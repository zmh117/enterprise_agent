from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_agent_runtime_grants_are_narrow_and_isolate_business_tables() -> None:
    grants = (ROOT / "backend/maintenance/agent_runtime_grants.sql").read_text(encoding="utf-8")
    normalized = " ".join(grants.lower().split())

    assert "grant all" not in normalized
    assert "agent_job" not in normalized
    assert "permission_policy" not in normalized
    assert "audit_event" not in normalized
    assert "delivery_outbox" not in normalized
    assert "grant select (id, protocol, status) on model_connection" in normalized
    assert "ciphertext" in normalized
    assert (
        "grant select, insert, delete on agent_runtime_terminal_ledger to agent_runtime_reader"
    ) in normalized
    assert (
        "grant select, insert, delete on agent_runtime_invocation_claim to agent_runtime_reader"
    ) in normalized
    assert (
        "grant select, insert, delete on agent_runtime_invocation_event to agent_runtime_reader"
    ) in normalized
    assert "update on agent_runtime_terminal_ledger" not in normalized
    assert "update on agent_runtime_invocation_claim" not in normalized
    assert "update on agent_runtime_invocation_event" not in normalized


def test_dual_runtimes_and_standard_mcp_are_hardened_and_secret_scoped() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    typescript_runtime = services["typescript-agent-runtime"]
    python_runtime = services["python-agent-runtime"]
    tool_mcp = services["tool-mcp"]
    for service in (python_runtime, typescript_runtime, tool_mcp):
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["tmpfs"]
        assert "agent-runtime-control" in service["networks"]

    assert typescript_runtime["environment"]["DATABASE_URL"].startswith(
        "${AGENT_RUNTIME_DATABASE_DSN:-postgresql://agent_runtime_reader:"
    )
    assert python_runtime["environment"]["DATABASE_DSN"].startswith(
        "${AGENT_RUNTIME_DATABASE_DSN:-postgresql://agent_runtime_reader:"
    )
    assert typescript_runtime["environment"]["AGENT_RUNTIME_CLI_VERSION"] == "2.1.226"
    assert python_runtime["environment"]["PYTHON_AGENT_RUNTIME_CLI_VERSION"] == "2.1.226"
    assert python_runtime["environment"]["HOME"] == "/tmp/python-agent-runtime"
    assert python_runtime["environment"]["TMPDIR"] == "/tmp/python-agent-runtime"
    assert python_runtime["environment"]["CLAUDE_CONFIG_DIR"] == (
        "/tmp/python-agent-runtime/.claude"
    )
    assert python_runtime["tmpfs"] == [
        "/tmp/python-agent-runtime:size=32m,mode=0700,uid=10002,gid=10002"
    ]
    for runtime in (python_runtime, typescript_runtime):
        assert "runtime_grant_public_key" in runtime["secrets"]
        assert "runtime_grant_private_key" not in runtime["secrets"]
        assert runtime["environment"]["MCP_TOOL_SERVER_URL"] == "http://tool-mcp:9103/mcp"
        assert runtime["environment"]["AGENT_RUNTIME_TEST_PROVIDER_MODE"] == (
            "${AGENT_RUNTIME_TEST_PROVIDER_MODE:-disabled}"
        )
        assert "ports" not in runtime
    assert typescript_runtime["environment"]["APP_ENV"] == "${APP_ENV:-local}"
    assert "ports" not in tool_mcp
    assert not any(
        "runtime_grant" in str(item).lower() or "mcp_signing" in str(item).lower()
        for item in tool_mcp.get("secrets", [])
    )

    api = services["api-server"]
    worker = services["agent-worker"]
    assert "model_probe_auth_token" in api["secrets"]
    assert "model_probe_auth_token" not in worker["secrets"]
    assert "runtime_grant_private_key" in worker["secrets"]
    assert "runtime_grant_public_key" not in worker["secrets"]
    assert not any("mcp" in str(item).lower() for item in worker["secrets"])

    assert "runtime-tool-mcp" not in services
    assert "runtime_tool_mcp_signing_key" not in compose.get("secrets", {})

    assert compose["networks"]["agent-runtime-control"]["internal"] is True


def test_api_server_alone_receives_fixed_ones_identity_provider_configuration() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    expected = {
        "ONES_IDENTITY_INSTANCE_CODE": "${ONES_IDENTITY_INSTANCE_CODE:-default}",
        "ONES_IDENTITY_DISPLAY_NAME": "${ONES_IDENTITY_DISPLAY_NAME:-ONES}",
        "ONES_IDENTITY_BASE_URL": "${ONES_IDENTITY_BASE_URL:-}",
        "ONES_IDENTITY_ALLOWED_HOSTS": "${ONES_IDENTITY_ALLOWED_HOSTS:-}",
        "ONES_IDENTITY_TIMEOUT_SECONDS": "${ONES_IDENTITY_TIMEOUT_SECONDS:-5}",
        "ONES_IDENTITY_MAX_RESPONSE_BYTES": "${ONES_IDENTITY_MAX_RESPONSE_BYTES:-65536}",
        "ONES_IDENTITY_ALLOW_INSECURE_LOCAL": ("${ONES_IDENTITY_ALLOW_INSECURE_LOCAL:-false}"),
        "ONES_IDENTITY_CHALLENGE_TTL_SECONDS": ("${ONES_IDENTITY_CHALLENGE_TTL_SECONDS:-600}"),
    }

    api_environment = services["api-server"]["environment"]
    assert {key: api_environment[key] for key in expected} == expected

    for service_name, service in services.items():
        if service_name == "api-server":
            continue
        environment = service.get("environment", {})
        assert not set(expected).intersection(environment), service_name


def test_worker_image_has_no_claude_sdk_or_cli_layer() -> None:
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    worker_section = dockerfile.split("FROM python-deps AS agent-worker", 1)[1].split(
        "FROM claude-runtime AS python-agent-runtime", 1
    )[0]
    assert "claude-runtime" not in worker_section
    assert "claude-agent-sdk" not in worker_section
    assert "@anthropic-ai/claude-code" not in worker_section
    assert "COPY .claude/skills /app/.claude/skills" in worker_section
    assert "COPY .claude/settings" not in worker_section
    assert "python_runtime" not in worker_section
    assert not (
        ROOT / "backend/app/modules/agent/infrastructure/claude_code_agent_client.py"
    ).exists()

    python_runtime_section = dockerfile.split("FROM claude-runtime AS python-agent-runtime", 1)[
        1
    ].split("FROM api-server AS tool-mcp", 1)[0]
    assert "COPY backend/app /app/backend/app" not in python_runtime_section
    assert "modules/job" not in python_runtime_section
    assert "modules/delivery" not in python_runtime_section
    assert "modules/message_bus" not in python_runtime_section

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    base_dependencies = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "claude-agent-sdk" not in base_dependencies
    assert '"mcp' not in base_dependencies
    assert '"claude-agent-sdk==0.2.134"' in pyproject


def test_runtime_migrator_applies_and_verifies_service_grants_after_schema() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    command = " ".join(compose["services"]["migrator"]["command"])

    assert command.index("app.cli.migrate") < command.index("app.cli.apply_agent_runtime_grants")
    assert (
        compose["services"]["migrator"]["environment"]["AGENT_RUNTIME_DATABASE_PASSWORD"]
        == "${AGENT_RUNTIME_DATABASE_PASSWORD:-agent_runtime_reader_local}"
    )


def test_async_job_creation_workers_can_reach_both_agent_runtimes() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    for service_name in ("channel-dispatch-worker", "webhook-worker"):
        service = services[service_name]
        assert set(service["networks"]) == {"default", "agent-runtime-control"}
        for runtime_name in ("python-agent-runtime", "typescript-agent-runtime"):
            assert service["depends_on"][runtime_name] == {"condition": "service_healthy"}
