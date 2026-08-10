from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings
from backend.tests.helpers import test_settings as build_test_settings


def test_mcp_server_registry_is_code_owned_read_only_and_independently_authorized() -> None:
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
    container = build_test_container(settings, migrate=True, seed=True)
    user = container.identity_repository.create_user(
        username="mcp-server-reader",
        display_name="MCP Server Reader",
    )
    role = container.identity_repository.create_role(code="mcp-server-reader", name="Reader")
    container.identity_repository.assign_role(user_id=str(user["id"]), role_id=str(role["id"]))
    container.authorization_center_repository.replace_admin_bindings(
        str(role["id"]),
        expected_revision=1,
        bindings=[
            {
                "capability_code": "mcp_servers.read",
                "resource_type": "mcp_server",
                "resource_code": "*",
            }
        ],
    )
    headers = {"x-admin-user-id": str(user["id"])}
    try:
        with TestClient(create_app(settings, container_factory=lambda _: container)) as client:
            response = client.get("/api/admin/mcp/status", headers=headers)
            assert response.status_code == 200, response.text
            assert [item["server_code"] for item in response.json()["servers"]] == [
                "ones-mcp",
                "data-mcp",
            ]
            assert all(
                item["source"] == "deployment_config"
                and item["transport"] == {
                    "type": "streamable_http",
                    "authentication": "runtime_bearer",
                }
                for item in response.json()["servers"]
            )
            assert "url" not in response.text.lower()
            assert "authorization" not in response.text.lower()
            assert client.post("/api/admin/mcp/status", headers=headers, json={}).status_code == 405
            assert client.get("/api/admin/mcp/status/unknown", headers=headers).status_code == 404
    finally:
        container.database.close()
