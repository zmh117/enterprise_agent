from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.admin.application.contracts import PageWindow, TimeWindow
from app.modules.admin.application.dashboard_service import DashboardQueryService
from app.modules.admin.application.scope import AdminScope
from app.modules.admin.infrastructure import AdminReadRepository
from app.modules.job.application.create_agent_job_service import _execution_scope_hash
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_unified_identity_rbac import csrf_headers, login, unified_settings


def execution_policy_snapshot() -> dict[str, object]:
    values = {
        "max_turns": 12,
        "timeout_seconds": 300,
        "max_tool_calls": 30,
    }
    return {
        "schema_version": 1,
        "requested": dict(values),
        "effective": dict(values),
        "sources": {"source_kind": "runtime_default"},
    }


def test_admin_capabilities_are_permission_derived_and_scope_safe() -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client)
        response = client.get("/api/admin/capabilities")

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] != "-"
    body = response.json()
    assert body["subject"]["id"] == "user_local_admin"
    assert "dashboard.read" in body["capabilities"]
    assert "tools.manage" in body["capabilities"]
    assert body["data_scope"] == {"mode": "restricted", "grants": []}
    assert "matched_policy_ids" not in str(body)
    assert "subject_code" not in str(body)


def test_admin_capabilities_fail_closed_without_policy_and_audit_denial() -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.identity_admin_service.create_user(
        actor_id="user_local_admin",
        username="read-limited",
        display_name="Read Limited",
        email="",
        password="read-limited-password",
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client, "read-limited", "read-limited-password")
        summary = client.get("/api/admin/capabilities")
        bypass = client.get("/api/admin/users")
        denied = container.database.execute(
            "select * from audit_event where status = 'DENIED' order by created_at desc"
        )

    assert summary.status_code == 200
    assert summary.json()["capabilities"] == []
    assert summary.json()["data_scope"]["mode"] == "restricted"
    assert bypass.status_code == 403
    assert denied


def test_admin_validation_errors_have_stable_contract_and_correlation_id() -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        csrf = login(client)
        response = client.post(
            "/api/admin/users",
            headers={**csrf_headers(csrf), "x-correlation-id": "contract-test"},
            json={"username": "", "display_name": ""},
        )

    assert response.status_code == 422
    assert response.headers["x-correlation-id"] == "contract-test"
    detail = response.json()["detail"]
    assert detail["code"] == "validation_failed"
    assert detail["message"] == "请求参数校验失败"
    assert detail["correlation_id"] == "contract-test"
    assert [item["field"] for item in detail["field_errors"]] == [
        "username",
        "display_name",
    ]


def test_page_and_time_windows_are_bounded_and_stable() -> None:
    cursor = PageWindow.encode("2026-07-20T12:00:00+00:00|job-1")
    assert PageWindow.parse(limit=50, cursor=cursor).cursor == cursor
    assert PageWindow.decode(cursor).endswith("|job-1")
    with pytest.raises(NonRetryableExecutionError):
        PageWindow.parse(limit=101)
    with pytest.raises(NonRetryableExecutionError):
        PageWindow.parse(cursor="not-base64")

    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    default = TimeWindow.parse(now=now)
    assert default.end - default.start == timedelta(hours=24)
    with pytest.raises(NonRetryableExecutionError):
        TimeWindow.parse(
            start="2026-01-01T00:00:00Z",
            end="2026-07-20T00:00:00Z",
            now=now,
        )


class FakeQueueStatus:
    def collect(self) -> dict[str, object]:
        return {
            "availability": "unavailable",
            "collected_at": "2026-07-20T12:00:00+00:00",
            "error": {
                "code": "queue_status_unavailable",
                "message": "Queue status is temporarily unavailable",
            },
            "items": [],
        }


def test_dashboard_is_scope_filtered_and_queue_failure_is_region_local() -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    limited = container.identity_admin_service.create_user(
        actor_id="user_local_admin",
        username="dashboard-limited",
        display_name="Dashboard Limited",
        email="",
        password="dashboard-limited-password",
    )
    own_session = container.agent_repository.create_session(
        project_code="default",
        source_channel="dingding",
        source_connector_id="connector-dingtalk-enterprise-default",
        external_conversation_id="own-conversation",
        requester_id=str(limited["id"]),
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
        session_key="dashboard-own",
    )
    other_session = container.agent_repository.create_session(
        project_code="default",
        source_channel="dingding",
        source_connector_id="connector-dingtalk-enterprise-default",
        external_conversation_id="other-conversation",
        requester_id="someone-else",
        routing_context={"project_code": "default", "environment": "prod", "base": "longhua"},
        session_key="dashboard-other",
    )
    own_job = container.agent_repository.create_job(
        session_id=own_session.id,
        idempotency_key="dashboard-own-job",
        internal_user_id=str(limited["id"]),
        project_code="default",
        source_channel="dingding",
        source_connector_id="connector-dingtalk-enterprise-default",
        requester_id=str(limited["id"]),
        input_message="safe own message",
        max_retry_count=3,
        initial_status=JobStatus.FAILED,
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
        execution_policy=execution_policy_snapshot(),
    )
    container.agent_repository.create_job(
        session_id=other_session.id,
        idempotency_key="dashboard-other-job",
        internal_user_id="someone-else",
        project_code="default",
        source_channel="dingding",
        source_connector_id="connector-dingtalk-enterprise-default",
        requester_id="someone-else",
        input_message="must not leak",
        max_retry_count=3,
        initial_status=JobStatus.FAILED,
        routing_context={"project_code": "default", "environment": "prod", "base": "longhua"},
        execution_policy=execution_policy_snapshot(),
    )
    window = TimeWindow.parse()
    result = DashboardQueryService(
        AdminReadRepository(container.database), FakeQueueStatus()
    ).query(
        window=window,
        scope=AdminScope({"mode": "restricted", "grants": []}, str(limited["id"])),
    )

    assert result["summary"]["jobs"] == 1
    assert result["summary"]["users"] == 1
    assert result["jobs"]["failed"] == 1
    assert result["jobs"]["recent_exceptions"][0]["id"] == own_job.id
    assert result["queues"]["availability"] == "unavailable"
    assert "must not leak" not in str(result)


def test_dashboard_api_is_authorized_bounded_and_does_not_probe_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: container)
    monkeypatch.setattr(
        "app.modules.admin.api.controller.RabbitMQQueueStatusAdapter",
        lambda *_args, **_kwargs: FakeQueueStatus(),
    )

    with TestClient(app) as client:
        login(client)
        response = client.get("/api/admin/dashboard")
        invalid = client.get(
            "/api/admin/dashboard",
            params={
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-07-20T00:00:00Z",
            },
        )

    assert response.status_code == 200
    assert response.json()["window"]["start"]
    assert response.json()["generated_at"]
    assert response.json()["queues"]["availability"] == "unavailable"
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_time_window"


def test_agent_skill_and_channel_catalogs_support_editable_agents() -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.database.execute(
        """
        insert into agent_definition
          (id, code, name, description, project_code, status, revision,
           created_by, created_at, updated_at)
        values ('agent-secondary', 'secondary-agent', 'Secondary', '', 'default',
                'enabled', 1, 'user_local_admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client)
        agents = client.get("/api/admin/agents")
        skills = client.get("/api/admin/skills")
        channel_providers = client.get("/api/admin/channel-providers")
        connectors = client.get("/api/admin/connectors")

    assert agents.status_code == skills.status_code == 200
    assert all(agent["management_mode"] == "editable" for agent in agents.json()["agents"])
    assert all("content" not in item for item in skills.json()["skills"])
    email = next(item for item in channel_providers.json()["providers"] if item["code"] == "email")
    assert email["available"] is False
    assert all(
        item["connector_type"].startswith("dingtalk_") for item in connectors.json()["connectors"]
    )
    assert "connector-email-default" not in str(connectors.json())


def test_channel_validation_rejects_unavailable_direction_and_plaintext_secret() -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        csrf = login(client)
        unavailable = client.post(
            "/api/admin/connectors/validate",
            headers=csrf_headers(csrf),
            json={
                "expected_revision": 0,
                "connector_type": "email",
                "name": "mail",
                "allow_delivery": True,
            },
        )
        wrong_direction = client.post(
            "/api/admin/connectors/validate",
            headers=csrf_headers(csrf),
            json={
                "expected_revision": 0,
                "connector_type": "dingtalk_enterprise_stream",
                "name": "stream",
                "allow_delivery": True,
                "secret_ref": "secret://platform/dingtalk_client_secret",
                "metadata": {
                    "client_id_ref": "secret://platform/dingtalk_client_id",
                    "tenant_code": "default",
                },
            },
        )
        plaintext = client.post(
            "/api/admin/connectors/validate",
            headers=csrf_headers(csrf),
            json={
                "expected_revision": 0,
                "connector_type": "dingtalk_enterprise_stream",
                "name": "stream",
                "allow_ingress": True,
                "secret_ref": "actual-secret",
                "metadata": {
                    "client_id_ref": "secret://platform/dingtalk_client_id",
                    "tenant_code": "default",
                },
            },
        )
        legacy_env = client.post(
            "/api/admin/connectors/validate",
            headers=csrf_headers(csrf),
            json={
                "expected_revision": 0,
                "connector_type": "dingtalk_enterprise_stream",
                "name": "legacy-stream",
                "allow_ingress": True,
                "secret_ref": "env:DINGTALK_CLIENT_SECRET",
                "metadata": {
                    "client_id_ref": "env:DINGTALK_CLIENT_ID",
                    "tenant_code": "default",
                },
            },
        )

    assert (
        unavailable.status_code
        == wrong_direction.status_code
        == plaintext.status_code
        == legacy_env.status_code
        == 400
    )
    assert "actual-secret" not in plaintext.text


def test_operations_browser_is_bounded_read_only_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.database.execute(
        """
        insert into business_application
          (id, code, name, description, project_code, owner_user_id, status,
           revision, created_by, created_at, updated_at)
        values (?, ?, ?, '', 'default', 'user_local_admin', 'enabled',
                1, 'user_local_admin', ?, ?)
        """,
        (
            "application-ops",
            "operations-application",
            "生产运维助手",
            "2026-07-20T00:00:00+00:00",
            "2026-07-20T00:00:00+00:00",
        ),
    )
    session = container.agent_repository.create_session(
        project_code="default",
        source_channel="dingding",
        source_connector_id="connector-dingtalk-enterprise-default",
        external_conversation_id="ops-conversation",
        requester_id="user_local_admin",
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
        session_key="ops-session",
        business_application_id="application-ops",
        business_application_code="operations-application",
        application_publication_id="publication-ops",
        execution_scope_hash=_execution_scope_hash(
            {
                "project_code": "default",
                "environment": "prod",
                "base": "guanlan",
            }
        ),
        conversation_mode="channel",
        recent_message_limit=20,
        session_policy={"conversation_mode": "channel", "retention_days": 30},
    )
    job = container.agent_repository.create_job(
        session_id=session.id,
        idempotency_key="ops-job",
        internal_user_id="user_local_admin",
        project_code="default",
        source_channel="dingding",
        source_connector_id="connector-dingtalk-enterprise-default",
        requester_id="user_local_admin",
        input_message="diagnose",
        max_retry_count=3,
        initial_status=JobStatus.FAILED,
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
        business_application_id="application-ops",
        business_application_code="operations-application",
        business_application_publication_id="publication-ops",
        business_application_deployment_id="deployment-ops",
        business_application_route_id="route-ops",
        business_application_runtime_status="partially_wired",
        business_application_route_decision={
            "correlation_id": "correlation-ops",
            "resolution_outcome": "matched",
        },
        execution_policy=execution_policy_snapshot(),
        reply_route={
            "type": "dingtalk_private",
            "connector_id": "connector-ops",
            "target": {
                "webhook_url": "https://must-never-leak.example.test/hook",
                "conversation_id": "conversation-ops",
            },
        },
    )
    container.agent_repository.add_tool_call(
        job_id=job.id,
        tool_name="ones_work_item_search",
        request_payload={},
        response_summary={"total": 1, "truncated": False},
        status="SUCCEEDED",
        duration_ms=4,
        risk_level="low",
        invocation_id=f"{job.id}.attempt-0",
        tool_origin="mcp",
        server_code="ones-mcp",
        mcp_call_id="mcp-call-operations-projection",
        persisted_by="mcp_server",
    )
    delivery_id = container.result_delivery_service.enqueue_job_failure(
        job_id=job.id,
        reason="safe synthetic failure",
        error_code="synthetic_failure",
        correlation_id="correlation-ops",
    )
    assert job.input_message_id is not None
    message_id = job.input_message_id
    attachment = container.agent_repository.add_attachment(
        message_id=message_id,
        job_id=job.id,
        ordinal=0,
        media_type="file",
        file_name="report.docx",
        declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        credential_ciphertext="must-never-leak",
    )
    container.database.execute(
        "update message_attachment set object_bucket='private', object_key='tenant/private/report.docx' where id=?",
        (attachment.id,),
    )
    before_queue = len(container.message_bus.attachments) if container.message_bus else 0
    app = create_app(settings, container_factory=lambda _: container)
    monkeypatch.setattr(
        "app.modules.admin.api.controller.RabbitMQQueueStatusAdapter",
        lambda *_args, **_kwargs: FakeQueueStatus(),
    )

    with TestClient(app) as client:
        login(client)
        queue_response = client.get("/api/admin/queues")
        jobs = client.get("/api/admin/jobs")
        jobs_by_names = client.get(
            "/api/admin/jobs",
            params={
                "username": "ministra",
                "application_name": "运维助手",
            },
        )
        jobs_by_unknown_name = client.get(
            "/api/admin/jobs",
            params={"username": "missing-user"},
        )
        summary = client.get("/api/admin/jobs/summary")
        delivery_metrics = client.get("/api/admin/deliveries/metrics")
        detail = client.get(f"/api/admin/jobs/{job.id}")
        conversations = client.get("/api/admin/conversations")
        conversation = client.get(f"/api/admin/conversations/{session.id}")
        attachments = client.get("/api/admin/attachments")
        attachment_detail = client.get(f"/api/admin/attachments/{attachment.id}")
        routes = client.get("/openapi.json").json()["paths"]

    assert queue_response.status_code == 200
    assert (
        jobs.status_code
        == summary.status_code
        == delivery_metrics.status_code
        == detail.status_code
        == jobs_by_names.status_code
        == jobs_by_unknown_name.status_code
        == 200
    )
    assert conversations.status_code == conversation.status_code == 200
    assert attachments.status_code == attachment_detail.status_code == 200
    assert jobs.json()["page"]["limit"] == 25
    assert jobs.json()["items"][0]["business_application_code"] == "operations-application"
    assert jobs.json()["items"][0]["business_application_name"] == "生产运维助手"
    assert jobs.json()["items"][0]["user_username"] == "admin"
    assert jobs.json()["items"][0]["user_display_name"] == "Administrator"
    assert jobs.json()["items"][0]["business_application_publication_id"] == "publication-ops"
    assert jobs.json()["items"][0]["correlation_id"] == "correlation-ops"
    assert detail.json()["job"]["business_application_deployment_id"] == "deployment-ops"
    assert detail.json()["job"]["tool_call_count"] == 1
    assert jobs.json()["items"][0]["tool_call_count"] == 1
    assert [item["id"] for item in jobs_by_names.json()["items"]] == [job.id]
    assert jobs_by_unknown_name.json()["items"] == []
    delivery = detail.json()["deliveries"]
    assert delivery["events"][0]["id"] == delivery_id
    assert delivery["events"][0]["status"] == "PENDING"
    assert delivery["events"][0]["delivered"] is False
    assert delivery["attempts"] == delivery["chunks"] == []
    assert delivery_metrics.json()["delivery"]["counts"]["PENDING"] == 1
    assert delivery_metrics.json()["delivery"]["active_count"] == 1
    assert conversations.json()["page"]["limit"] == 25
    assert conversation.json()["session"]["business_application_code"] == "operations-application"
    assert conversation.json()["session"]["conversation_mode"] == "channel"
    assert "request_payload" not in str(detail.json())
    serialized_delivery = str(delivery)
    assert "delivery_binding_json" not in serialized_delivery
    assert "route_hash" not in serialized_delivery
    assert "https://must-never-leak.example.test/hook" not in serialized_delivery
    serialized_attachment = str(attachment_detail.json())
    assert "must-never-leak" not in serialized_attachment
    assert "tenant/private/report.docx" not in serialized_attachment
    assert attachment_detail.json()["attachment"]["storage_configured"] is True
    assert routes["/api/admin/queues"].keys() == {"get"}
    assert not any(word in path for path in routes for word in ("purge", "replay"))
    assert (len(container.message_bus.attachments) if container.message_bus else 0) == before_queue
