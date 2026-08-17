from __future__ import annotations

import json

import pytest

from app.modules.agent.application.typescript_runtime_retirement import (
    TypeScriptRuntimeRetirementPreflight,
)
from app.shared.database import Database


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    value.execute_script(
        """
        create table schema_migration (version text primary key);
        create table agent_definition (
          id text primary key, code text, status text, current_publication_id text,
          runtime_kind text not null
        );
        create table agent_publication (
          id text primary key, agent_id text, revision integer, status text,
          runtime_kind text not null
        );
        create table business_application_revision (
          id text primary key, application_id text, agent_publication_id text
        );
        create table business_application_publication (
          id text primary key, revision_id text
        );
        create table business_application_deployment (
          id text primary key, application_id text, environment text,
          publication_id text, active integer
        );
        create table agent_job (
          id text primary key, status text, agent_runtime_kind text,
          user_message text default ''
        );
        create table job_dispatch_outbox (
          id text primary key, job_id text, status text
        );
        create table platform_runtime_config_definition (
          id text primary key, key text, service_names_json text, status text
        );
        create table platform_runtime_config_value (
          id text primary key, definition_id text, key text,
          service_name text, status text, value_json text default 'null',
          secret_ref text default ''
        );
        insert into schema_migration(version) values ('111');
        """,
        ignore_existing_errors=False,
    )
    try:
        yield value
    finally:
        value.close()


def _preflight(
    database: Database,
    *,
    queue_inspector=lambda: {
        "job_queue": {"exists": True, "messages": 0, "consumers": 1},
        "retry_queue": {"exists": True, "messages": 0, "consumers": 0},
        "dead_queue": {"exists": True, "messages": 0, "consumers": 0},
        "legacy_retry_queue": {"exists": True, "messages": 0, "consumers": 0},
    },
    observed_environment: str = "local",
    expected_environments: tuple[str, ...] = ("local",),
    checkout: dict[str, object] | None = None,
    environ: dict[str, str] | None = None,
) -> TypeScriptRuntimeRetirementPreflight:
    return TypeScriptRuntimeRetirementPreflight(
        database=database,
        queue_inspector=queue_inspector,
        target_environment="local",
        observed_environment=observed_environment,
        expected_environments=expected_environments,
        checkout=checkout or {"verified": True, "branch": "mcp_new", "commit": "synthetic-commit"},
        environ=environ or {},
    )


def test_preflight_allows_only_terminal_historical_typescript_facts_without_content(
    database: Database,
) -> None:
    sensitive = "MUST-NOT-APPEAR"
    database.execute(
        "insert into agent_definition values (?, ?, 'enabled', null, 'typescript-v1')",
        ("agent-ts", "typescript-diagnostic-agent"),
    )
    database.execute(
        "insert into agent_publication values (?, ?, 1, 'inactive', 'typescript-v1')",
        ("agent-publication-ts", "agent-ts"),
    )
    database.execute(
        "insert into agent_job values (?, 'SUCCEEDED', 'typescript-v1', ?)",
        ("job-ts-terminal", sensitive),
    )
    database.execute(
        "insert into job_dispatch_outbox values (?, ?, 'PUBLISHED')",
        ("outbox-ts-terminal", "job-ts-terminal"),
    )

    report = _preflight(database).run()

    assert report["status"] == "ready"
    assert report["write_performed"] is False
    assert report["database"]["typescript_jobs_by_status"] == {"SUCCEEDED": 1}
    assert report["coverage"]["verified_environments"] == ["local"]
    assert sensitive not in json.dumps(report, ensure_ascii=False)


def test_preflight_reports_current_history_and_blocks_executable_typescript_work(
    database: Database,
) -> None:
    database.execute(
        "insert into agent_definition values (?, ?, 'enabled', ?, 'typescript-v1')",
        ("agent-ts", "typescript-diagnostic-agent", "agent-publication-ts"),
    )
    database.execute(
        "insert into agent_publication values (?, ?, 1, 'active', 'typescript-v1')",
        ("agent-publication-ts", "agent-ts"),
    )
    database.execute(
        "insert into business_application_revision values (?, ?, ?)",
        ("application-revision-ts", "application-ts", "agent-publication-ts"),
    )
    database.execute(
        "insert into business_application_publication values (?, ?)",
        ("application-publication-ts", "application-revision-ts"),
    )
    database.execute(
        "insert into business_application_deployment values (?, ?, 'local', ?, 1)",
        ("deployment-ts", "application-ts", "application-publication-ts"),
    )
    database.execute(
        "insert into agent_job values (?, 'RETRY_WAIT', 'typescript-v1', '')",
        ("job-ts-retry",),
    )
    database.execute(
        "insert into job_dispatch_outbox values (?, ?, 'RETRY_WAIT')",
        ("outbox-ts-retry", "job-ts-retry"),
    )

    report = _preflight(database).run()

    assert report["status"] == "blocked"
    assert report["blocker_codes"] == [
        "typescript_active_deployment",
        "typescript_non_terminal_jobs",
        "typescript_non_terminal_outbox",
    ]
    assert report["database"]["active_typescript_deployments"] == [
        {
            "deployment_id": "deployment-ts",
            "application_id": "application-ts",
            "environment": "local",
            "publication_id": "application-publication-ts",
        }
    ]
    assert report["database"]["current_typescript_publication_ids"] == ["agent-publication-ts"]


def test_preflight_blocks_runtime_configuration_without_exposing_values(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive = "secret://platform/must-not-appear"
    database.execute(
        "insert into platform_runtime_config_definition values (?, ?, ?, 'enabled')",
        (
            "definition-ts",
            "TYPESCRIPT_AGENT_RUNTIME_URL",
            '["typescript-agent-runtime"]',
        ),
    )
    database.execute(
        "insert into platform_runtime_config_value values (?, ?, ?, ?, 'enabled', ?, ?)",
        (
            "value-ts",
            "definition-ts",
            "TYPESCRIPT_AGENT_RUNTIME_URL",
            "typescript-agent-runtime",
            '"http://typescript-agent-runtime:8090"',
            sensitive,
        ),
    )

    executed: list[tuple[str, tuple[object, ...]]] = []
    original_execute = database.execute

    def recording_execute(
        sql: str,
        params: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        executed.append((sql, tuple(params)))
        return original_execute(sql, params)

    monkeypatch.setattr(database, "execute", recording_execute)

    report = _preflight(
        database,
        environ={"TYPESCRIPT_AGENT_RUNTIME_URL": "http://must-not-appear.invalid"},
    ).run()

    assert report["status"] == "blocked"
    assert "typescript_database_runtime_configuration" in report["blocker_codes"]
    assert "typescript_environment_runtime_configuration" in report["blocker_codes"]
    encoded = json.dumps(report, ensure_ascii=False)
    assert sensitive not in encoded
    assert "must-not-appear.invalid" not in encoded
    assert report["runtime_configuration"]["values_exposed"] is False
    runtime_config_queries = [
        (sql, params) for sql, params in executed if "platform_runtime_config_definition" in sql
    ]
    assert len(runtime_config_queries) == 1
    assert "%typescript%runtime%" not in runtime_config_queries[0][0]
    assert runtime_config_queries[0][1] == (
        "%typescript%runtime%",
        "%typescript-agent-runtime%",
        "%typescript%runtime%",
        "typescript-agent-runtime",
    )


def test_preflight_fails_closed_when_queue_or_environment_coverage_is_unknown(
    database: Database,
) -> None:
    def unavailable_queue() -> dict[str, object]:
        raise ConnectionError("amqp://credential-must-not-appear")

    report = _preflight(
        database,
        queue_inspector=unavailable_queue,
        expected_environments=("local", "production"),
    ).run()

    assert report["status"] == "blocked"
    assert "queue_unavailable" in report["blocker_codes"]
    assert "environment_coverage_incomplete" in report["blocker_codes"]
    assert report["coverage"]["unverified_environments"] == ["local", "production"]
    assert "credential-must-not-appear" not in json.dumps(report, ensure_ascii=False)


def test_preflight_fails_closed_for_incomplete_or_nonempty_executable_queues(
    database: Database,
) -> None:
    report = _preflight(
        database,
        queue_inspector=lambda: {
            "job_queue": {"exists": True, "messages": 1, "consumers": 1},
            "dead_queue": {"exists": True, "messages": 3, "consumers": 0},
            "legacy_retry_queue": {"exists": True, "messages": 0, "consumers": 0},
        },
    ).run()

    assert report["status"] == "blocked"
    assert "queue_topology_incomplete" in report["blocker_codes"]
    assert "runtime_queue_not_empty" in report["blocker_codes"]
    assert report["queue"]["status"] == "incomplete"
    assert report["queue"]["missing_or_unverified_queue_labels"] == ["retry_queue"]
    assert report["coverage"]["unverified_environments"] == ["local"]
    assert report["queue"]["executable_messages_by_queue"] == {
        "job_queue": 1,
        "retry_queue": 0,
        "legacy_retry_queue": 0,
    }


def test_preflight_treats_broker_verified_absent_retry_queues_as_zero(
    database: Database,
) -> None:
    report = _preflight(
        database,
        queue_inspector=lambda: {
            "job_queue": {"exists": True, "messages": 0, "consumers": 1},
            "retry_queue": {"exists": False, "messages": 0, "consumers": 0},
            "dead_queue": {"exists": True, "messages": 0, "consumers": 0},
            "legacy_retry_queue": {"exists": False, "messages": 0, "consumers": 0},
        },
    ).run()

    assert report["status"] == "ready"
    assert report["queue"]["missing_or_unverified_queue_labels"] == []
    assert report["queue"]["verified_absent_queue_labels"] == [
        "retry_queue",
        "legacy_retry_queue",
    ]


def test_preflight_fails_closed_when_database_is_unavailable() -> None:
    database = Database("sqlite:///:memory:")
    try:
        report = _preflight(database).run()
    finally:
        database.close()

    assert report["status"] == "blocked"
    assert "database_unavailable" in report["blocker_codes"]
    assert report["database"]["status"] == "unavailable"


def test_preflight_requires_verified_checkout_and_matching_observed_environment(
    database: Database,
) -> None:
    report = _preflight(
        database,
        observed_environment="production",
        checkout={"verified": False, "branch": "unknown", "commit": "unknown"},
    ).run()

    assert report["status"] == "blocked"
    assert "checkout_unverified" in report["blocker_codes"]
    assert "target_environment_mismatch" in report["blocker_codes"]
    assert "environment_coverage_incomplete" in report["blocker_codes"]
