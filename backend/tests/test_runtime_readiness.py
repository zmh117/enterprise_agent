from __future__ import annotations

from dataclasses import replace

from app import main
from app.shared.config import AgentRuntimeSettings
from backend.tests.helpers import container, test_settings as _test_settings


def test_health_is_liveness_only_and_never_checks_dependencies() -> None:
    settings = replace(
        _test_settings(),
        database_dsn="postgresql://unreachable.invalid/example",
        rabbitmq_url="amqp://unreachable.invalid/example",
    )
    assert main._build_health(settings) == {
        "status": "ok",
        "claude_invoked": False,
    }


def test_ready_checks_schema_database_rabbit_token_and_master_key(
    monkeypatch,
) -> None:
    runtime = container()
    try:
        monkeypatch.setattr(
            main,
            "_check_rabbitmq",
            lambda _url: True,
        )
        ready = main._build_readiness(
            runtime.settings,
            database=runtime.database,
        )
        assert ready["status"] == "ready"
        assert ready["core"] == {
            "database": True,
            "schema": True,
            "schema_head": "102",
            "rabbitmq": True,
            "master_key": True,
            "runtime_assembly": True,
            "agent_runtimes": {
                runtime_kind: {
                    "configured": False,
                    "ready": False,
                    "identity": "not_configured",
                    "database": "unavailable",
                    "master_key": "unavailable",
                    "runtime_version": "",
                    "protocol_version": "",
                    "sdk_version": "",
                    "cli_version": "",
                    "model_invoked": False,
                    "mcp_invoked": False,
                }
                for runtime_kind in ("python-v1", "typescript-v1")
            },
        }
        assert ready["tool_mcp"] == {
            "server_code": "tool-mcp",
            "transport": "streamable_http",
            "resource_resolution": "invocation_time",
        }
        assert ready["claude_invoked"] is False
        assert ready["mcp_invoked"] is False
        assert ready["runtime_selection"] == {
            "default_runtime": "python-v1",
            "supported_runtimes": ["python-v1", "typescript-v1"],
            "protocol_version": "1.0",
        }
        assert ready["runtime_config"] == {
            "source": runtime.settings.runtime_config_source,
            "degraded": runtime.settings.runtime_config_degraded,
            "revision": runtime.settings.runtime_config_revision,
            "config_hash": runtime.settings.runtime_config_hash,
            "errors": list(runtime.settings.runtime_config_errors),
        }
        assert isinstance(ready["runtime_config"]["revision"], int)
        assert len(ready["runtime_config"]["config_hash"]) == 64
        assert "test-only-master-key" not in str(ready["runtime_config"])

        missing_key = main._build_readiness(
            replace(runtime.settings, app_config_master_key=""),
            database=runtime.database,
        )
        assert missing_key["status"] == "not_ready"
        assert missing_key["core"]["master_key"] is False
    finally:
        runtime.database.close()


def test_unavailable_runtime_is_reported_without_disabling_management_api(monkeypatch) -> None:
    runtime = container()
    try:
        monkeypatch.setattr(main, "_check_rabbitmq", lambda _url: True)
        monkeypatch.setattr(
            main,
            "_check_agent_runtime",
            lambda _settings, **_kwargs: {
                "configured": True,
                "ready": False,
                "identity": "verified",
                "database": "ready",
                "master_key": "unavailable",
                "model_invoked": False,
                "mcp_invoked": False,
            },
        )
        settings = replace(
            runtime.settings,
            environment="canary",
            agent_runtime=AgentRuntimeSettings(
                python_base_url="http://python-agent-runtime:8091",
                python_allowed_hosts=("python-agent-runtime",),
                typescript_base_url="http://typescript-agent-runtime:8090",
                typescript_allowed_hosts=("typescript-agent-runtime",),
                allow_insecure_internal_http=True,
            ),
        )

        status = main._build_readiness(settings, database=runtime.database)

        assert status["status"] == "ready"
        assert status["runtime_selection"]["default_runtime"] == "python-v1"
        assert status["core"]["agent_runtimes"]["python-v1"]["master_key"] == "unavailable"
        assert status["claude_invoked"] is False
        assert status["mcp_invoked"] is False
    finally:
        runtime.database.close()


def test_schema_drift_makes_ready_fail_closed(monkeypatch) -> None:
    runtime = container()
    try:
        monkeypatch.setattr(
            main,
            "_check_rabbitmq",
            lambda _url: True,
        )
        runtime.database.execute("delete from schema_migration where version = '100'")
        status = main._build_readiness(
            runtime.settings,
            database=runtime.database,
        )
        assert status["status"] == "not_ready"
        assert status["core"]["database"] is True
        assert status["core"]["schema"] is False
        assert status["core"]["schema_head"] == ""
    finally:
        runtime.database.close()
