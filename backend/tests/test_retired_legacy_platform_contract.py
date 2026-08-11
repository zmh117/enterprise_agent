from __future__ import annotations

from app.main import create_app
from backend.tests.helpers import container, test_settings as make_settings


RETIRED_ROUTE_MARKERS = (
    "api-capabilities",
    "api-connections",
    "resource-mappings",
    "handlers",
    "external-credentials",
    "internal-api-platform",
)

RETIRED_TABLES = {
    "api_capability",
    "api_connection",
    "api_handler",
    "handler_installation",
    "handler_publication",
    "platform_resource_binding",
    "business_application_resource_binding",
    "business_application_publication_builtin_tool_resource",
    "builtin_tool_release",
    "external_api_credential",
}


def test_retired_management_and_internal_platform_routes_are_absent() -> None:
    app = create_app(make_settings())
    paths = {
        str(getattr(route, "path", ""))
        for route in app.routes
        if getattr(route, "path", "")
    }

    assert not {
        path
        for path in paths
        if any(marker in path for marker in RETIRED_ROUTE_MARKERS)
    }


def test_retired_tables_are_absent_and_direct_mcp_tables_are_present() -> None:
    runtime = container()
    tables = {
        str(row["name"])
        for row in runtime.database.execute(
            "select name from sqlite_master where type = 'table'"
        )
    }

    assert RETIRED_TABLES.isdisjoint(tables)
    assert {
        "agent_publication_mcp_tool",
        "business_application_revision_mcp_tool",
        "business_application_publication_mcp_tool",
        "agent_job_mcp_tool_snapshot",
        "rbac_role_application_mcp_tool",
    } <= tables
