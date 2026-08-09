from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.bootstrap import _ensure_trusted_ones_for_service
from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.channel.infrastructure.connector_registry import (
    DINGTALK_STREAM_CONNECTOR_TYPE,
    ConnectorRegistry,
)
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    CreateAgentJobService,
)
from app.shared.config import Settings
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.runtime_config_loader import _service_requires_master_key


@pytest.mark.parametrize(
    "service_name",
    (
        "agent-worker",
        "job-dispatch-worker",
        "webhook-worker",
    ),
)
def test_non_decrypting_workers_do_not_require_platform_master_key(
    service_name: str,
) -> None:
    assert _service_requires_master_key(service_name) is False


@pytest.mark.parametrize(
    "service_name",
    (
        "api-server",
        "channel-dispatch-worker",
        "delivery-dispatch-worker",
        "attachment-worker",
    ),
)
def test_decrypting_services_require_platform_master_key(service_name: str) -> None:
    assert _service_requires_master_key(service_name) is True


def test_stream_dispatch_revalidates_connector_without_resolving_client_secret() -> None:
    repository = Mock()
    repository.get_connector.return_value = {
        "id": "connector-stream",
        "connector_type": DINGTALK_STREAM_CONNECTOR_TYPE,
        "name": "Stream",
        "enabled": True,
        "allow_ingress": True,
        "allow_delivery": False,
        "secret_ref": "secret://platform/dingtalk-client-secret",
    }
    resolver = Mock(side_effect=AssertionError("dispatch must not resolve client secret"))
    registry = ConnectorRegistry(repository, reference_resolver=resolver)

    connector = registry.require_dingtalk_stream_ingress("connector-stream")

    assert connector.id == "connector-stream"
    resolver.assert_not_called()


def test_stream_job_revalidates_ingress_and_reply_original_without_resolving_secret() -> None:
    registry = Mock()
    service = CreateAgentJobService.__new__(CreateAgentJobService)
    service.connector_registry = registry
    service.audit_service = Mock()
    command = CreateAgentJobCommand(
        idempotency_key="stream-event",
        user_message="hello",
        requester_id="user-1",
        source_channel="dingding_stream",
        source_connector_id="connector-stream",
        reply_route={
            "type": "dingtalk_stream_session_webhook",
            "connector_id": "connector-stream",
            "target": {},
        },
    )

    service._assert_connectors_allowed(command, command.reply_route)

    assert registry.require_dingtalk_stream_ingress.call_count == 2
    registry.require_ingress.assert_not_called()
    registry.require_delivery.assert_not_called()


def test_stream_reply_original_rejects_a_different_connector() -> None:
    registry = Mock()
    service = CreateAgentJobService.__new__(CreateAgentJobService)
    service.connector_registry = registry
    service.audit_service = Mock()
    command = CreateAgentJobCommand(
        idempotency_key="stream-event",
        user_message="hello",
        requester_id="user-1",
        source_channel="dingding_stream",
        source_connector_id="connector-stream",
        reply_route={
            "type": "dingtalk_stream_session_webhook",
            "connector_id": "connector-other",
            "target": {},
        },
    )

    with pytest.raises(NonRetryableExecutionError) as error:
        service._assert_connectors_allowed(command, command.reply_route)

    assert error.value.error_code == "dingtalk_stream_reply_connector_mismatch"
    registry.require_delivery.assert_not_called()


def test_worker_startup_never_mutates_trusted_provider_instance() -> None:
    repository = Mock()

    _ensure_trusted_ones_for_service(
        repository,
        settings=Settings(),
        service_name="agent-worker",
    )

    repository.ensure_trusted_ones.assert_not_called()


def test_agent_context_builds_model_binding_without_worker_dns_resolution() -> None:
    model_connection_service = Mock()
    model_connection_service.runtime_binding.return_value = Mock(
        config_hash="model-config-hash",
        connection_revision=7,
    )
    builder = AgentContextBuilder.__new__(AgentContextBuilder)
    builder.agent_config_service = Mock(
        model_connection_service=model_connection_service,
    )

    binding = builder._model_binding(
        {
            "model_connection": {
                "revision_id": "model-revision-7",
                "config_hash": "model-config-hash",
                "revision": 7,
            }
        }
    )

    assert binding is model_connection_service.runtime_binding.return_value
    model_connection_service.runtime_binding.assert_called_once_with(
        "model-revision-7",
        validate_dns=False,
    )


def test_api_startup_owns_trusted_provider_reconciliation() -> None:
    repository = Mock()

    _ensure_trusted_ones_for_service(
        repository,
        settings=Settings(),
        service_name="api-server",
    )

    repository.ensure_trusted_ones.assert_called_once()
