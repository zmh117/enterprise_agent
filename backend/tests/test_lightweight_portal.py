from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings, Settings


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


def _job(container: object, user_id: str, suffix: str) -> tuple[str, str]:
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
        user_message=f"message-{suffix}",
        max_retry_count=0,
        reply_route={"type": "none"},
        execution_policy={
            "schema_version": 1,
            "requested": {"max_turns": 5, "timeout_seconds": 60, "max_tool_calls": 5},
            "effective": {"max_turns": 5, "timeout_seconds": 60, "max_tool_calls": 5},
            "sources": {"source_kind": "runtime_default"},
        },
    )
    return job.id, session.id


def test_portal_history_requires_authentication_and_isolates_every_object() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    owner = container.identity_repository.get_user_by_username("local-user")
    foreign = container.identity_repository.create_user(
        username="foreign-user",
        display_name="Foreign User",
    )
    own_job, own_session = _job(container, str(owner["id"]), "own")
    foreign_job, foreign_session = _job(container, str(foreign["id"]), "foreign")
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        assert client.get("/api/me/jobs").status_code == 401

        headers = {"x-admin-user-id": "local-user"}
        listing = client.get("/api/me/jobs", headers=headers)
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["items"]] == [own_job]

        own = client.get(f"/api/me/jobs/{own_job}/evidence", headers=headers)
        assert own.status_code == 200
        assert own.json()["session_ref"] == {"id": own_session}
        assert "mcp_tool_calls" in own.json()

        foreign_response = client.get(f"/api/me/jobs/{foreign_job}/evidence", headers=headers)
        unknown_response = client.get("/api/me/jobs/job-does-not-exist/evidence", headers=headers)
        assert foreign_response.status_code == unknown_response.status_code == 404
        assert foreign_response.json() == unknown_response.json()
        assert (
            client.get(f"/api/me/conversations/{foreign_session}", headers=headers).status_code
            == 404
        )


def test_lightweight_portal_login_survives_retired_web_admin_feature() -> None:
    settings = _settings()
    settings = replace(
        settings,
        identity=replace(settings.identity, web_admin_enabled=False),
    )
    container = build_test_container(settings, migrate=True, seed=False)
    container.auth_service.bootstrap_admin(
        username="portal-user",
        display_name="Portal User",
        password="portal-password-123",
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "portal-user", "password": "portal-password-123"},
        )

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "portal-user"


def test_retired_backend_management_routes_cannot_be_reenabled() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: container)
    headers = {"x-admin-user-id": "local-user"}

    with TestClient(app) as client:
        for method, path in (
            ("get", "/api/admin/api-capabilities"),
            ("get", "/api/platform/runtime-config/values"),
            ("get", "/api/platform/builtin-tools"),
            ("post", "/api/agent/jobs"),
        ):
            assert getattr(client, method)(path, headers=headers).status_code == 404


def test_platformctl_resource_api_requires_explicit_admin_permission() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.identity_repository.create_user(
        username="ordinary-user",
        display_name="Ordinary User",
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        assert client.get("/api/admin/mcp/resources").status_code == 401
        assert (
            client.get(
                "/api/admin/mcp/resources",
                headers={"x-admin-user-id": "ordinary-user"},
            ).status_code
            == 403
        )
        allowed = client.get(
            "/api/admin/mcp/resources",
            headers={"x-admin-user-id": "local-user"},
        )
        assert allowed.status_code == 200
        assert allowed.json() == {"resources": []}
