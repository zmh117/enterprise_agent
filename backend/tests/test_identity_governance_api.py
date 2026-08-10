from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings
from backend.tests.helpers import test_settings as build_test_settings


ADMIN = {"x-admin-user-id": "user_local_admin", "Idempotency-Key": "test-request"}


def _runtime():
    settings = replace(
        build_test_settings(),
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )
    return settings, build_test_container(settings, migrate=True, seed=True)


def test_user_directory_create_update_and_detail_are_safe() -> None:
    settings, container = _runtime()
    try:
        with TestClient(create_app(settings, container_factory=lambda _: container)) as client:
            created = client.post(
                "/api/admin/users",
                headers=ADMIN,
                json={
                    "username": "governance-user",
                    "display_name": "治理用户",
                    "email": "governance@example.test",
                    "password": "test-password-change-me",
                },
            )
            assert created.status_code == 200, created.text
            user = created.json()["user"]
            assert set(user).isdisjoint({"password", "password_hash", "session_token"})

            listed = client.get("/api/admin/users?search=governance", headers=ADMIN)
            detail = client.get(f"/api/admin/users/{user['id']}", headers=ADMIN)
            assert listed.status_code == detail.status_code == 200
            assert [item["id"] for item in listed.json()["users"]] == [user["id"]]
            assert set(detail.json()).issuperset(
                {"user", "roles", "sessions", "external_identities"}
            )
            assert "token_hash" not in detail.text
            assert "csrf_hash" not in detail.text
            assert "password_hash" not in detail.text

            updated = client.put(
                f"/api/admin/users/{user['id']}",
                headers={**ADMIN, "Idempotency-Key": "update-user"},
                json={
                    "expected_revision": user["revision"],
                    "display_name": "治理用户二号",
                    "email": "governance@example.test",
                    "status": "disabled",
                },
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["user"]["status"] == "disabled"
    finally:
        container.database.close()


def test_role_governance_uses_code_owned_capabilities_and_application_only_access() -> None:
    settings, container = _runtime()
    try:
        with TestClient(create_app(settings, container_factory=lambda _: container)) as client:
            created = client.post(
                "/api/admin/authorization/roles",
                headers={**ADMIN, "Idempotency-Key": "create-role"},
                json={
                    "code": "mcp-viewer",
                    "name": "MCP Viewer",
                    "description": "",
                    "purpose_tags": ["mcp"],
                },
            )
            assert created.status_code == 200, created.text
            detail = created.json()
            role = detail["role"]

            replaced = client.put(
                f"/api/admin/authorization/roles/{role['id']}/admin-capabilities",
                headers={**ADMIN, "Idempotency-Key": "role-capabilities"},
                json={
                    "expected_revision": detail["admin"]["revision"],
                    "capability_codes": ["mcp_tools.manage"],
                },
            )
            assert replaced.status_code == 200, replaced.text
            assert {
                item["capability_code"] for item in replaced.json()["bindings"]
            } == {"mcp_tools.read", "mcp_tools.manage"}

            retired_payload = client.put(
                f"/api/admin/authorization/roles/{role['id']}/business-access",
                headers={**ADMIN, "Idempotency-Key": "retired-business-payload"},
                json={
                    "expected_revision": detail["business"]["revision"],
                    "application_ids": [],
                    "capability_codes": ["retired"],
                },
            )
            assert retired_payload.status_code == 422

            catalog = client.get("/api/admin/authorization/capabilities", headers=ADMIN)
            assert catalog.status_code == 200
            serialized = catalog.text.lower()
            assert "api_capability" not in serialized
            assert "api_connection" not in serialized
            assert "resource_mapping" not in serialized
    finally:
        container.database.close()


def test_unprivileged_user_cannot_enumerate_governance_directory() -> None:
    settings, container = _runtime()
    user = container.identity_repository.create_user(
        username="no-admin-access",
        display_name="No Admin",
    )
    try:
        with TestClient(create_app(settings, container_factory=lambda _: container)) as client:
            response = client.get(
                "/api/admin/users",
                headers={"x-admin-user-id": str(user["id"])},
            )
            assert response.status_code == 403
    finally:
        container.database.close()
