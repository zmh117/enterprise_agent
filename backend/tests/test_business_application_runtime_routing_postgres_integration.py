from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any

import pytest

from app.bootstrap import Container, build_test_container
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)
from backend.tests.test_business_application_runtime_routing import (
    CONNECTOR_ID,
    RecordingDeliveryAdapter,
    RecordingRejectionNotifier,
    _stream_payload,
    _trigger,
)


POSTGRES_DSN = os.getenv("RUNTIME_ROUTING_POSTGRES_DSN", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="set RUNTIME_ROUTING_POSTGRES_DSN to run Docker Compose PostgreSQL acceptance",
)


def _container(*, data_plane_enabled: bool) -> Container:
    settings = replace(
        control_plane_settings(),
        database_dsn=POSTGRES_DSN,
        environment="local",
    )
    settings = replace(
        settings,
        identity=replace(
            settings.identity,
            published_agent_runtime_enabled=data_plane_enabled,
        ),
    )
    return build_test_container(settings, migrate=True, seed=True)


def _application_payload(*, max_turns: int) -> dict[str, Any]:
    payload = draft_payload()
    payload["triggers"] = [
        _trigger(
            trigger_type="dingtalk_private",
            routing_key="bot:docker-runtime-bot",
        ),
        _trigger(
            trigger_type="dingtalk_group",
            routing_key="conversation:docker-runtime-group",
        ),
    ]
    payload["deliveries"] = [
        {
            "delivery_type": "reply_original",
            "connector_id": CONNECTOR_ID,
            "enabled": True,
            "config": {"target_reference": "", "reply_mode": "original"},
        }
    ]
    payload["execution_policy"] = {
        "max_turns": max_turns,
        "timeout_seconds": 300,
        "max_tool_calls": 30,
    }
    return payload


def _save_and_publish(
    container: Container,
    *,
    code: str,
    expected_revision: int,
    max_turns: int,
) -> dict[str, Any]:
    revision = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=expected_revision,
        payload=_application_payload(max_turns=max_turns),
    )
    return container.business_application_service.publish(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )


def _private_payload(message_id: str, *, bot: str = "docker-runtime-bot") -> dict[str, Any]:
    return _stream_payload(
        message_id=message_id,
        robot_code=bot,
        routing_environment="sanjiu",
    )


def _group_payload(message_id: str) -> dict[str, Any]:
    return _stream_payload(
        message_id=message_id,
        robot_code="docker-runtime-bot",
        conversation_id="docker-runtime-group",
        conversation_type="2",
        routing_environment="sanjiu",
    )


def test_docker_postgres_runtime_takeover_and_provenance_acceptance() -> None:
    code = "docker-runtime-routing-acceptance"
    disabled = _container(data_plane_enabled=False)
    application = disabled.business_application_service.create(
        actor_id="user_local_admin",
        code=code,
        name="Docker runtime routing acceptance",
        description="Disposable acceptance fixture",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    publication_v1 = _save_and_publish(
        disabled,
        code=code,
        expected_revision=int(application["revision"]),
        max_turns=12,
    )
    deployment_v1 = disabled.business_application_service.activate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        publication_id=str(publication_v1["id"]),
        expected_revision=0,
    )
    assert deployment_v1["runtime_status"] == "not_wired"
    assert deployment_v1["reason_code"] == "data_plane_disabled"

    disabled_notifier = RecordingRejectionNotifier()
    disabled.dingtalk_stream_message_service.rejection_notifier = disabled_notifier
    jobs_before_disabled = disabled.agent_repository.count_rows("agent_job")
    rejected_while_disabled = disabled.dingtalk_stream_message_service.handle_callback(
        payload=_private_payload("docker-gate-off"),
        correlation_id="docker-correlation-gate-off",
    )
    assert rejected_while_disabled.accepted is False
    assert disabled.agent_repository.count_rows("agent_job") == jobs_before_disabled
    assert disabled_notifier.reasons == [
        "Business Application configuration is temporarily unavailable"
    ]

    enabled = _container(data_plane_enabled=True)
    effective = enabled.business_application_resolver.resolve_active(code, "local")
    assert effective["runtime_wired"] is True
    assert effective["runtime_status"] == "partially_wired"

    private = enabled.dingtalk_stream_message_service.handle_callback(
        payload=_private_payload("docker-private-v1"),
        correlation_id="docker-correlation-private-v1",
    )
    private_job = enabled.agent_repository.get_job(private.job_id)
    assert private_job.business_application_code == code
    assert private_job.business_application_publication_id == publication_v1["id"]
    assert private_job.business_application_deployment_id == deployment_v1["id"]
    assert private_job.business_application_route_id
    assert private_job.routing_context["environment"] == "sanjiu"

    group = enabled.dingtalk_stream_message_service.handle_callback(
        payload=_group_payload("docker-group-v1"),
        correlation_id="docker-correlation-group-v1",
    )
    group_job = enabled.agent_repository.get_job(group.job_id)
    assert group_job.business_application_code == code
    assert group_job.business_application_route_id != private_job.business_application_route_id
    assert group_job.routing_context["environment"] == "sanjiu"

    unmatched_notifier = RecordingRejectionNotifier()
    enabled.dingtalk_stream_message_service.rejection_notifier = unmatched_notifier
    jobs_before_unmatched = enabled.agent_repository.count_rows("agent_job")
    unmatched = enabled.dingtalk_stream_message_service.handle_callback(
        payload=_private_payload("docker-unmatched", bot="docker-other-bot"),
        correlation_id="docker-correlation-unmatched",
    )
    assert unmatched.accepted is False
    assert enabled.agent_repository.count_rows("agent_job") == jobs_before_unmatched
    assert unmatched_notifier.reasons == ["当前机器人未配置可用的业务应用，请联系管理员"]

    duplicate_payload = _private_payload("docker-duplicate")
    duplicate_first = enabled.dingtalk_stream_message_service.handle_callback(
        payload=duplicate_payload,
        correlation_id="docker-correlation-duplicate-first",
    )
    duplicate_second = enabled.dingtalk_stream_message_service.handle_callback(
        payload=duplicate_payload,
        correlation_id="docker-correlation-duplicate-second",
    )
    assert duplicate_first.job_id == duplicate_second.job_id
    assert (
        enabled.database.execute_one(
            "select count(*) as count from agent_job where external_event_id = ?",
            ("docker-duplicate",),
        )["count"]
        == 1
    )

    delivery_adapter = RecordingDeliveryAdapter()
    enabled.result_delivery_service.adapters["dingtalk_stream_session_webhook"] = delivery_adapter
    answer = enabled.agent_executor.execute(
        private.job_id,
        worker_id="docker-runtime-acceptance",
        correlation_id="docker-correlation-private-v1",
    )
    assert answer
    assert delivery_adapter.routes
    assert (
        enabled.agent_repository.list_delivery_attempts(private.job_id)[0]["status"] == "SUCCEEDED"
    )

    latest = enabled.business_application_repository.get_by_code(code)
    publication_v2 = _save_and_publish(
        enabled,
        code=code,
        expected_revision=int(latest["revision"]),
        max_turns=13,
    )
    deployment_v2 = enabled.business_application_service.activate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        publication_id=str(publication_v2["id"]),
        expected_revision=int(deployment_v1["revision"]),
    )
    queued_v2 = enabled.dingtalk_stream_message_service.handle_callback(
        payload=_private_payload("docker-private-v2"),
        correlation_id="docker-correlation-private-v2",
    )
    queued_v2_job = enabled.agent_repository.get_job(queued_v2.job_id)
    assert queued_v2_job.business_application_publication_id == publication_v2["id"]

    rolled_back = enabled.business_application_service.activate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        publication_id=str(publication_v1["id"]),
        expected_revision=int(deployment_v2["revision"]),
    )
    after_rollback = enabled.dingtalk_stream_message_service.handle_callback(
        payload=_private_payload("docker-after-rollback"),
        correlation_id="docker-correlation-after-rollback",
    )
    assert (
        enabled.agent_repository.get_job(after_rollback.job_id).business_application_publication_id
        == publication_v1["id"]
    )
    assert (
        enabled.agent_repository.get_job(queued_v2.job_id).business_application_publication_id
        == publication_v2["id"]
    )

    enabled.database.execute(
        "update business_application_publication set config_hash = ? where id = ?",
        ("tampered", publication_v1["id"]),
    )
    notifier = RecordingRejectionNotifier()
    enabled.dingtalk_stream_message_service.rejection_notifier = notifier
    jobs_before_blocked = int(
        enabled.database.execute_one("select count(*) as count from agent_job")["count"]
    )
    blocked = enabled.dingtalk_stream_message_service.handle_callback(
        payload=_private_payload("docker-blocked"),
        correlation_id="docker-correlation-blocked",
    )
    assert blocked.accepted is False
    assert notifier.reasons == ["Business Application configuration is temporarily unavailable"]
    assert (
        enabled.database.execute_one("select count(*) as count from agent_job")["count"]
        == jobs_before_blocked
    )
    enabled.database.execute(
        "update business_application_publication set config_hash = ? where id = ?",
        (publication_v1["config_hash"], publication_v1["id"]),
    )

    deactivated = enabled.business_application_service.deactivate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        expected_revision=int(rolled_back["revision"]),
    )
    assert deactivated["active"] is False
    jobs_before_deactivation_message = enabled.agent_repository.count_rows("agent_job")
    after_deactivation = enabled.dingtalk_stream_message_service.handle_callback(
        payload=_private_payload("docker-after-deactivation"),
        correlation_id="docker-correlation-after-deactivation",
    )
    assert after_deactivation.accepted is False
    assert enabled.agent_repository.count_rows("agent_job") == jobs_before_deactivation_message

    evidence = enabled.database.execute_one(
        """
        select
          (select count(*) from business_application where code = ?) as applications,
          (select count(*) from business_application_publication where application_id = ?) as publications,
          (select count(*) from business_application_deployment where application_id = ?) as deployments,
          (select count(*) from agent_job where business_application_id = ?) as attributed_jobs,
          (select count(*) from delivery_attempt where job_id = ?) as deliveries
        """,
        (
            code,
            application["id"],
            application["id"],
            application["id"],
            private.job_id,
        ),
    )
    assert evidence == {
        "applications": 1,
        "publications": 2,
        "deployments": 1,
        "attributed_jobs": 5,
        "deliveries": 1,
    }
    audit_rows = enabled.database.execute(
        """
        select event_type, payload_summary
          from audit_event
         where event_type like 'business_application.runtime.%%'
            or event_type like 'business_application.route.%%'
            or event_type = 'delivery.completed'
        """
    )
    event_types = {row["event_type"] for row in audit_rows}
    assert {
        "business_application.runtime.activated",
        "business_application.runtime.rolled_back",
        "business_application.runtime.deactivated",
        "business_application.route.matched",
        "business_application.route.not_matched",
        "business_application.route.blocked",
        "business_application.route.job_created",
        "delivery.completed",
    } <= event_types
    serialized_audit = json.dumps(audit_rows)
    assert "sendBySession" not in serialized_audit
    assert "access_token" not in serialized_audit
