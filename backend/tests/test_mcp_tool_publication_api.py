from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings
from backend.tests.helpers import test_settings as base_test_settings


ADMIN = "user_local_admin"
NOW = "2026-08-09T00:00:00+00:00"


def _publish(container, code: str) -> str:
    service = container.mcp_tool_publication_service
    service.create(
        code=code,
        name=code,
        catalog_key="ones-mcp/ones_work_item_search",
        actor_id=ADMIN,
        idempotency_key=f"{code}-create",
    )
    service.verify(code, expected_revision=1, actor_id=ADMIN)
    result = service.publish(
        code,
        expected_revision=1,
        actor_id=ADMIN,
        idempotency_key=f"{code}-publish",
    )
    return str(result["publication_id"])


def _grant_specific_read(container, code: str) -> str:
    user_id = "user_tool_reader"
    role_id = "role_tool_reader"
    container.database.execute(
        """
        insert into app_user
          (id, username, display_name, email, status, account_type,
           revision, created_at, updated_at)
        values (?, 'tool-reader', 'Tool Reader', '', 'enabled', 'human', 1, ?, ?)
        """,
        (user_id, NOW, NOW),
    )
    container.database.execute(
        """
        insert into rbac_role
          (id, code, name, description, status, revision, created_at, updated_at)
        values (?, 'tool-reader', 'Tool Reader', '', 'enabled', 1, ?, ?)
        """,
        (role_id, NOW, NOW),
    )
    container.database.execute(
        """
        insert into rbac_user_role
          (id, user_id, role_id, status, revision, created_at, updated_at)
        values ('membership_tool_reader', ?, ?, 'enabled', 1, ?, ?)
        """,
        (user_id, role_id, NOW, NOW),
    )
    container.database.execute(
        """
        insert into rbac_role_admin_capability
          (id, role_id, capability_code, resource_type, resource_code,
           status, created_at, updated_at)
        values ('capability_tool_reader', ?, 'mcp_tools.read', 'mcp_tool', ?,
                'enabled', ?, ?)
        """,
        (role_id, code, NOW, NOW),
    )
    return user_id


def test_tool_publication_queries_filter_specific_scope_and_hide_other_targets() -> None:
    settings = replace(
        base_test_settings(),
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )
    container = build_test_container(settings, migrate=True, seed=True)
    visible_publication = _publish(container, "visible-tool")
    hidden_publication = _publish(container, "hidden-tool")
    user_id = _grant_specific_read(container, "visible-tool")
    headers = {"x-admin-user-id": user_id}

    try:
        with TestClient(create_app(settings, container_factory=lambda _: container)) as client:
            listed = client.get("/api/admin/mcp/tool-publications", headers=headers)
            assert listed.status_code == 200
            assert [item["code"] for item in listed.json()["tools"]] == ["visible-tool"]
            assert listed.json()["permissions"] == {"can_create": False}

            assert (
                client.get(
                    "/api/admin/mcp/tool-publications/visible-tool", headers=headers
                ).status_code
                == 200
            )
            hidden = client.get("/api/admin/mcp/tool-publications/hidden-tool", headers=headers)
            missing = client.get("/api/admin/mcp/tool-publications/missing-tool", headers=headers)
            assert hidden.status_code == missing.status_code == 404
            assert hidden.json() == missing.json()

            assert (
                client.get(
                    f"/api/admin/mcp/tool-publications/{visible_publication}/usage",
                    headers=headers,
                ).status_code
                == 200
            )
            hidden_usage = client.get(
                f"/api/admin/mcp/tool-publications/{hidden_publication}/usage",
                headers=headers,
            )
            missing_usage = client.get(
                "/api/admin/mcp/tool-publications/missing-publication/usage",
                headers=headers,
            )
            assert hidden_usage.status_code == missing_usage.status_code == 404
            assert hidden_usage.json() == missing_usage.json()
    finally:
        container.database.close()
