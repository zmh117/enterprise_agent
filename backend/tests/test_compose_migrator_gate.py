from __future__ import annotations

from pathlib import Path

import yaml

from app.cli.apply_local_seed import local_seed_sql
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
LOCAL_SEED_PATH = ROOT / "backend" / "seeds" / "local_seed.sql"


def test_compose_postgres_uses_asia_shanghai_timezone() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    postgres = compose["services"]["postgres"]

    assert postgres["environment"]["TZ"] == "Asia/Shanghai"
    assert postgres["command"] == [
        "postgres",
        "-c",
        "timezone=Asia/Shanghai",
    ]


def test_compose_business_services_wait_for_one_shot_migrator() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    migrator = services["migrator"]

    assert migrator["build"]["target"] == "migrator"
    assert migrator["restart"] == "no"
    assert migrator["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "APP_STARTUP_MIGRATE" not in COMPOSE_PATH.read_text(encoding="utf-8")

    for service_name in (
        "tool-mcp",
        "file-service",
        "python-agent-runtime",
        "api-server",
        "agent-worker",
        "job-dispatch-worker",
        "webhook-worker",
        "channel-dispatch-worker",
        "file-worker",
    ):
        assert services[service_name]["depends_on"]["migrator"] == {
            "condition": "service_completed_successfully"
        }


def test_runtime_services_do_not_force_local_seed_replay() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    for service_name in (
        "tool-mcp",
        "file-service",
        "python-agent-runtime",
        "api-server",
        "agent-worker",
        "job-dispatch-worker",
        "delivery-dispatch-worker",
        "webhook-worker",
        "channel-dispatch-worker",
        "file-worker",
    ):
        assert services[service_name].get("environment", {}).get(
            "SEED_LOCAL_CONFIG", "${SEED_LOCAL_CONFIG:-false}"
        ) in {"false", "${SEED_LOCAL_CONFIG:-false}"}


def test_local_seed_publication_tools_match_code_manifest(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'local-seed.db'}")
    try:
        Migrator(database, default_migrations_dir(), migrator_build="local-seed-test").run()
        database.execute_script(local_seed_sql())
        rows = database.execute(
            """
            select tool_identifier, server_code, schema_hash
              from agent_publication_mcp_tool
             where agent_publication_id = 'agent_publication_default_v1'
            """
        )
    finally:
        database.close()

    assert rows
    for row in rows:
        definition = MCP_TOOL_MANIFEST[row["tool_identifier"]]
        assert (row["server_code"], row["schema_hash"]) == (
            definition.server_code,
            definition.schema_hash,
        ), row["tool_identifier"]


def test_local_seed_is_additive_for_control_plane_connectors() -> None:
    seed_sql = LOCAL_SEED_PATH.read_text(encoding="utf-8").upper()
    assert "UPDATE INTEGRATION_CONNECTOR" not in seed_sql
