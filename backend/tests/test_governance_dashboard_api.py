from __future__ import annotations

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


def test_dashboard_only_returns_modules_visible_to_current_principal() -> None:
    settings = _settings()
    container = build_test_container(settings, migrate=True, seed=True)
    viewer = container.identity_repository.create_user(
        username="dashboard-viewer", display_name="Dashboard Viewer"
    )
    role = container.authorization_center_repository.create_role(
        code="dashboard-only",
        name="Dashboard only",
        description="No module enumeration",
        purpose_tags=[],
    )
    container.authorization_center_repository.replace_admin_bindings(
        str(role["id"]),
        expected_revision=1,
        bindings=[
            {
                "capability_code": "dashboard.read",
                "resource_type": "dashboard",
                "resource_code": "*",
            }
        ],
    )
    container.identity_repository.assign_role(
        user_id=str(viewer["id"]), role_id=str(role["id"])
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        viewer_response = client.get(
            "/api/admin/dashboard",
            headers={"x-admin-user-id": "dashboard-viewer"},
        )
        admin_response = client.get(
            "/api/admin/dashboard",
            headers={"x-admin-user-id": "local-user"},
        )

    assert viewer_response.status_code == admin_response.status_code == 200
    assert viewer_response.json()["modules"] == []
    admin_codes = {item["code"] for item in admin_response.json()["modules"]}
    assert {
        "agents",
        "applications",
        "channels",
        "users",
        "identity_candidates",
        "jobs",
        "mcp_servers",
        "mcp_tools",
        "mcp_resources",
        "credentials",
    } <= admin_codes
    assert "api_capabilities" not in admin_codes
    assert "resource_mappings" not in admin_codes
