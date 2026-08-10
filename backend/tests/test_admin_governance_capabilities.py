from __future__ import annotations

from app.modules.admin.domain import ADMIN_CAPABILITIES
from backend.tests.helpers import container


def test_catalog_covers_governance_console_and_excludes_retired_api_platform() -> None:
    codes = {item.code for item in ADMIN_CAPABILITIES}
    assert {
        "dashboard.read",
        "users.read",
        "users.manage",
        "user_sessions.revoke",
        "roles.read",
        "roles.manage",
        "roles.simulate",
        "identities.read",
        "identities.manage",
        "channels.read",
        "channels.manage",
        "channels.test",
        "jobs.read",
        "jobs.debug",
        "jobs.cancel",
        "mcp_servers.read",
        "mcp_servers.check",
        "mcp_tools.read",
        "mcp_tools.manage",
        "mcp_resources.read",
        "mcp_resources.manage",
        "secrets.read",
        "secrets.manage",
    }.issubset(codes)
    assert not any(
        retired in item.code
        for item in ADMIN_CAPABILITIES
        for retired in ("api_capability", "api_handler", "api_connection", "resource_mapping")
    )


def test_platform_admin_gets_console_capabilities_and_other_role_defaults_to_deny() -> None:
    c = container()
    admin = c.identity_repository.get_user_by_username("local-user")
    assert admin is not None
    for resource_type, action in (
        ("dashboard", "read"),
        ("user", "manage"),
        ("role", "manage"),
        ("identity", "manage"),
        ("channel_connector", "manage"),
        ("agent_job", "debug"),
        ("mcp_server", "read"),
        ("mcp_tool", "manage"),
        ("mcp_resource", "manage"),
        ("secret", "manage"),
    ):
        assert c.authorization_evaluator.decide(
            user_id=str(admin["id"]),
            resource_type=resource_type,
            resource_code="*",
            action=action,
        ).allowed

    viewer = c.identity_repository.create_user(username="viewer", display_name="Viewer")
    viewer_role = c.identity_repository.create_role(code="viewer", name="Viewer")
    c.identity_repository.assign_role(
        user_id=str(viewer["id"]),
        role_id=str(viewer_role["id"]),
    )
    assert not c.authorization_evaluator.decide(
        user_id=str(viewer["id"]),
        resource_type="dashboard",
        resource_code="*",
        action="read",
    ).allowed


def test_service_account_cannot_gain_web_management_even_with_platform_admin_role() -> None:
    c = container()
    service = c.identity_repository.create_user(
        username="service-with-admin-role",
        display_name="Service",
        account_type="service",
    )
    role = c.identity_repository.get_role_by_code("platform-admin")
    assert role is not None
    c.identity_repository.assign_role(
        user_id=str(service["id"]),
        role_id=str(role["id"]),
    )
    decision = c.authorization_evaluator.decide(
        user_id=str(service["id"]),
        resource_type="user",
        resource_code="*",
        action="manage",
    )
    assert not decision.allowed
    assert decision.reason == "service_account_web_management_forbidden"
