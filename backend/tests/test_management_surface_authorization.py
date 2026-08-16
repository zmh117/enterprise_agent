from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings, Settings
from backend.tests.helpers import test_settings as make_test_settings
from backend.tests.test_unified_identity_rbac import csrf_headers, login


ADMIN_ID = "user_local_admin"


def _settings(*, test_headers: bool = False) -> Settings:
    base = make_test_settings()
    return replace(
        base,
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=False,
            test_identity_headers_enabled=test_headers,
            cookie_secure=False,
            allowed_origins=("http://admin.test",),
        ),
    )


def _container(settings: Settings) -> Container:
    return build_test_container(settings, migrate=True, seed=True)


def _grant_capabilities(
    runtime: Container,
    *,
    username: str,
    capability_codes: tuple[str, ...],
) -> None:
    user = runtime.identity_repository.create_user(
        username=username,
        display_name=username,
    )
    role = runtime.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code=f"{username}-role",
        name=f"{username} role",
        description="management surface contract",
        purpose_tags=["contract-test"],
    )["role"]
    runtime.authorization_center_service.replace_admin_capabilities(
        actor_id=ADMIN_ID,
        role_id=str(role["id"]),
        expected_revision=int(role["revision"]),
        bindings=[
            {"capability_code": capability_code, "resource_code": "*"}
            for capability_code in capability_codes
        ],
        confirmed=True,
        reason="management surface contract",
    )
    runtime.identity_repository.assign_role(
        user_id=str(user["id"]),
        role_id=str(role["id"]),
        assigned_by=ADMIN_ID,
    )


def test_management_surface_distinguishes_unauthenticated_forged_and_authorized() -> None:
    settings = _settings(test_headers=False)
    runtime = _container(settings)

    with TestClient(create_app(settings, container_factory=lambda _: runtime)) as client:
        for path in (
            "/api/platform/environments",
            "/api/agent/workflows",
            "/api/agent/jobs/_debug-options",
        ):
            assert client.get(path).status_code == 401
            assert (
                client.get(path, headers={"x-admin-user-id": ADMIN_ID}).status_code
                == 401
            )

        csrf = login(client)
        headers = csrf_headers(csrf)
        assert client.get("/api/platform/environments", headers=headers).status_code == 200
        assert client.get("/api/agent/workflows", headers=headers).status_code == 200
        assert client.get("/api/agent/jobs/_debug-options", headers=headers).status_code == 200


def test_authenticated_user_without_management_actions_gets_403() -> None:
    settings = _settings(test_headers=True)
    runtime = _container(settings)
    runtime.identity_repository.create_user(
        username="management-no-capabilities",
        display_name="management-no-capabilities",
    )
    headers = {"x-admin-user-id": "management-no-capabilities"}

    with TestClient(create_app(settings, container_factory=lambda _: runtime)) as client:
        assert client.get("/api/platform/environments", headers=headers).status_code == 403
        assert client.get("/api/platform/secrets", headers=headers).status_code == 403
        assert client.get("/api/agent/workflows", headers=headers).status_code == 403
        assert client.get("/api/agent/jobs/_debug-options", headers=headers).status_code == 403


def test_workflow_read_edit_publish_actions_are_independent() -> None:
    settings = _settings(test_headers=True)
    runtime = _container(settings)
    _grant_capabilities(
        runtime,
        username="workflow-reader",
        capability_codes=("agents.read",),
    )
    _grant_capabilities(
        runtime,
        username="workflow-editor",
        capability_codes=("agents.read", "agents.edit"),
    )
    _grant_capabilities(
        runtime,
        username="workflow-publisher",
        capability_codes=("agents.read", "agents.publish"),
    )

    with TestClient(create_app(settings, container_factory=lambda _: runtime)) as client:
        admin_headers = {"x-admin-user-id": "admin"}
        created = client.post(
            "/api/agent/workflows",
            headers=admin_headers,
            json={"code": "contract-flow", "name": "Contract flow"},
        )
        assert created.status_code == 200, created.text

        reader_headers = {"x-admin-user-id": "workflow-reader"}
        assert client.get("/api/agent/workflows", headers=reader_headers).status_code == 200
        assert (
            client.post(
                "/api/agent/workflows",
                headers=reader_headers,
                json={"code": "reader-write", "name": "denied"},
            ).status_code
            == 403
        )

        editor_headers = {"x-admin-user-id": "workflow-editor"}
        edited = client.post(
            "/api/agent/workflows",
            headers=editor_headers,
            json={"code": "editor-flow", "name": "Editor flow"},
        )
        assert edited.status_code == 200, edited.text
        assert (
            client.post(
                "/api/agent/workflows/contract-flow/publish",
                headers=editor_headers,
            ).status_code
            == 403
        )

        published = client.post(
            "/api/agent/workflows/contract-flow/publish",
            headers={"x-admin-user-id": "workflow-publisher"},
        )
        assert published.status_code == 200, published.text


def test_platform_and_secret_actions_are_independent() -> None:
    settings = _settings(test_headers=True)
    runtime = _container(settings)
    _grant_capabilities(
        runtime,
        username="platform-reader",
        capability_codes=("platform.read",),
    )
    _grant_capabilities(
        runtime,
        username="secret-manager",
        capability_codes=("secrets.read", "secrets.manage"),
    )
    _grant_capabilities(
        runtime,
        username="secret-rotator",
        capability_codes=("secrets.read", "secrets.rotate"),
    )

    with TestClient(create_app(settings, container_factory=lambda _: runtime)) as client:
        reader = {"x-admin-user-id": "platform-reader"}
        assert client.get("/api/platform/environments", headers=reader).status_code == 200
        assert (
            client.post(
                "/api/platform/environments",
                headers=reader,
                json={"code": "reader-write-denied"},
            ).status_code
            == 403
        )

        manager = {"x-admin-user-id": "secret-manager"}
        created = client.post(
            "/api/platform/secrets",
            headers=manager,
            json={"code": "action-matrix-secret", "value": "contract-value"},
        )
        assert created.status_code == 200, created.text
        assert (
            client.post(
                "/api/platform/secrets/action-matrix-secret/rotate",
                headers=manager,
                json={"value": "manager-must-not-rotate"},
            ).status_code
            == 403
        )

        rotated = client.post(
            "/api/platform/secrets/action-matrix-secret/rotate",
            headers={"x-admin-user-id": "secret-rotator"},
            json={"value": "rotator-may-rotate"},
        )
        assert rotated.status_code == 200, rotated.text
