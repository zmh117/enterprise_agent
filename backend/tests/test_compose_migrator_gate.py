from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"


def test_compose_business_services_wait_for_one_shot_migrator() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    migrator = services["migrator"]

    assert migrator["build"]["target"] == "migrator"
    assert migrator["restart"] == "no"
    assert migrator["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "APP_STARTUP_MIGRATE" not in COMPOSE_PATH.read_text(encoding="utf-8")

    for service_name in (
        "local-internal-api-platform",
        "internal-api-platform",
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
