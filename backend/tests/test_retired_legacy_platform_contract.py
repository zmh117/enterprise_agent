from __future__ import annotations

from pathlib import Path

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
    "agent_job_execution_binding",
    "agent_tool_binding",
    "tool_definition",
    "datasource_registry",
}

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RETIRED_SOURCE_PATHS = (
    "backend/app/modules/api_capability",
    "backend/app/modules/internal_api_platform",
    "backend/app/modules/local_internal_api_platform",
    "backend/app/modules/internal_tools",
    "backend/app/internal_api_platform.py",
    "backend/app/local_internal_api_platform.py",
    "backend/app/mock_internal_api_platform.py",
    "backend/app/shared/service_token.py",
)
RETIRED_ACTIVE_MARKERS = (
    "runtime-tool-mcp",
    "RUNTIME_TOOL_MCP_",
    "INTERNAL_API_",
    "internal-api-platform",
    "app.modules.api_capability",
    "app.modules.internal_api_platform",
    "/platform/api-capabilities",
    "/platform/builtin-tools",
)


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
    assert runtime.database.execute_one(
        "select count(*) as count from rbac_role_admin_capability where capability_code like 'builtin_tools.%'"
    )["count"] == 0
    assert runtime.database.execute_one(
        "select count(*) as count from permission_policy where resource_type = 'builtin_tool'"
    )["count"] == 0


def test_retired_source_paths_and_active_configuration_markers_are_absent() -> None:
    residual_paths: list[str] = []
    for relative in RETIRED_SOURCE_PATHS:
        path = REPOSITORY_ROOT / relative
        if path.is_file():
            residual_paths.append(relative)
        elif path.is_dir() and any(
            child.is_file() and "__pycache__" not in child.parts
            for child in path.rglob("*")
        ):
            residual_paths.append(relative)
    assert residual_paths == []

    candidates = [REPOSITORY_ROOT / ".env.example", REPOSITORY_ROOT / "docker-compose.yml"]
    candidates.extend(REPOSITORY_ROOT.glob("docker-compose.*.yml"))
    for relative in ("backend/app", "frontend/src", "scripts"):
        candidates.extend(
            path
            for path in (REPOSITORY_ROOT / relative).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    residuals: list[str] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in RETIRED_ACTIVE_MARKERS:
            if marker in text:
                residuals.append(f"{path.relative_to(REPOSITORY_ROOT)}: {marker}")
    assert residuals == []
