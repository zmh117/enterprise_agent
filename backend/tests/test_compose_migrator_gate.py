from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
LOCAL_SEED_PATH = ROOT / "backend" / "seeds" / "local_seed.sql"


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
        "typescript-agent-runtime",
        "python-agent-runtime",
        "api-server",
        "agent-worker",
        "job-dispatch-worker",
        "webhook-worker",
        "channel-dispatch-worker",
        "attachment-worker",
    ):
        assert services[service_name]["depends_on"]["migrator"] == {
            "condition": "service_completed_successfully"
        }


def test_runtime_services_do_not_force_local_seed_replay() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    for service_name in (
        "tool-mcp",
        "typescript-agent-runtime",
        "python-agent-runtime",
        "api-server",
        "agent-worker",
        "job-dispatch-worker",
        "delivery-dispatch-worker",
        "webhook-worker",
        "channel-dispatch-worker",
        "attachment-worker",
    ):
        assert services[service_name].get("environment", {}).get(
            "SEED_LOCAL_CONFIG", "${SEED_LOCAL_CONFIG:-false}"
        ) == "${SEED_LOCAL_CONFIG:-false}"


def test_local_seed_is_additive_for_control_plane_connectors() -> None:
    seed_sql = LOCAL_SEED_PATH.read_text(encoding="utf-8").upper()
    assert "UPDATE INTEGRATION_CONNECTOR" not in seed_sql
