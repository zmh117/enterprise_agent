from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_agent_runtime_grants_are_narrow_and_isolate_business_tables() -> None:
    grants = (ROOT / "backend/maintenance/agent_runtime_grants.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(grants.lower().split())

    assert "grant all" not in normalized
    assert "agent_job" not in normalized
    assert "permission_policy" not in normalized
    assert "audit_event" not in normalized
    assert "delivery_outbox" not in normalized
    assert "grant select (id, protocol, status) on model_connection" in normalized
    assert "ciphertext" in normalized
    assert (
        "grant select, insert, delete on agent_runtime_terminal_ledger "
        "to agent_runtime_reader"
    ) in normalized
    assert "update on agent_runtime_terminal_ledger" not in normalized


def test_runtime_and_mcp_compose_services_are_hardened_and_secret_scoped() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    runtime = services["agent-runtime"]
    tool_mcp = services["runtime-tool-mcp"]
    for service in (runtime, tool_mcp):
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["tmpfs"]
        assert "agent-runtime-control" in service["networks"]

    assert runtime["environment"]["DATABASE_URL"].startswith(
        "${AGENT_RUNTIME_DATABASE_DSN:-postgresql://agent_runtime_reader:"
    )
    assert runtime["environment"]["AGENT_RUNTIME_CLI_VERSION"] == "2.1.226"
    assert "runtime_grant_public_key" in runtime["secrets"]
    assert "runtime_grant_private_key" not in runtime["secrets"]
    assert "runtime_tool_mcp_signing_key" not in runtime["secrets"]

    api = services["api-server"]
    worker = services["agent-worker"]
    assert "model_probe_auth_token" in api["secrets"]
    assert "model_probe_auth_token" not in worker["secrets"]
    assert "runtime_grant_private_key" in worker["secrets"]
    assert "runtime_grant_public_key" not in worker["secrets"]
    assert "runtime_tool_mcp_signing_key" in worker["secrets"]
    assert "runtime_tool_mcp_signing_key" in tool_mcp["secrets"]

    assert compose["networks"]["agent-runtime-control"]["internal"] is True


def test_runtime_migrator_applies_and_verifies_service_grants_after_schema() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    command = " ".join(compose["services"]["migrator"]["command"])

    assert command.index("app.cli.migrate") < command.index(
        "app.cli.apply_agent_runtime_grants"
    )
    assert (
        compose["services"]["migrator"]["environment"][
            "AGENT_RUNTIME_DATABASE_PASSWORD"
        ]
        == "${AGENT_RUNTIME_DATABASE_PASSWORD:-agent_runtime_reader_local}"
    )
