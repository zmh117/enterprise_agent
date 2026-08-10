from __future__ import annotations

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings, Settings
from backend.tests.test_agent_application_management import _application_payload


def _settings() -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="test-only-master-key",
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )


def _job(container: object, user_id: str, suffix: str) -> str:
    repository = container.agent_repository
    session = repository.create_session(
        dingding_conversation_id=f"conversation-{suffix}",
        dingding_user_id=user_id,
        source="test",
        project_code="default",
        requester_id=user_id,
        session_key=f"test:{suffix}",
        reply_route={"type": "none"},
    )
    job = repository.create_job(
        session_id=session.id,
        idempotency_key=f"job-{suffix}",
        user_id=user_id,
        requester_id=user_id,
        internal_user_id=user_id,
        project_code="default",
        source="test",
        user_message=f"sensitive-message-{suffix}",
        max_retry_count=0,
        reply_route={"type": "none"},
        execution_policy={
            "schema_version": 1,
            "requested": {
                "max_turns": 5,
                "timeout_seconds": 60,
                "max_tool_calls": 5,
            },
            "effective": {
                "max_turns": 5,
                "timeout_seconds": 60,
                "max_tool_calls": 5,
            },
            "sources": {"source_kind": "runtime_default"},
        },
    )
    return job.id


def _grant_job_reader(container: object, username: str) -> tuple[str, str]:
    user = container.identity_repository.create_user(
        username=username,
        display_name=username,
    )
    role = container.authorization_center_repository.create_role(
        code=f"{username}-role",
        name=f"{username} role",
        description="Scoped job reader",
        purpose_tags=[],
    )
    container.authorization_center_repository.replace_admin_bindings(
        str(role["id"]),
        expected_revision=1,
        bindings=[
            {
                "capability_code": "jobs.read",
                "resource_type": "agent_job",
                "resource_code": "*",
            }
        ],
    )
    container.identity_repository.assign_role(
        user_id=str(user["id"]),
        role_id=str(role["id"]),
    )
    return str(user["id"]), username


def _active_debug_application(container: object, user_id: str) -> None:
    created = container.business_application_service.create(
        actor_id=user_id,
        code="debug-application",
        name="Debug Application",
        description="Governed debug application",
        project_code="default",
        owner_user_id=user_id,
        idempotency_key="debug-application-create",
    )
    revision = container.business_application_service.save_draft(
        actor_id=user_id,
        code="debug-application",
        expected_revision=int(created["revision"]),
        payload=_application_payload([], routing_key="bot:debug-application"),
        idempotency_key="debug-application-draft",
    )
    publication = container.business_application_service.publish(
        actor_id=user_id,
        code="debug-application",
        revision_id=str(revision["id"]),
        expected_revision=int(created["revision"]) + 1,
        idempotency_key="debug-application-publish",
    )
    container.business_application_service.activate(
        actor_id=user_id,
        code="debug-application",
        environment="test",
        publication_id=str(publication["id"]),
        expected_revision=0,
        idempotency_key="debug-application-activate",
    )
    role = container.authorization_center_repository.create_role(
        code="debug-application-user",
        name="Debug Application User",
        description="Application use permission",
        purpose_tags=[],
    )
    container.authorization_center_repository.replace_business_access(
        str(role["id"]),
        expected_revision=1,
        applications=[{"application_id": str(created["id"])}],
    )
    container.identity_repository.assign_role(
        user_id=user_id,
        role_id=str(role["id"]),
    )


def test_admin_job_history_is_scoped_and_uses_safe_projection() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    scoped_user_id, scoped_username = _grant_job_reader(container, "job-reader")
    admin = container.identity_repository.get_user_by_username("local-user")
    own_job = _job(container, scoped_user_id, "scoped-own")
    foreign_job = _job(container, str(admin["id"]), "scoped-foreign")
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        headers = {"x-admin-user-id": scoped_username}
        listing = client.get("/api/admin/jobs", headers=headers)
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["items"]] == [own_job]
        assert "user_message" not in listing.text
        assert "idempotency_key" not in listing.text
        assert "result" not in listing.json()["items"][0]

        own = client.get(f"/api/admin/jobs/{own_job}/evidence", headers=headers)
        foreign = client.get(f"/api/admin/jobs/{foreign_job}/evidence", headers=headers)
        unknown = client.get("/api/admin/jobs/job-unknown/evidence", headers=headers)
        assert own.status_code == 200
        assert foreign.status_code == unknown.status_code == 404
        assert foreign.json() == unknown.json()


def test_job_cancel_is_expected_status_guarded_and_idempotent() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    admin = container.identity_repository.get_user_by_username("local-user")
    job_id = _job(container, str(admin["id"]), "cancel")
    app = create_app(settings, container_factory=lambda _: container)
    headers = {
        "x-admin-user-id": "local-user",
        "Idempotency-Key": "cancel-job-once",
    }

    with TestClient(app) as client:
        first = client.post(
            f"/api/admin/jobs/{job_id}/cancel",
            headers=headers,
            json={"expected_status": "PENDING"},
        )
        replay = client.post(
            f"/api/admin/jobs/{job_id}/cancel",
            headers=headers,
            json={"expected_status": "PENDING"},
        )
        conflict = client.post(
            f"/api/admin/jobs/{job_id}/cancel",
            headers={**headers, "Idempotency-Key": "cancel-after-state-change"},
            json={"expected_status": "PENDING"},
        )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["job"]["status"] == "CANCELLED"
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "job_status_conflict"


def test_debug_request_rejects_runtime_authority_overrides() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        response = client.post(
            "/api/admin/debug/jobs",
            headers={
                "x-admin-user-id": "local-user",
                "Idempotency-Key": "debug-overrides",
            },
            json={
                "application_code": "application-one",
                "environment": "test",
                "message": "diagnose",
                "actor_id": "another-user",
                "mcp_server_url": "https://untrusted.example",
                "tool_allowlist": ["arbitrary-tool"],
                "resource_deployment_id": "resource-any",
                "reply_route": {"type": "webhook", "url": "https://untrusted.example"},
            },
        )

    assert response.status_code == 422
    fields = {
        item["field"] for item in response.json()["detail"]["field_errors"]
    }
    assert {
        "actor_id",
        "mcp_server_url",
        "tool_allowlist",
        "resource_deployment_id",
        "reply_route",
    }.issubset(fields)


def test_debug_job_uses_active_publication_and_application_access() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    admin = container.identity_repository.get_user_by_username("local-user")
    _active_debug_application(container, str(admin["id"]))
    app = create_app(settings, container_factory=lambda _: container)
    headers = {
        "x-admin-user-id": "local-user",
        "Idempotency-Key": "debug-job-create",
    }

    with TestClient(app) as client:
        catalog = client.get("/api/admin/debug/applications", headers=headers)
        created = client.post(
            "/api/admin/debug/jobs",
            headers=headers,
            json={
                "application_code": "debug-application",
                "environment": "test",
                "message": "inspect current runtime",
            },
        )
        replay = client.post(
            "/api/admin/debug/jobs",
            headers=headers,
            json={
                "application_code": "debug-application",
                "environment": "test",
                "message": "inspect current runtime",
            },
        )

    assert catalog.status_code == 200
    assert [(item["code"], item["environment"]) for item in catalog.json()["items"]] == [
        ("debug-application", "test")
    ]
    assert created.status_code == replay.status_code == 201
    assert created.json() == replay.json()
    job = created.json()["job"]
    assert job["source_channel"] == "debug_api"
    assert job["business_application_code"] == "debug-application"
    assert job["business_application_publication_id"]
    assert job["agent_publication_id"] == "agent_publication_default_v1"
    assert "inspect current runtime" not in created.text
