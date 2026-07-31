from __future__ import annotations

from dataclasses import replace

from app import main
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
            "schema_head": "025",
            "rabbitmq": True,
            "internal_api_token": True,
            "master_key": True,
            "runtime_assembly": True,
        }
        assert ready["resources"]["status"] == "EMPTY"
        assert ready["claude_invoked"] is False

        missing_key = main._build_readiness(
            replace(runtime.settings, app_config_master_key=""),
            database=runtime.database,
        )
        assert missing_key["status"] == "not_ready"
        assert missing_key["core"]["master_key"] is False
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
        runtime.database.execute(
            "delete from schema_migration where version = '023'"
        )
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
