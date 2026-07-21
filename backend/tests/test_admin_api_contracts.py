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
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_unified_identity_rbac import csrf_headers, login, unified_settings


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
    assert body["data_scope"] == {"mode": "global", "grants": []}
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
    assert detail["message"] == "Request validation failed"
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
        dingding_conversation_id="own-conversation",
        dingding_user_id=str(limited["id"]),
        source="dingding",
        project_code="default",
        requester_id=str(limited["id"]),
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
        session_key="dashboard-own",
    )
    other_session = container.agent_repository.create_session(
        dingding_conversation_id="other-conversation",
        dingding_user_id="someone-else",
        source="dingding",
        project_code="default",
        requester_id="someone-else",
        routing_context={"project_code": "default", "environment": "prod", "base": "longhua"},
        session_key="dashboard-other",
    )
    own_job = container.agent_repository.create_job(
        session_id=own_session.id,
        idempotency_key="dashboard-own-job",
        user_id=str(limited["id"]),
        internal_user_id=str(limited["id"]),
        project_code="default",
        source="dingding",
        user_message="safe own message",
        max_retry_count=3,
        initial_status=JobStatus.FAILED,
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
    )
    container.agent_repository.create_job(
        session_id=other_session.id,
        idempotency_key="dashboard-other-job",
        user_id="someone-else",
        internal_user_id="someone-else",
        project_code="default",
        source="dingding",
        user_message="must not leak",
        max_retry_count=3,
        initial_status=JobStatus.FAILED,
        routing_context={"project_code": "default", "environment": "prod", "base": "longhua"},
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


def test_agent_skill_tool_and_channel_catalogs_enforce_mvp_availability() -> None:
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
    with pytest.raises(NonRetryableExecutionError) as read_only:
        container.agent_config_service.save_draft(
            actor_id="user_local_admin",
            agent_code="secondary-agent",
            expected_revision=0,
            config={},
        )
    assert read_only.value.error_code == "agent_read_only"
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client)
        agents = client.get("/api/admin/agents")
        skills = client.get("/api/admin/skills")
        tool_providers = client.get("/api/admin/tool-providers")
        channel_providers = client.get("/api/admin/channel-providers")
        connectors = client.get("/api/admin/connectors")

    assert agents.status_code == skills.status_code == 200
    assert agents.json()["agents"][0]["management_mode"] == "editable"
    assert all("content" not in item for item in skills.json()["skills"])
    database = next(
        item for item in tool_providers.json()["providers"] if item["code"] == "database"
    )
    assert database["dialects"] == ["postgresql", "mysql", "sqlserver"]
    assert "oracle" not in str(tool_providers.json()).lower()
    email = next(item for item in channel_providers.json()["providers"] if item["code"] == "email")
    assert email["available"] is False
    assert all(
        item["connector_type"].startswith("dingtalk_") for item in connectors.json()["connectors"]
    )
    assert "connector-email-default" not in str(connectors.json())


def test_tool_resource_contract_rejects_plaintext_and_enforces_revision() -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.platform_config_service.upsert_environment(
        {"code": "prod", "display_name": "Production", "status": "enabled"},
        actor_id="user_local_admin",
    )
    app = create_app(settings, container_factory=lambda _: container)
    payload = {
        "expected_revision": 0,
        "code": "prod_loki",
        "scope_type": "environment",
        "environment_code": "prod",
        "resource_kind": "loki",
        "engine": "",
        "config": {
            "base_url": "https://loki.internal",
            "host_allowlist": ["loki.internal"],
        },
        "secret_refs": {"token": "secret://platform/loki_token"},
        "status": "enabled",
    }

    with TestClient(app) as client:
        csrf = login(client)
        created = client.post("/api/admin/tool-resources", headers=csrf_headers(csrf), json=payload)
        updated_payload = {**payload, "expected_revision": 1, "status": "disabled"}
        updated = client.put(
            "/api/admin/tool-resources/prod_loki",
            headers=csrf_headers(csrf),
            json=updated_payload,
        )
        stale = client.put(
            "/api/admin/tool-resources/prod_loki",
            headers=csrf_headers(csrf),
            json=updated_payload,
        )
        plaintext = client.post(
            "/api/admin/tool-resources",
            headers=csrf_headers(csrf),
            json={
                **payload,
                "code": "bad_loki",
                "config": {**payload["config"], "token": "plain-secret"},
            },
        )

    assert created.status_code == 200, created.text
    assert created.json()["resource"]["revision"] == 1
    assert updated.status_code == 200
    assert updated.json()["resource"]["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    assert plaintext.status_code == 400
    assert "plain-secret" not in plaintext.text


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
                "secret_ref": "env:DINGTALK_CLIENT_SECRET",
                "metadata": {"client_id_ref": "env:DINGTALK_CLIENT_ID", "tenant_code": "default"},
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
                "metadata": {"client_id_ref": "env:DINGTALK_CLIENT_ID", "tenant_code": "default"},
            },
        )

    assert unavailable.status_code == wrong_direction.status_code == plaintext.status_code == 400
    assert "actual-secret" not in plaintext.text


def test_operations_browser_is_bounded_read_only_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = unified_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    session = container.agent_repository.create_session(
        dingding_conversation_id="ops-conversation",
        dingding_user_id="user_local_admin",
        source="dingding",
        project_code="default",
        requester_id="user_local_admin",
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
        session_key="ops-session",
    )
    job = container.agent_repository.create_job(
        session_id=session.id,
        idempotency_key="ops-job",
        user_id="user_local_admin",
        internal_user_id="user_local_admin",
        project_code="default",
        source="dingding",
        user_message="diagnose",
        max_retry_count=3,
        initial_status=JobStatus.FAILED,
        routing_context={"project_code": "default", "environment": "prod", "base": "guanlan"},
    )
    message_id = container.agent_repository.add_message(
        session_id=session.id,
        job_id=job.id,
        role="user",
        content="attachment question",
    )
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
        summary = client.get("/api/admin/jobs/summary")
        detail = client.get(f"/api/admin/jobs/{job.id}")
        conversations = client.get("/api/admin/conversations")
        conversation = client.get(f"/api/admin/conversations/{session.id}")
        attachments = client.get("/api/admin/attachments")
        attachment_detail = client.get(f"/api/admin/attachments/{attachment.id}")
        routes = client.get("/openapi.json").json()["paths"]

    assert queue_response.status_code == 200
    assert jobs.status_code == summary.status_code == detail.status_code == 200
    assert conversations.status_code == conversation.status_code == 200
    assert attachments.status_code == attachment_detail.status_code == 200
    assert jobs.json()["page"]["limit"] == 25
    assert conversations.json()["page"]["limit"] == 25
    assert "request_payload" not in str(detail.json())
    serialized_attachment = str(attachment_detail.json())
    assert "must-never-leak" not in serialized_attachment
    assert "tenant/private/report.docx" not in serialized_attachment
    assert attachment_detail.json()["attachment"]["storage_configured"] is True
    assert routes["/api/admin/queues"].keys() == {"get"}
    assert not any(word in path for path in routes for word in ("purge", "replay"))
    assert (len(container.message_bus.attachments) if container.message_bus else 0) == before_queue
