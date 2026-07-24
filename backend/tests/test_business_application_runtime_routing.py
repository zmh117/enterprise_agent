from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.modules.business_application.domain import (
    RuntimeReadinessEvaluator,
    RuntimeReason,
)
from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.channel.application.channel_ingress_service import (
    _business_application_routing_key,
)
from app.modules.channel.domain.channel_event import (
    ChannelAttachment,
    ChannelEvent,
    ChannelSource,
    ReplyRoute,
    RoutingContext,
)
from app.modules.agent.application.conversation_context import ConversationContextService
from app.modules.job.application.create_agent_job_service import _session_key
from app.modules.job.application.job_status_service import JobStatusService
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)
from backend.tests.test_unified_identity_rbac import csrf_headers, login


CONNECTOR_ID = "connector-dingtalk-stream-default"
SESSION_WEBHOOK = "https://oapi.dingtalk.com/robot/sendBySession"


class RecordingRejectionNotifier:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    def notify(
        self,
        *,
        conversation_id: str,
        session_webhook: str,
        session_webhook_expires: str,
        reason: str,
    ) -> bool:
        assert conversation_id
        assert session_webhook == SESSION_WEBHOOK
        self.reasons.append(reason)
        return True


class RecordingDeliveryAdapter:
    def __init__(self) -> None:
        self.routes: list[ReplyRoute] = []

    def send(
        self,
        *,
        connector: object,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        assert title
        assert text
        self.routes.append(route)


def _container(*, environment: str = "local", data_plane_enabled: bool = True) -> Container:
    settings = replace(control_plane_settings(), environment=environment)
    if not data_plane_enabled:
        settings = replace(
            settings,
            identity=replace(
                settings.identity,
                published_agent_runtime_enabled=False,
            ),
        )
    return build_test_container(settings, migrate=True, seed=True)


def _publish(
    container: Container,
    code: str,
    *,
    triggers: list[dict[str, Any]],
    deliveries: list[dict[str, Any]] | None = None,
    session_policy: dict[str, Any] | None = None,
    execution_policy: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code=code,
        name=code,
        description="runtime routing test",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["triggers"] = triggers
    payload["deliveries"] = deliveries or [
        {
            "delivery_type": "reply_original",
            "connector_id": CONNECTOR_ID,
            "enabled": True,
            "config": {"target_reference": "", "reply_mode": "original"},
        }
    ]
    if session_policy is not None:
        payload["session_policy"] = session_policy
    if execution_policy is not None:
        payload["execution_policy"] = execution_policy
    revision = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    return application, revision, publication


def _trigger(
    *,
    trigger_type: str,
    routing_key: str,
    connector_id: str = CONNECTOR_ID,
) -> dict[str, Any]:
    return {
        "trigger_type": trigger_type,
        "connector_id": connector_id,
        "routing_key": routing_key,
        "actor_policy": "CURRENT_SENDER",
        "service_account_user_id": "",
        "enabled": True,
        "config": {
            "conversation_type": ("group" if trigger_type == "dingtalk_group" else "private"),
            "require_mention": trigger_type == "dingtalk_group",
            "webhook_definition_id": "",
        },
    }


def _activate(
    container: Container,
    code: str,
    publication: dict[str, Any],
    *,
    environment: str,
) -> dict[str, Any]:
    return container.business_application_service.activate(
        actor_id="user_local_admin",
        code=code,
        environment=environment,
        publication_id=str(publication["id"]),
        expected_revision=0,
    )


def _stream_payload(
    *,
    message_id: str,
    robot_code: str = "diagnostic-bot",
    conversation_id: str = "conversation-private",
    conversation_type: str = "1",
    routing_environment: str = "",
    session_webhook: str = SESSION_WEBHOOK,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "conversationId": conversation_id,
        "conversationType": conversation_type,
        "senderStaffId": "local-user",
        "msgId": message_id,
        "robotCode": robot_code,
        "sessionWebhook": session_webhook,
        "text": {"content": "diagnose the current incident"},
    }
    if routing_environment:
        payload["routing"] = {
            "project_code": "default",
            "environment": routing_environment,
        }
    return payload


def test_runtime_readiness_reports_gate_environment_and_component_states() -> None:
    snapshot = {
        "agent": {"id": "agent-publication", "config_hash": "hash"},
        "triggers": [_trigger(trigger_type="dingtalk_private", routing_key="bot:bot-a")],
        "deliveries": [
            {
                "delivery_type": "reply_original",
                "connector_id": CONNECTOR_ID,
                "enabled": True,
            }
        ],
        "session_policy": {
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
        },
        "execution_policy": {"max_turns": 12},
    }
    disabled = RuntimeReadinessEvaluator(
        data_plane_enabled=False,
        runtime_environment="local",
    ).evaluate(snapshot=snapshot, deployment={"environment": "local", "active": True})
    assert disabled.runtime_status.value == "not_wired"
    assert disabled.reason_code == RuntimeReason.DATA_PLANE_DISABLED.value

    other_environment = RuntimeReadinessEvaluator(
        data_plane_enabled=True,
        runtime_environment="local",
    ).evaluate(snapshot=snapshot, deployment={"environment": "test", "active": True})
    assert other_environment.runtime_status.value == "not_wired"
    assert other_environment.reason_code == RuntimeReason.NOT_CURRENT_RUNTIME_ENVIRONMENT.value

    current = RuntimeReadinessEvaluator(
        data_plane_enabled=True,
        runtime_environment="local",
    ).evaluate(snapshot=snapshot, deployment={"environment": "local", "active": True})
    assert current.runtime_wired is True
    assert current.runtime_status.value == "wired"
    assert current.components["trigger_routing"].status.value == "wired"
    assert current.components["execution_policy"].status.value == "wired"
    assert current.components["session_policy"].status.value == "wired"
    assert current.components["retention_policy"].status.value == "stored_only"
    assert current.components["retention_policy"].impact.value == "governance"
    assert current.components["retention_policy"].fields["retention_days"] == "stored_only"


def test_runtime_environment_is_separate_from_business_data_environment() -> None:
    container = _container(environment="local")
    _, _, publication = _publish(
        container,
        "local-runtime-sanjiu-data",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    deployment = _activate(
        container,
        "local-runtime-sanjiu-data",
        publication,
        environment="local",
    )
    assert deployment["runtime_environment"] == "local"

    result = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(
            message_id="environment-split",
            routing_environment="sanjiu",
        ),
        correlation_id="correlation-environment-split",
    )
    assert result.accepted is True
    job = container.agent_repository.get_job(result.job_id)
    assert job.business_application_code == "local-runtime-sanjiu-data"
    assert job.business_application_publication_id == publication["id"]
    assert job.routing_context["environment"] == "sanjiu"


def test_private_and_group_routing_keys_only_use_trusted_bot_or_conversation_identity() -> None:
    private = ChannelEvent(
        source=ChannelSource(
            type="dingding_stream",
            connector_id=CONNECTOR_ID,
            event_id="event-private",
            actor_id="user-a",
            conversation_id="user-specific-conversation",
            metadata={
                "conversation_type": "private",
                "bot_identity": " Shared-Bot ",
            },
        ),
        delivery=ReplyRoute(type="none"),
        routing=RoutingContext(environment="forged-environment"),
        message="forged bot:other-bot",
    )
    second_user = replace(
        private,
        source=replace(
            private.source,
            actor_id="user-b",
            conversation_id="another-private-conversation",
        ),
    )
    group = replace(
        private,
        source=replace(
            private.source,
            actor_id="group-user",
            conversation_id=" OpenConversation-42 ",
            metadata={"conversation_type": "group", "bot_identity": "ignored-bot"},
        ),
    )
    assert _business_application_routing_key(private, "dingtalk_private") == "bot:shared-bot"
    assert _business_application_routing_key(second_user, "dingtalk_private") == "bot:shared-bot"
    assert (
        _business_application_routing_key(group, "dingtalk_group")
        == "conversation:openconversation-42"
    )


def test_not_matched_and_integrity_failure_are_rejected_without_job() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "blocked-route",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    _activate(container, "blocked-route", publication, environment="local")

    notifier = RecordingRejectionNotifier()
    container.dingtalk_stream_message_service.rejection_notifier = notifier
    jobs_before = container.agent_repository.count_rows("agent_job")
    unmatched = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(
            message_id="not-matched",
            robot_code="another-bot",
        ),
        correlation_id="correlation-not-matched",
    )
    assert unmatched.accepted is False
    assert unmatched.status == "rejected"
    assert notifier.reasons == ["当前机器人未配置可用的业务应用，请联系管理员"]
    assert container.agent_repository.count_rows("agent_job") == jobs_before
    assert len(container.message_bus.jobs) == jobs_before

    container.database.execute(
        """
        update business_application_publication
           set config_hash = ?
         where id = ?
        """,
        ("tampered", publication["id"]),
    )
    blocked = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="blocked-integrity"),
        correlation_id="correlation-blocked",
    )
    assert blocked.accepted is False
    assert blocked.status == "rejected"
    assert notifier.reasons == [
        "当前机器人未配置可用的业务应用，请联系管理员",
        "Business Application configuration is temporarily unavailable",
    ]
    assert container.agent_repository.count_rows("agent_job") == jobs_before
    assert len(container.message_bus.jobs) == jobs_before


def test_matched_job_pins_provenance_and_duplicate_event_is_idempotent() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "provenance-route",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    deployment = _activate(
        container,
        "provenance-route",
        publication,
        environment="local",
    )
    payload = _stream_payload(message_id="same-external-event")
    first = container.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="correlation-first",
    )
    repeated = container.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="correlation-repeated",
    )
    assert first.job_id == repeated.job_id
    assert container.agent_repository.count_rows("agent_job") == 1
    assert len(container.message_bus.jobs) == 1
    job = container.agent_repository.get_job(first.job_id)
    assert job.business_application_code == "provenance-route"
    assert job.business_application_publication_id == publication["id"]
    assert job.business_application_deployment_id == deployment["id"]
    assert job.business_application_route_id
    assert job.business_application_config_hash == publication["config_hash"]
    assert job.business_application_route_decision["resolution_outcome"] == "matched"
    assert "sessionWebhook" not in json.dumps(job.business_application_route_decision)
    queued = container.message_bus.jobs[0]
    assert set(vars(queued)) == {"job_id", "correlation_id"}


def test_activation_is_local_only_and_rejects_invalid_runtime_bindings() -> None:
    container = _container(environment="local")
    _, _, legacy_publication = _publish(
        container,
        "legacy-route",
        triggers=[_trigger(trigger_type="dingtalk_private", routing_key="default")],
    )
    with pytest.raises(NonRetryableExecutionError) as legacy_error:
        _activate(container, "legacy-route", legacy_publication, environment="local")
    assert legacy_error.value.error_code == "validation_failed"
    assert legacy_error.value.field_errors[0]["reason_code"] == "legacy_routing_key"

    with pytest.raises(NonRetryableExecutionError) as environment_error:
        _activate(
            container,
            "legacy-route",
            legacy_publication,
            environment="test",
        )
    assert environment_error.value.field_errors == [
        {
            "field": "environment",
            "message": "Only the local Business Application environment is supported",
        }
    ]

    _, _, mismatch_publication = _publish(
        container,
        "delivery-mismatch",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    mismatched_snapshot = dict(mismatch_publication["snapshot"])
    mismatched_snapshot["deliveries"] = [
        {
            **dict(mismatched_snapshot["deliveries"][0]),
            "connector_id": "connector-another-stream",
        }
    ]
    mismatched_hash = snapshot_hash(mismatched_snapshot)
    container.database.execute(
        """
        update business_application_publication
           set snapshot_json = ?, config_hash = ?
         where id = ?
        """,
        (
            json.dumps(mismatched_snapshot),
            mismatched_hash,
            mismatch_publication["id"],
        ),
    )
    with pytest.raises(NonRetryableExecutionError) as mismatch_error:
        _activate(
            container,
            "delivery-mismatch",
            mismatch_publication,
            environment="local",
        )
    assert mismatch_error.value.field_errors[0]["reason_code"] == "delivery_connector_mismatch"


def test_session_policy_is_application_scoped_and_publication_upgrade_does_not_split_session() -> (
    None
):
    container = _container()
    policy = {
        "conversation_mode": "channel",
        "recent_message_limit": 1,
        "retention_days": 30,
        "continuous_conversation_enabled": True,
        "attachments_enabled": False,
    }
    application, _, publication_v1 = _publish(
        container,
        "session-scope",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
        session_policy=policy,
    )
    deployment_v1 = _activate(
        container,
        "session-scope",
        publication_v1,
        environment="local",
    )
    first = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="session-v1"),
        correlation_id="correlation-session-v1",
    )
    latest = container.business_application_repository.get_by_code("session-scope")
    payload_v2 = draft_payload(route="bot:diagnostic-bot")
    payload_v2["session_policy"] = policy
    revision_v2 = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="session-scope",
        expected_revision=int(latest["revision"]),
        payload=payload_v2,
    )
    publication_v2 = container.business_application_service.publish(
        actor_id="user_local_admin",
        code="session-scope",
        revision_id=str(revision_v2["id"]),
    )
    container.business_application_service.activate(
        actor_id="user_local_admin",
        code="session-scope",
        environment="local",
        publication_id=str(publication_v2["id"]),
        expected_revision=int(deployment_v1["revision"]),
    )
    second = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="session-v2"),
        correlation_id="correlation-session-v2",
    )
    first_job = container.agent_repository.get_job(first.job_id)
    second_job = container.agent_repository.get_job(second.job_id)
    assert first_job.session_id == second_job.session_id
    assert first_job.business_application_publication_id == publication_v1["id"]
    assert second_job.business_application_publication_id == publication_v2["id"]
    session = container.agent_repository.get_session(second_job.session_id)
    assert session.business_application_id == application["id"]
    assert session.recent_message_limit == 1
    assert session.session_policy["retention_days"] == 30


def test_event_fixed_agent_conflict_is_rejected_before_job_creation() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "agent-conflict",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    _activate(container, "agent-conflict", publication, environment="local")
    event = container.dingtalk_stream_message_service.to_channel_event(
        message=container.dingtalk_stream_message_service.parse_message(
            _stream_payload(message_id="agent-conflict")
        ),
        payload=_stream_payload(message_id="agent-conflict"),
        source_connector_id=CONNECTOR_ID,
        correlation_id="correlation-agent-conflict",
    )
    event = replace(event, agent_publication_id="another-agent-publication")
    with pytest.raises(NonRetryableExecutionError) as conflict:
        container.channel_ingress_service.accept(event)
    assert conflict.value.error_code == "agent_override_conflict"
    assert container.agent_repository.count_rows("agent_job") == 0


def test_deactivation_releases_route_but_existing_job_keeps_fixed_version() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "deactivation-route",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    deployment = _activate(
        container,
        "deactivation-route",
        publication,
        environment="local",
    )
    before = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="before-deactivation"),
        correlation_id="correlation-before-deactivation",
    )
    container.business_application_service.deactivate(
        actor_id="user_local_admin",
        code="deactivation-route",
        environment="local",
        expected_revision=int(deployment["revision"]),
    )
    notifier = RecordingRejectionNotifier()
    container.dingtalk_stream_message_service.rejection_notifier = notifier
    jobs_before = container.agent_repository.count_rows("agent_job")
    after = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="after-deactivation"),
        correlation_id="correlation-after-deactivation",
    )
    before_job = container.agent_repository.get_job(before.job_id)
    assert before_job.business_application_publication_id == publication["id"]
    assert after.accepted is False
    assert after.status == "rejected"
    assert notifier.reasons == ["当前机器人未配置可用的业务应用，请联系管理员"]
    assert container.agent_repository.count_rows("agent_job") == jobs_before


def test_missing_bot_identity_does_not_guess_a_route() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "missing-bot",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    _activate(container, "missing-bot", publication, environment="local")
    container.dingtalk_stream_message_service.default_robot_code = ""
    connector = container.connector_registry.get(CONNECTOR_ID)
    assert connector is not None
    connector.metadata.pop("default_robot_code", None)
    notifier = RecordingRejectionNotifier()
    container.dingtalk_stream_message_service.rejection_notifier = notifier
    jobs_before = container.agent_repository.count_rows("agent_job")
    result = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="missing-bot-event", robot_code=""),
        correlation_id="correlation-missing-bot",
    )
    assert result.accepted is False
    assert result.status == "rejected"
    assert notifier.reasons == ["当前机器人未配置可用的业务应用，请联系管理员"]
    assert container.agent_repository.count_rows("agent_job") == jobs_before


def test_same_bot_group_routes_are_split_by_conversation_and_reply_to_original_session() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "group-routing",
        triggers=[
            _trigger(
                trigger_type="dingtalk_group",
                routing_key="conversation:group-a",
            ),
            _trigger(
                trigger_type="dingtalk_group",
                routing_key="conversation:group-b",
            ),
        ],
    )
    _activate(container, "group-routing", publication, environment="local")
    first = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(
            message_id="group-a-message",
            conversation_id="group-a",
            conversation_type="2",
        ),
        correlation_id="correlation-group-a",
    )
    second = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(
            message_id="group-b-message",
            conversation_id="group-b",
            conversation_type="2",
        ),
        correlation_id="correlation-group-b",
    )
    first_job = container.agent_repository.get_job(first.job_id)
    second_job = container.agent_repository.get_job(second.job_id)
    assert first_job.business_application_code == "group-routing"
    assert second_job.business_application_code == "group-routing"
    assert first_job.business_application_route_id != second_job.business_application_route_id
    assert first_job.reply_route["type"] == "dingtalk_stream_session_webhook"
    assert second_job.reply_route["type"] == "dingtalk_stream_session_webhook"

    adapter = RecordingDeliveryAdapter()
    container.result_delivery_service.adapters["dingtalk_stream_session_webhook"] = adapter
    status_service = JobStatusService(container.agent_repository)
    assert status_service.claim(first.job_id, "runtime-test-worker") is not None
    status_service.succeed(first.job_id, "group result")
    container.result_delivery_service.deliver_job_result(first.job_id)
    assert len(adapter.routes) == 1
    assert adapter.routes[0].target["conversation_id"] == "group-a"


def test_routed_job_pins_requested_and_effective_execution_policy() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "execution-policy-routing",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
        execution_policy={
            "max_turns": 99,
            "timeout_seconds": 120,
            "max_tool_calls": 4,
        },
    )
    _activate(
        container,
        "execution-policy-routing",
        publication,
        environment="local",
    )

    result = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="execution-policy-routing"),
        correlation_id="correlation-execution-policy-routing",
    )
    job = container.agent_repository.get_job(result.job_id)

    assert job.execution_policy is not None
    assert job.execution_policy["schema_version"] == 1
    assert job.execution_policy["requested"] == {
        "max_turns": 99,
        "timeout_seconds": 120,
        "max_tool_calls": 4,
    }
    assert job.execution_policy["effective"] == {
        "max_turns": 12,
        "timeout_seconds": 120,
        "max_tool_calls": 4,
    }
    assert (
        job.execution_policy["sources"]["business_application_publication_id"]
        == publication["id"]
    )
    assert (
        job.execution_policy["sources"]["agent_publication_id"]
        == "agent_publication_default_v1"
    )


def test_missing_group_conversation_id_is_rejected_without_route_guessing() -> None:
    container = _container()
    before = container.agent_repository.count_rows("agent_job")
    result = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationType": "2",
            "senderStaffId": "local-user",
            "msgId": "missing-group-conversation",
            "robotCode": "diagnostic-bot",
            "sessionWebhook": SESSION_WEBHOOK,
            "text": {"content": "group message"},
        },
        correlation_id="correlation-missing-group",
    )
    assert result.accepted is False
    assert result.status == "rejected"
    assert container.agent_repository.count_rows("agent_job") == before


def test_session_key_modes_and_different_applications_are_isolated() -> None:
    common = {
        "source_channel": "dingding_stream",
        "connector_id": CONNECTOR_ID,
        "project_code": "default",
        "conversation_type": "group",
        "conversation_id": "group-a",
        "requester_id": "user-a",
        "bot_identity": "diagnostic-bot",
    }
    channel = _session_key(
        **common,
        business_application_id="application-a",
        conversation_mode="channel",
    )
    actor = _session_key(
        **common,
        business_application_id="application-a",
        conversation_mode="actor",
    )
    application = _session_key(
        **common,
        business_application_id="application-a",
        conversation_mode="application",
    )
    other_application = _session_key(
        **common,
        business_application_id="application-b",
        conversation_mode="channel",
    )
    assert len({channel, actor, application, other_application}) == 4

    container = _container()
    _, _, first_publication = _publish(
        container,
        "session-application-a",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
        session_policy={
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
            "continuous_conversation_enabled": True,
            "attachments_enabled": False,
        },
    )
    first_deployment = _activate(
        container,
        "session-application-a",
        first_publication,
        environment="local",
    )
    first = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="session-application-a"),
        correlation_id="correlation-session-application-a",
    )
    container.business_application_service.deactivate(
        actor_id="user_local_admin",
        code="session-application-a",
        environment="local",
        expected_revision=int(first_deployment["revision"]),
    )
    _, _, second_publication = _publish(
        container,
        "session-application-b",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
        session_policy={
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
            "continuous_conversation_enabled": True,
            "attachments_enabled": False,
        },
    )
    _activate(
        container,
        "session-application-b",
        second_publication,
        environment="local",
    )
    second = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="session-application-b"),
        correlation_id="correlation-session-application-b",
    )
    assert (
        container.agent_repository.get_job(first.job_id).session_id
        != container.agent_repository.get_job(second.job_id).session_id
    )


def test_application_recent_message_limit_and_attachment_policy_are_enforced() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "bounded-session-policy",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
        session_policy={
            "conversation_mode": "channel",
            "recent_message_limit": 1,
            "retention_days": 30,
            "continuous_conversation_enabled": True,
            "attachments_enabled": False,
        },
    )
    _activate(container, "bounded-session-policy", publication, environment="local")
    first = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="bounded-message-1"),
        correlation_id="correlation-bounded-1",
    )
    second = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(message_id="bounded-message-2"),
        correlation_id="correlation-bounded-2",
    )
    assert first.accepted is second.accepted is True
    second_job = container.agent_repository.get_job(second.job_id)
    context = ConversationContextService(
        container.agent_repository,
        container.settings.conversation,
    ).build(second_job)
    assert len(context.recent_messages) == 1
    assert context.recent_messages[0]["job_id"] == second.job_id

    payload = _stream_payload(message_id="attachment-disabled")
    event = container.dingtalk_stream_message_service.to_channel_event(
        message=container.dingtalk_stream_message_service.parse_message(payload),
        payload=payload,
        source_connector_id=CONNECTOR_ID,
        correlation_id="correlation-attachment-disabled",
    )
    event = replace(
        event,
        attachments=(
            ChannelAttachment(
                media_type="file",
                file_name="evidence.png",
                source_credential="temporary-download-code",
                declared_mime="image/png",
            ),
        ),
    )
    with pytest.raises(NonRetryableExecutionError) as disabled:
        container.channel_ingress_service.accept(event)
    assert disabled.value.safe_message == "Attachments are not enabled for this application"


def test_route_audit_is_correlated_hashed_and_never_contains_session_credentials() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "audit-safe-route",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    _activate(container, "audit-safe-route", publication, environment="local")
    secret_webhook = f"{SESSION_WEBHOOK}?access_token=must-never-leak"
    result = container.dingtalk_stream_message_service.handle_callback(
        payload=_stream_payload(
            message_id="audit-safe-message",
            session_webhook=secret_webhook,
        ),
        correlation_id="correlation-audit-safe",
    )
    assert result.accepted is True
    rows = container.database.execute(
        """
        select event_type, summary, payload_summary
          from audit_event
         where event_type like 'business_application.route.%'
            or event_type like 'dingtalk.stream.%'
         order by created_at, id
        """
    )
    serialized = json.dumps(rows)
    assert "must-never-leak" not in serialized
    assert secret_webhook not in serialized
    matched = next(
        row for row in rows if row["event_type"] == "business_application.route.job_created"
    )
    payload = json.loads(json.loads(matched["payload_summary"])["payload"])
    assert payload["correlation_id"] == "correlation-audit-safe"
    assert payload["business_application_code"] == "audit-safe-route"
    assert payload["business_application_publication_id"] == publication["id"]
    assert payload["routing_key_hash"]
    assert "diagnostic-bot" not in json.dumps(payload)


def test_unified_identity_and_rbac_fail_before_application_route_or_job_creation() -> None:
    container = _container()
    _, _, publication = _publish(
        container,
        "identity-first-route",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    _activate(container, "identity-first-route", publication, environment="local")
    notifier = RecordingRejectionNotifier()
    container.dingtalk_stream_message_service.rejection_notifier = notifier
    result = container.dingtalk_stream_message_service.handle_callback(
        payload={
            **_stream_payload(message_id="unknown-identity"),
            "senderStaffId": "unknown-dingtalk-user",
        },
        correlation_id="correlation-identity-first",
    )
    assert result.accepted is False
    assert result.status == "permission_denied"
    assert container.agent_repository.count_rows("agent_job") == 0
    route_audits = container.database.execute(
        """
        select event_type from audit_event
         where event_type like 'business_application.route.%'
        """
    )
    assert route_audits == []


def test_management_api_exposes_uniform_runtime_contract_and_preflight_errors() -> None:
    settings = replace(control_plane_settings(), environment="local")
    container = build_test_container(settings, migrate=True, seed=True)
    _, _, publication = _publish(
        container,
        "runtime-contract",
        triggers=[
            _trigger(
                trigger_type="dingtalk_private",
                routing_key="bot:diagnostic-bot",
            )
        ],
    )
    _activate(container, "runtime-contract", publication, environment="local")
    _, _, legacy_publication = _publish(
        container,
        "runtime-contract-legacy",
        triggers=[_trigger(trigger_type="dingtalk_private", routing_key="default")],
    )
    app = create_app(settings, container_factory=lambda _: container)
    with TestClient(app) as client:
        csrf = login(client)
        listed = client.get("/api/admin/business-applications")
        detail = client.get("/api/admin/business-applications/runtime-contract")
        publications = client.get("/api/admin/business-applications/runtime-contract/publications")
        effective = client.get(
            "/api/admin/business-applications/runtime-contract/effective",
            params={"environment": "local"},
        )
        prepared = client.post(
            "/api/admin/business-applications/runtime-contract/environments/staging/activate",
            headers=csrf_headers(csrf),
            json={
                "publication_id": publication["id"],
                "expected_revision": 0,
            },
        )
        invalid = client.post(
            "/api/admin/business-applications/runtime-contract-legacy/environments/local/activate",
            headers=csrf_headers(csrf),
            json={
                "publication_id": legacy_publication["id"],
                "expected_revision": 0,
            },
        )
        openapi = client.get("/openapi.json").json()
        container.database.execute(
            """
            update business_application_publication
               set config_hash = 'tampered'
             where id = ?
            """,
            (publication["id"],),
        )
        blocked = client.get("/api/admin/business-applications/runtime-contract")

    assert listed.status_code == detail.status_code == publications.status_code == 200
    assert effective.status_code == 200
    for value in (
        next(item for item in listed.json()["items"] if item["code"] == "runtime-contract"),
        detail.json()["application"],
        publications.json()["items"][0],
        effective.json(),
        effective.json()["deployment"],
    ):
        assert value["runtime_wired"] is True
        assert value["runtime_status"] == "wired"
        assert value["runtime_environment"] == "local"
        assert value["runtime_components"]["trigger_routing"]["status"] == "wired"
    assert prepared.status_code == 422
    assert prepared.json()["detail"]["field_errors"][0]["field"] == "environment"
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["field_errors"][0]["reason_code"] == "legacy_routing_key"
    runtime_schema = openapi["components"]["schemas"]["ApplicationSummaryResponse"]
    assert "runtime_status" in runtime_schema["properties"]

    assert blocked.status_code == 200
    assert blocked.json()["application"]["runtime_status"] == "blocked"
    assert blocked.json()["application"]["runtime_wired"] is False
