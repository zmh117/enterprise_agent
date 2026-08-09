from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _text_files(root: Path, suffixes: set[str]) -> str:
    if not root.exists():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in suffixes
    )


def test_retired_backend_and_frontend_source_roots_are_physically_empty() -> None:
    assert not (ROOT / "backend/app/mock_internal_api_platform.py").exists()
    for relative in (
        "backend/app/modules/api_capability",
        "backend/app/modules/internal_api_platform",
        "backend/app/modules/local_internal_api_platform",
        "backend/app/modules/internal_tools",
    ):
        root = ROOT / relative
        assert not list(root.rglob("*.py")) if root.exists() else True

    for relative in (
        "frontend/src/contexts/api-capabilities",
        "frontend/src/contexts/platform-governance",
        "frontend/src/contexts/applications",
        "frontend/src/contexts/authorization",
    ):
        root = ROOT / relative
        assert (
            not [path for path in root.rglob("*") if path.suffix in {".ts", ".tsx"}]
            if root.exists()
            else True
        )


def test_active_runtime_has_no_legacy_import_service_flag_or_tool_name() -> None:
    backend = _text_files(ROOT / "backend/app", {".py"})
    frontend = _text_files(ROOT / "frontend/src", {".ts", ".tsx"})
    deployment = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            ".env.example",
            "docker-compose.yml",
            "backend/Dockerfile",
            "pyproject.toml",
            "backend/seeds/local_seed.sql",
        )
    )
    active = "\n".join((backend, frontend, deployment))
    for forbidden in (
        "app.modules.api_capability",
        "app.modules.internal_api_platform",
        "app.modules.local_internal_api_platform",
        "app.modules.internal_tools",
        "internal-api-platform",
        "local-internal-api-platform",
        "FEATURE_REAL_INTERNAL_TOOLS",
        "INTERNAL_API_AUTH_TOKEN_FILE",
        "query_database",
        "query_redis_get",
        "query_redis_scan",
        "query_loki",
        "get_schema_directory",
        "diagnose_loki",
    ):
        assert forbidden not in active


def test_cutover_manifest_covers_legacy_tables_and_columns() -> None:
    manifest = json.loads(
        (ROOT / "config/legacy-platform-retirement.json").read_text(encoding="utf-8")
    )
    assert "agent_tool_call" in manifest["drop_tables"]
    assert {(value["table"], value["column"]) for value in manifest["drop_columns"]} == {
        ("agent_definition", "classification"),
        ("agent_job", "execution_scope_id"),
        ("agent_job", "execution_scope_hash"),
        ("business_application_revision", "api_capability_release_ids_json"),
    }
    assert all(value is False for value in manifest["policy"].values())


def test_agent_and_mcp_servers_keep_separate_exact_dependency_boundaries() -> None:
    agent = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"claude-agent-sdk==0.2.134"' in agent
    assert '"mcp>=1.23.0,<2.0.0"' in agent
    for service in ("ones-mcp-server", "data-mcp-server"):
        pyproject = (ROOT / "services" / service / "pyproject.toml").read_text(encoding="utf-8")
        lock = (ROOT / "services" / service / "requirements.lock").read_text(encoding="utf-8")
        assert '"mcp==2.0.0"' in pyproject
        assert "mcp==2.0.0" in lock
