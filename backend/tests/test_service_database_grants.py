from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

from app.cli.apply_service_grants import _role_password_statement, apply_service_grants
from app.shared.database import Database


ROOT = Path(__file__).resolve().parents[2]


def test_non_postgres_test_runtime_never_attempts_role_mutation(tmp_path: Path) -> None:
    database = Database("sqlite:///:memory:")
    try:
        result = apply_service_grants(
            database,
            grants_path=tmp_path / "not-needed-for-sqlite.sql",
        )
    finally:
        database.close()
    assert result == "skipped_non_postgres"


def test_grants_are_explicit_and_exclude_retired_platform_tables() -> None:
    sql = (ROOT / "backend/maintenance/mcp_service_grants.sql").read_text()
    normalized = " ".join(sql.lower().split())
    assert "grant all" not in normalized
    assert "api_capability" not in normalized
    assert "api_connection" not in normalized
    assert "tool_definition" not in normalized
    assert "platform_resource" not in normalized
    for role in (
        "enterprise_agent_api",
        "enterprise_agent_worker",
        "ones_mcp_reader",
        "data_mcp_runtime",
    ):
        assert role in sql

    data_grants = normalized.split("-- data mcp resolves", 1)[1]
    assert "platform_secret_change_event" in data_grants
    assert (
        "grant insert on table mcp_resource_generation, "
        "mcp_resource_generation_secret_version to data_mcp_runtime"
    ) in data_grants
    assert (
        "grant update on table mcp_resource_deployment, "
        "mcp_resource_generation, platform_secret_change_event to data_mcp_runtime"
    ) in data_grants


def test_service_grants_do_not_reference_tables_retired_by_head_migration() -> None:
    grants_sql = (ROOT / "backend/maintenance/mcp_service_grants.sql").read_text()
    retirement_sql = (
        ROOT / "backend/migrations/040_remove_retired_platform_schema.sql"
    ).read_text()
    retired_tables = set(re.findall(r"(?m)^  ([a-z][a-z0-9_]*)[,;]$", retirement_sql))

    stale_grants = sorted(
        table for table in retired_tables if re.search(rf"\b{re.escape(table)}\b", grants_sql)
    )

    assert stale_grants == []


def test_compose_separates_database_roles_and_master_key_mounts() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert "builtin-tool-compose-acceptance" not in services
    assert "enterprise_agent_api" in services["api-server"]["environment"]["DATABASE_DSN"]
    assert "enterprise_agent_worker" in services["agent-worker"]["environment"]["DATABASE_DSN"]
    assert "ones_mcp_reader" in services["ones-mcp-server"]["environment"]["DATABASE_DSN"]
    assert "data_mcp_runtime" in services["data-mcp-server"]["environment"]["DATABASE_DSN"]

    agent = services["agent-worker"]
    assert "APP_CONFIG_MASTER_KEY_FILE" not in agent["environment"]
    assert "app_config_master_key" not in agent.get("secrets", [])
    for worker_name in (
        "agent-worker",
        "job-dispatch-worker",
        "delivery-dispatch-worker",
        "webhook-worker",
        "channel-dispatch-worker",
        "attachment-worker",
    ):
        worker = services[worker_name]
        assert "MODEL_PROBE_AUTH_TOKEN_FILE" not in worker["environment"]
        assert "model_probe_auth_token" not in worker.get("secrets", [])
    assert (
        services["api-server"]["environment"]["MODEL_PROBE_AUTH_TOKEN_FILE"]
        == "/run/secrets/model_probe_auth_token"
    )
    assert "model_probe_auth_token" in services["api-server"]["secrets"]
    for decrypting_service in (
        "api-server",
        "ones-mcp-server",
        "data-mcp-server",
        "delivery-dispatch-worker",
        "attachment-worker",
    ):
        assert "APP_CONFIG_MASTER_KEY_FILE" in services[decrypting_service]["environment"]
        assert "app_config_master_key" in services[decrypting_service]["secrets"]


def test_short_service_passwords_fail_before_database_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = Database("sqlite:///:memory:")
    database.engine = "postgres"  # type: ignore[assignment]
    monkeypatch.setenv("API_DATABASE_PASSWORD", "short")
    monkeypatch.setenv("WORKER_DATABASE_PASSWORD", "long-enough-worker-password")
    monkeypatch.setenv("ONES_MCP_DATABASE_PASSWORD", "long-enough-ones-password")
    monkeypatch.setenv("DATA_MCP_DATABASE_PASSWORD", "long-enough-data-password")
    try:
        with pytest.raises(RuntimeError, match="API_DATABASE_PASSWORD"):
            apply_service_grants(database, grants_path=tmp_path / "unused.sql")
    finally:
        database.close()


def test_role_password_ddl_is_safely_composed_without_bind_placeholders() -> None:
    statement = _role_password_statement(
        role="enterprise_agent_api",
        password="long-enough-'quoted'-password",
        exists=False,
    ).as_string(None)

    assert statement == (
        "CREATE ROLE \"enterprise_agent_api\" LOGIN PASSWORD 'long-enough-''quoted''-password'"
    )
    assert "$1" not in statement
