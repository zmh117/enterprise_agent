from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import threading
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.bootstrap import build_test_container, build_worker_container
from app.modules.admin.application.scope import AdminScope
from app.modules.admin.infrastructure import AdminJobQuery, AdminReadRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.delivery.application.delivery_dispatch_service import (
    DeliveryOutboxDispatcher,
)
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.job_dispatch_service import JobDispatchOutboxDispatcher
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository, AuditRepository
from app.modules.job.infrastructure.execution_audit_repository import (
    ExecutionAuditRepository,
)
from app.modules.mcp_audit import McpAuditContext, McpAuditCoordinator
from app.modules.platform_config.application.runtime_config import (
    RuntimeConfigRegistry,
    RuntimeConfigSnapshotBuilder,
)
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import (
    AgentRuntimeSettings,
    DeliverySettings,
    PrincipalJwtSettings,
    QueueSettings,
    Settings,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import (
    BaselineAdoptionInspector,
    BaselineAdoptionRollback,
    MigrationDefinitionError,
    MigrationExecutionError,
    Migrator,
    SchemaMigrationLedger,
)
from app.shared.schema_baseline import (
    LEGACY_MANIFEST_FILENAME,
    load_legacy_manifest,
    postgres_comment_snapshot,
)
from backend.tests.helpers import test_settings as make_test_settings


POSTGRES_DSN = os.getenv("MIGRATION_POSTGRES_DSN", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="set MIGRATION_POSTGRES_DSN to run PostgreSQL Migrator integration",
)


def test_postgres_admin_job_query_uses_json_filters_and_keyset_limit(
    postgres_database_dsn: str,
) -> None:
    settings = replace(make_test_settings(), database_dsn=postgres_database_dsn)
    runtime = build_test_container(settings, migrate=True, seed=True)
    try:
        session = runtime.agent_repository.create_session(
            project_code="postgres-query",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            external_conversation_id="postgres-admin-query",
            requester_id="user_local_admin",
            routing_context={"environment": "prod", "base": "postgres-base"},
            session_key="postgres-admin-query",
        )
        job = runtime.agent_repository.create_job(
            session_id=session.id,
            idempotency_key="postgres-admin-query",
            internal_user_id="user_local_admin",
            project_code="postgres-query",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            requester_id="user_local_admin",
            input_message="postgres query fixture",
            max_retry_count=3,
            routing_context={"environment": "prod", "base": "postgres-base"},
            business_application_route_decision={"correlation_id": "postgres-admin-query"},
            execution_policy={
                "schema_version": 1,
                "requested": {
                    "max_turns": 12,
                    "timeout_seconds": 300,
                    "max_tool_calls": 30,
                },
                "effective": {
                    "max_turns": 12,
                    "timeout_seconds": 300,
                    "max_tool_calls": 30,
                },
                "sources": {"source_kind": "runtime_default"},
            },
            reply_route={"type": "none"},
        )
        runtime.database.execute(
            """
            insert into agent_job_execution_summary
              (job_id, accounting_status, model_usage_json, execution_status,
               source_protocol_version, created_at, updated_at)
            values (?, 'COMPLETE', ?, 'SUCCEEDED', '1.2', ?, ?)
            """,
            (
                job.id,
                '[{"model_id":"postgres-query-model"}]',
                "2026-08-16T00:00:00+00:00",
                "2026-08-16T00:00:00+00:00",
            ),
        )

        items = AdminReadRepository(runtime.database).query_jobs(
            AdminJobQuery(
                start="2000-01-01T00:00:00+00:00",
                end="2100-01-01T00:00:00+00:00",
                scope=AdminScope(
                    {
                        "mode": "restricted",
                        "grants": [
                            {
                                "effect": "allow",
                                "environment": "prod",
                                "base": "postgres-base",
                                "workshop": "*",
                            }
                        ],
                    },
                    "postgres-query-viewer",
                ),
                correlation_id="postgres-admin-query",
                execution_statuses=("SUCCEEDED",),
                model="postgres-query-model",
                limit=1,
            )
        )

        assert [item["id"] for item in items] == [job.id]
    finally:
        runtime.database.close()


@pytest.fixture
def postgres_database_dsn() -> str:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    database_name = f"migration_test_{uuid.uuid4().hex}"
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(database_name)))
    parameters = conninfo_to_dict(POSTGRES_DSN)
    parameters["dbname"] = database_name
    test_dsn = make_conninfo(**parameters)
    try:
        yield test_dsn
    finally:
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(
                """
                select pg_terminate_backend(pid)
                  from pg_stat_activity
                 where datname = %s and pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(sql.SQL("drop database {}").format(sql.Identifier(database_name)))


def _write(
    directory: Path,
    name: str,
    sql: str,
) -> None:
    (directory / name).write_text(sql.strip() + "\n", encoding="utf-8")


def _baseline_only_migrations(tmp_path: Path) -> Path:
    source = default_migrations_dir()
    target = tmp_path / "postgres-baseline-only"
    target.mkdir()
    (target / "100_baseline_v1.sql").write_bytes((source / "100_baseline_v1.sql").read_bytes())
    (target / LEGACY_MANIFEST_FILENAME).write_bytes(
        (source / LEGACY_MANIFEST_FILENAME).read_bytes()
    )
    return target


def _convert_postgres_baseline_to_legacy_ledger(database: Database) -> None:
    manifest = load_legacy_manifest(default_migrations_dir() / LEGACY_MANIFEST_FILENAME)
    with database.unit_of_work():
        database.execute("delete from schema_migration")
        database.execute("delete from schema_baseline_adoption")
        for artifact in manifest["catalog"]:
            database.execute(
                """
                insert into schema_migration
                  (version, name, checksum, applied_at, duration_ms, migrator_build)
                values (?, ?, ?, '2026-08-11T00:00:00Z', 0, 'legacy-fixture')
                """,
                (
                    artifact["version"],
                    artifact["name"],
                    artifact["checksum"],
                ),
            )


def test_postgres_baseline_100_fresh_schema_and_comments(
    postgres_database_dsn: str,
) -> None:
    database = Database(postgres_database_dsn)
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-baseline-fresh-test",
        ).run()
        comments = postgres_comment_snapshot(database)

        assert result.head == "115"
        assert result.applied == (
            "100",
            "101",
            "102",
            "103",
            "104",
            "105",
            "106",
            "107",
            "108",
            "109",
            "110",
            "111",
            "112",
            "113",
            "114",
            "115",
        )
        assert database.execute_one(
            """
            select count(*)::int as count
              from information_schema.tables
             where table_schema = 'public'
               and table_type = 'BASE TABLE'
               and table_name not in ('schema_migration', 'schema_baseline_adoption')
            """
        ) == {"count": 112}
        assert comments["table_count"] == 112
        assert comments["column_count"] == 1428
    finally:
        database.close()


def test_postgres_explicit_fresh_contract_schema_and_comments(
    postgres_database_dsn: str,
) -> None:
    database = Database(postgres_database_dsn)
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-explicit-contract-test",
            include_schema_contract=True,
        ).run()
        comments = postgres_comment_snapshot(database)

        assert result.head == "115"
        assert result.applied == (
            "100",
            "101",
            "102",
            "103",
            "104",
            "105",
            "106",
            "107",
            "108",
            "109",
            "110",
            "111",
            "112",
            "113",
            "114",
            "115",
        )
        assert comments["table_count"] == 112
        assert comments["column_count"] == 1428
        assert {
            "dingding_conversation_id",
            "dingding_user_id",
            "source",
        }.isdisjoint(
            {
                row["column_name"]
                for row in database.execute(
                    """
                    select column_name
                      from information_schema.columns
                     where table_schema = 'public' and table_name = 'agent_session'
                    """
                )
            }
        )
    finally:
        database.close()


def test_postgres_concurrent_baseline_migrators_apply_100_once(
    postgres_database_dsn: str,
) -> None:
    def run(build: str):
        database = Database(postgres_database_dsn)
        try:
            return Migrator(
                database,
                default_migrations_dir(),
                migrator_build=build,
            ).run()
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, ("baseline-build-a", "baseline-build-b")))

    assert sorted(result.applied for result in results) == [
        (),
        ("100", "101", "102", "103", "104", "105", "106"),
    ]
    database = Database(postgres_database_dsn)
    try:
        assert [row["version"] for row in SchemaMigrationLedger(database).read_records()] == [
            "100",
            "101",
            "102",
            "103",
            "104",
            "105",
            "106",
        ]
    finally:
        database.close()


def test_postgres_agent_run_audit_precision_constraints_and_cascade(
    postgres_database_dsn: str,
) -> None:
    database = Database(postgres_database_dsn)
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-agent-run-audit-test",
        ).run()
        timestamp = "2026-08-12T00:00:00+00:00"
        database.execute(
            """
            insert into agent_session
              (id, project_code, created_at, updated_at, source_channel,
               source_connector_id, external_conversation_id, requester_id, session_key)
            values ('postgres-audit-session', 'default', ?, ?, 'test',
                    'connector-test', 'audit-conversation', 'audit-user',
                    'postgres-audit-session')
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into agent_job
              (id, session_id, idempotency_key, project_code, status, created_at,
               source_channel, source_connector_id, requester_id,
               agent_runtime_protocol_version)
            values ('postgres-audit-job', 'postgres-audit-session',
                    'postgres-audit-job', 'default', 'SUCCEEDED', ?, 'test',
                    'connector-test', 'audit-user', '1.3')
            """,
            (timestamp,),
        )
        repository = ExecutionAuditRepository(database)
        digest = "a" * 64
        model_event = {
            "protocol_version": "1.3",
            "invocation_id": "postgres-invocation",
            "request_digest": digest,
            "sequence": 1,
            "event_type": "model_call",
            "timestamp": timestamp,
            "payload": {
                "model_call_id": "postgres-model-call",
                "provider_request_id": None,
                "provider_message_id": "postgres-message",
                "model_id": "claude-safe-model",
                "status": "SUCCEEDED",
                "started_at": None,
                "completed_at": timestamp,
                "duration_ms": None,
                "duration_source": "UNAVAILABLE",
                "usage": {
                    "input_tokens": 9_000_000_000,
                    "output_tokens": 4_000_000_000,
                    "cache_creation_input_tokens": None,
                    "cache_read_input_tokens": None,
                },
                "stop_reason": "end_turn",
                "error_code": None,
                "error_summary": None,
            },
        }
        second_model_event = {
            **model_event,
            "sequence": 2,
            "payload": {
                **model_event["payload"],
                "model_call_id": "postgres-model-call-2",
                "provider_message_id": "postgres-message-2",
            },
        }
        terminal = {
            "protocol_version": "1.3",
            "invocation_id": "postgres-invocation",
            "request_digest": digest,
            "sequence": 3,
            "event_type": "terminal",
            "timestamp": timestamp,
            "payload": {
                "protocol_version": "1.3",
                "invocation_id": "postgres-invocation",
                "request_digest": digest,
                "last_sequence": 3,
                "status": "SUCCEEDED",
                "final_answer": "must-not-enter-audit-event",
                "usage": {
                    "input_tokens": 9_000_000_000,
                    "output_tokens": 4_000_000_000,
                    "cache_creation_input_tokens": None,
                    "cache_read_input_tokens": None,
                },
                "accounting": {
                    "status": "COMPLETE",
                    "duration_ms": 1,
                    "duration_api_ms": None,
                    "num_turns": 1,
                    "usage": {
                        "input_tokens": 9_000_000_000,
                        "output_tokens": 4_000_000_000,
                        "cache_creation_input_tokens": None,
                        "cache_read_input_tokens": None,
                    },
                    "model_usage": [],
                    "estimated_cost_usd": 0.123456789012,
                    "permission_denials_count": 0,
                },
                "runtime_provenance": {
                    "runtime_kind": "typescript-v1",
                    "runtime_version": "0.1.0",
                    "protocol_version": "1.2",
                    "sdk_version": "0.3.226",
                    "cli_version": "2.1.226",
                    "model_connection_revision_id": "revision-1",
                    "model_connection_config_hash": "b" * 64,
                },
            },
        }
        repository.record_runtime_event("postgres-audit-job", model_event)
        repository.record_runtime_event("postgres-audit-job", second_model_event)
        repository.record_runtime_event("postgres-audit-job", terminal)
        summary = repository.rebuild_summary("postgres-audit-job")
        first_page = repository.list_model_calls("postgres-audit-job", limit=1)
        second_page = repository.list_model_calls(
            "postgres-audit-job", limit=1, cursor=first_page["next_cursor"]
        )

        assert summary["input_tokens"] == 9_000_000_000
        assert summary["estimated_cost_usd"] == "0.123456789012"
        assert first_page["has_more"] is True
        assert first_page["items"][0]["runtime_sequence"] == 1
        assert second_page["has_more"] is False
        assert second_page["items"][0]["runtime_sequence"] == 2
        serialized = str(AgentRepository(database).list_runtime_events("postgres-audit-job"))
        assert "must-not-enter-audit-event" not in serialized

        database.execute("delete from agent_runtime_event where job_id = 'postgres-audit-job'")
        database.execute("delete from agent_job where id = 'postgres-audit-job'")
        assert database.execute_one("select count(*)::int as count from agent_model_call") == {
            "count": 0
        }
        assert database.execute_one(
            "select count(*)::int as count from agent_job_execution_summary"
        ) == {"count": 0}
    finally:
        database.close()


def test_postgres_exact_042_adoption_preserves_retained_data(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    database = Database(postgres_database_dsn)
    try:
        Migrator(
            database,
            migrations,
            migrator_build="postgres-adoption-fixture",
        ).run()
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('postgres-adoption-user', 'postgres-adoption-user',
                    'Postgres Adoption User', 'enabled', ?, ?)
            """,
            ("2026-08-11T00:00:00Z", "2026-08-11T00:00:00Z"),
        )
        _convert_postgres_baseline_to_legacy_ledger(database)

        result = Migrator(
            database,
            migrations,
            migrator_build="postgres-adoption-test",
        ).run()

        assert result.baselined == 1
        assert result.applied == ()
        assert database.execute_one(
            "select username from app_user where id = 'postgres-adoption-user'"
        ) == {"username": "postgres-adoption-user"}
        assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "100"
        assert len(SchemaMigrationLedger(database).read_adoptions()) == 1
    finally:
        database.close()


def test_postgres_baseline_adoption_operational_verification_and_rollback(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    database = Database(postgres_database_dsn)
    try:
        Migrator(
            database,
            migrations,
            migrator_build="postgres-adoption-fixture",
        ).run()
        PlatformConfigRepository(database).upsert_runtime_config_definition(
            key="POSTGRES_ADOPTION_CONFIG",
            value_type="string",
            default="safe-default",
        )
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('postgres-adoption-user', 'postgres-adoption-user',
                    'Postgres Adoption User', 'enabled', ?, ?)
            """,
            ("2026-08-11T00:00:00Z", "2026-08-11T00:00:00Z"),
        )
        _convert_postgres_baseline_to_legacy_ledger(database)
        before_records = SchemaMigrationLedger(database).read_records()

        preflight = BaselineAdoptionInspector(
            database,
            migrations,
        ).preflight(migrator_build="build-2026.08.11")

        assert preflight["status"] == "ready-for-adoption"
        assert preflight["runtime_config_summary"]["revision"] == 1
        assert SchemaMigrationLedger(database).read_records() == before_records
        assert SchemaMigrationLedger(database).read_adoptions() == []

        adopted = Migrator(
            database,
            migrations,
            migrator_build="build-2026.08.11",
        ).run()
        repeated = Migrator(
            database,
            migrations,
            migrator_build="build-2026.08.11",
        ).run()
        verified = BaselineAdoptionInspector(
            database,
            migrations,
        ).verify(expected_migrator_build="build-2026.08.11")

        assert adopted.baselined == 1
        assert repeated.baselined == 0
        assert repeated.applied == ()
        assert verified["status"] == "adoption-verified"
        assert verified["runtime_config_summary"]["revision"] == 1
        assert verified["retained_data_counts"]["app_user"] == 1

        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('acceptance-failure-user', 'acceptance-failure-user',
                    'Acceptance Failure', 'enabled', ?, ?)
            """,
            ("2026-08-11T00:00:00Z", "2026-08-11T00:00:00Z"),
        )
        with pytest.raises(MigrationDefinitionError, match="counts changed"):
            BaselineAdoptionInspector(
                database,
                migrations,
            ).verify(expected_migrator_build="build-2026.08.11")

        assert (
            BaselineAdoptionRollback(
                database,
                migrations,
                migrator_build="rollback-test",
            ).run()
            == "042"
        )
        assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "042"
        assert SchemaMigrationLedger(database).read_adoptions() == []
    finally:
        database.close()


def test_postgres_concurrent_runtime_config_reconciliation_counts_change_once(
    postgres_database_dsn: str,
) -> None:
    database = Database(postgres_database_dsn)
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-runtime-config-fixture",
        ).run()
    finally:
        database.close()

    def reconcile(description: str, barrier: threading.Barrier):
        worker_database = Database(postgres_database_dsn)
        try:
            barrier.wait(timeout=10)
            return PlatformConfigRepository(worker_database).upsert_runtime_config_definition(
                key="CONCURRENT_POSTGRES_CONFIG",
                value_type="string",
                default={"stable": True},
                service_names=["worker-b", "worker-a", "worker-b"],
                description=description,
            )
        finally:
            worker_database.close()

    create_barrier = threading.Barrier(8)
    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(lambda _: reconcile("initial", create_barrier), range(8)))
    assert [result.outcome for result in created].count("created") == 1
    assert [result.outcome for result in created].count("unchanged") == 7

    update_barrier = threading.Barrier(8)
    with ThreadPoolExecutor(max_workers=8) as executor:
        updated = list(executor.map(lambda _: reconcile("changed", update_barrier), range(8)))
    assert [result.outcome for result in updated].count("updated") == 1
    assert [result.outcome for result in updated].count("unchanged") == 7

    database = Database(postgres_database_dsn)
    try:
        stored = PlatformConfigRepository(database).get_runtime_config_definition(
            "CONCURRENT_POSTGRES_CONFIG"
        )
        assert stored is not None
        assert stored["description"] == "changed"
        assert stored["service_names"] == ["worker-a", "worker-b"]
        assert stored["revision"] == 2
    finally:
        database.close()


def test_postgres_runtime_config_reads_and_reconciliation_are_write_free(
    postgres_database_dsn: str,
) -> None:
    database = Database(postgres_database_dsn)
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-runtime-read-fixture",
        ).run()
        repository = PlatformConfigRepository(database)
        registry = RuntimeConfigRegistry(repository)
        builder = RuntimeConfigSnapshotBuilder(repository)
        first_sync = registry.ensure_builtin_definitions()
        before_definitions = repository.list_runtime_config_definitions()
        before_revision = repository.runtime_config_revision()
        before_audit = repository.list_config_audit(limit=500)

        repeated_sync = registry.ensure_builtin_definitions()
        first_snapshot = builder.build_snapshot(service_name="api-server")
        second_snapshot = builder.build_snapshot(service_name="api-server")

        assert first_sync["created"] == len(before_definitions)
        assert repeated_sync == {
            "created": 0,
            "updated": 0,
            "unchanged": len(before_definitions),
        }
        assert repository.list_runtime_config_definitions() == before_definitions
        assert repository.runtime_config_revision() == before_revision
        assert repository.list_config_audit(limit=500) == before_audit
        assert first_snapshot["revision"] == second_snapshot["revision"] == before_revision
        assert first_snapshot["config_hash"] == second_snapshot["config_hash"]
        assert first_snapshot["errors"] == second_snapshot["errors"] == []
    finally:
        database.close()


def test_postgres_legacy_comment_drift_rejects_adoption(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    database = Database(postgres_database_dsn)
    try:
        Migrator(
            database,
            migrations,
            migrator_build="postgres-comment-drift-fixture",
        ).run()
        _convert_postgres_baseline_to_legacy_ledger(database)
        database.execute("comment on table app_user is 'drifted comment'")

        with pytest.raises(MigrationDefinitionError, match="comments"):
            Migrator(
                database,
                migrations,
                migrator_build="postgres-comment-drift-test",
            ).run()
        assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "042"
        assert SchemaMigrationLedger(database).read_adoptions() == []
    finally:
        database.close()


def test_postgres_concurrent_migrators_serialize_on_advisory_lock(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "001_lock_probe.sql",
        """
        select pg_sleep(0.25);
        create table lock_probe (id integer primary key);
        """,
    )

    def run(build: str):
        database = Database(postgres_database_dsn)
        try:
            return Migrator(
                database,
                tmp_path,
                migrator_build=build,
            ).run()
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, ("build-a", "build-b")))

    assert sorted(result.applied for result in results) == [(), ("001",)]
    database = Database(postgres_database_dsn)
    try:
        assert database.execute_one("select count(*) as count from lock_probe") == {"count": 0}
        assert len(SchemaMigrationLedger(database).list_records()) == 1
    finally:
        database.close()


def test_postgres_checksum_drift_stops_before_later_migration(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    first = tmp_path / "001_first.sql"
    _write(tmp_path, first.name, "create table first_table (id integer primary key);")
    database = Database(postgres_database_dsn)
    try:
        Migrator(database, tmp_path, migrator_build="build-a").run()
        _write(
            tmp_path,
            first.name,
            "create table first_table (id integer primary key, changed text);",
        )
        _write(
            tmp_path,
            "002_must_not_apply.sql",
            "create table must_not_apply (id integer primary key);",
        )

        with pytest.raises(MigrationDefinitionError, match="checksum"):
            Migrator(database, tmp_path, migrator_build="build-b").run()

        assert database.execute_one("select to_regclass('public.must_not_apply') as relation") == {
            "relation": None
        }
    finally:
        database.close()


def test_postgres_duplicate_version_is_rejected_before_ledger_creation(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    _write(tmp_path, "001_first.sql", "select 1;")
    _write(tmp_path, "001_second.sql", "select 2;")
    database = Database(postgres_database_dsn)
    try:
        with pytest.raises(MigrationDefinitionError, match="Duplicate"):
            Migrator(database, tmp_path, migrator_build="build-a").run()

        assert database.execute_one(
            "select to_regclass('public.schema_migration') as relation"
        ) == {"relation": None}
    finally:
        database.close()


def test_postgres_failed_version_rolls_back_schema_and_ledger_and_reruns(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "001_first.sql",
        "create table first_table (id integer primary key);",
    )
    _write(
        tmp_path,
        "002_broken.sql",
        """
        create table must_rollback (id integer primary key);
        insert into table_that_does_not_exist (id) values (1);
        """,
    )
    database = Database(postgres_database_dsn)
    try:
        with pytest.raises(MigrationExecutionError, match="002 failed"):
            Migrator(database, tmp_path, migrator_build="build-a").run()

        assert database.execute_one("select to_regclass('public.must_rollback') as relation") == {
            "relation": None
        }
        assert [row["version"] for row in SchemaMigrationLedger(database).list_records()] == ["001"]

        _write(
            tmp_path,
            "002_broken.sql",
            "create table recovered_table (id integer primary key);",
        )
        recovered = Migrator(
            database,
            tmp_path,
            migrator_build="build-b",
        ).run()
        repeated = Migrator(
            database,
            tmp_path,
            migrator_build="build-c",
        ).run()

        assert recovered.applied == ("002",)
        assert repeated.applied == ()
        assert database.execute_one("select to_regclass('public.recovered_table') as relation") == {
            "relation": "recovered_table"
        }
    finally:
        database.close()


def test_postgres_operation_uows_isolate_concurrent_commit_and_rollback(
    postgres_database_dsn: str,
) -> None:
    database = Database(
        postgres_database_dsn,
        pool_min_size=0,
        pool_max_size=4,
    )
    barrier = threading.Barrier(2)
    try:
        database.execute("create table operation_probe (id integer primary key, value text)")

        def run(identifier: int, *, fail: bool) -> tuple[int, str]:
            try:
                with database.unit_of_work():
                    database.execute(
                        "insert into operation_probe (id, value) values (?, ?)",
                        (identifier, f"value-{identifier}"),
                    )
                    barrier.wait(timeout=5)
                    visible = database.execute_one("select count(*) as count from operation_probe")
                    barrier.wait(timeout=5)
                    if fail:
                        raise RuntimeError("rollback this operation")
                    return int(visible["count"]), "committed"
            except RuntimeError:
                return int(visible["count"]), "rolled-back"

        with ThreadPoolExecutor(max_workers=2) as executor:
            committed = executor.submit(run, 1, fail=False)
            rolled_back = executor.submit(run, 2, fail=True)
            results = sorted((committed.result(), rolled_back.result()))

        assert results == [(1, "committed"), (1, "rolled-back")]
        assert database.execute("select id, value from operation_probe order by id") == [
            {"id": 1, "value": "value-1"}
        ]
        assert database.pool_snapshot().checked_out == 0
    finally:
        database.close()


def test_postgres_concurrent_same_name_mcp_calls_keep_exact_links(
    postgres_database_dsn: str,
) -> None:
    database = Database(
        postgres_database_dsn,
        pool_min_size=0,
        pool_max_size=8,
    )
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-mcp-audit-concurrency-test",
        ).run()
        timestamp = "2026-08-12T00:00:00+00:00"
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('mcp-concurrent-user', 'mcp-concurrent-user',
                    'MCP Concurrent User', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        repository = AgentRepository(database)
        session = repository.create_session(
            project_code="default",
            source_channel="test",
            source_connector_id="connector-test",
            external_conversation_id="mcp-audit-concurrent",
            requester_id="mcp-concurrent-user",
            session_key=f"mcp-audit-concurrent-{uuid.uuid4().hex}",
            reply_route={"type": "test"},
        )
        job = repository.create_job(
            session_id=session.id,
            idempotency_key=f"mcp-audit-concurrent-{uuid.uuid4().hex}",
            project_code="default",
            source_channel="test",
            source_connector_id="connector-test",
            requester_id="mcp-concurrent-user",
            input_message="query order",
            max_retry_count=0,
            execution_policy={
                "schema_version": 1,
                "requested": {"max_turns": 1, "timeout_seconds": 30, "max_tool_calls": 2},
                "effective": {"max_turns": 1, "timeout_seconds": 30, "max_tool_calls": 2},
                "sources": {"source_kind": "runtime_default"},
            },
        )
        coordinator = McpAuditCoordinator(database, max_payload_bytes=64 * 1024)
        barrier = threading.Barrier(2)

        def invoke(index: int):
            barrier.wait(timeout=5)
            handle = coordinator.begin(
                McpAuditContext(
                    correlation_id=f"mcp-concurrent-{index}",
                    job_id=job.id,
                    session_id=session.id,
                    invocation_id=f"{job.id}.attempt-0",
                    actor_user_id="mcp-concurrent-user",
                    server_code="tool-mcp",
                    tool_identifier="get_er_context",
                ),
                business_request={"query": f"order-{index}"},
            )
            coordinator.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision="ALLOW",
                authorization_reason="test_allow",
            )
            coordinator.complete(
                handle,
                status="SUCCEEDED",
                business_response={"index": index},
                duration_ms=1,
            )
            return handle

        with ThreadPoolExecutor(max_workers=2) as executor:
            handles = list(executor.map(invoke, range(2)))

        assert len({handle.mcp_call_id for handle in handles}) == 2
        assert len({handle.agent_tool_call_id for handle in handles}) == 2
        rows = database.execute(
            """
            select mcp_call_id, agent_tool_call_id, event_kind, status
              from mcp_operation_audit
             where job_id = ?
             order by mcp_call_id, event_kind
            """,
            (job.id,),
        )
        assert len(rows) == 4
        for handle in handles:
            linked = [row for row in rows if row["mcp_call_id"] == handle.mcp_call_id]
            assert {row["event_kind"] for row in linked} == {"TOOL", "AUTHORIZATION"}
            assert {row["agent_tool_call_id"] for row in linked} == {handle.agent_tool_call_id}
            assert {row["status"] for row in linked} == {"SUCCEEDED"}
    finally:
        database.close()


def test_postgres_job_dispatchers_use_skip_locked_without_duplicate_claims(
    postgres_database_dsn: str,
) -> None:
    database = Database(
        postgres_database_dsn,
        pool_min_size=0,
        pool_max_size=8,
    )
    published: list[tuple[str, str, str]] = []
    publish_lock = threading.Lock()

    class CapturePublisher:
        def publish_agent_job(
            self,
            event_id: str,
            job_id: str,
            correlation_id: str,
        ) -> None:
            with publish_lock:
                published.append((event_id, job_id, correlation_id))

    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-job-dispatch-test",
        ).run()
        repository = AgentRepository(database)
        audit = AuditService(AuditRepository(database))
        timestamp = "2026-07-28T00:00:00+00:00"
        database.execute(
            """
            insert into agent_session
              (id, project_code, created_at, updated_at, source_channel,
               source_connector_id, external_conversation_id, requester_id,
               session_key)
            values ('session-dispatch-concurrency', 'default', ?, ?, 'test',
                    'connector-test', 'conversation', 'user',
                    'session-dispatch-concurrency')
            """,
            (timestamp, timestamp),
        )
        for index in range(40):
            job_id = f"job-dispatch-concurrency-{index}"
            database.execute(
                """
                insert into agent_job
                  (id, session_id, idempotency_key, project_code, status,
                   created_at, source_channel, source_connector_id, requester_id)
                values (?, 'session-dispatch-concurrency', ?, 'default',
                        'PENDING', ?, 'test', 'connector-test', 'user')
                """,
                (job_id, f"dispatch-concurrency-{index}", timestamp),
            )
            repository.create_dispatch_event(
                job_id=job_id,
                job_idempotency_key=f"dispatch-concurrency-{index}",
                correlation_id=f"correlation-{index}",
            )
        dispatchers = [
            JobDispatchOutboxDispatcher(
                repository=repository,
                publisher=CapturePublisher(),
                audit_service=audit,
                settings=QueueSettings(),
                worker_id=f"postgres-dispatcher-{index}",
            )
            for index in range(2)
        ]

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(
                executor.map(
                    lambda dispatcher: dispatcher.publish_pending(limit=40),
                    dispatchers,
                )
            )

        assert len(published) == 40
        assert len({event_id for event_id, _, _ in published}) == 40
        assert database.execute_one(
            """
            select count(*) as count
              from job_dispatch_outbox
             where status = 'PUBLISHED'
            """
        ) == {"count": 40}
    finally:
        database.close()


def test_postgres_delivery_dispatchers_use_skip_locked_without_duplicate_sends(
    postgres_database_dsn: str,
    tmp_path: Path,
) -> None:
    database = Database(
        postgres_database_dsn,
        pool_min_size=0,
        pool_max_size=8,
    )
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="postgres-delivery-dispatch-test",
        ).run()
    finally:
        database.close()

    private_key_path = tmp_path / "runtime-grant-private.pem"
    private_key_path.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_key_path.chmod(0o600)
    settings = Settings(
        database_dsn=postgres_database_dsn,
        feature_real_claude=False,
        delivery=DeliverySettings(outbox_max_attempts=2),
        agent_runtime=AgentRuntimeSettings(
            grant_private_key_file=str(private_key_path),
        ),
        principal_jwt=PrincipalJwtSettings(
            signing_private_key_file=str(private_key_path),
        ),
    )
    runtime = build_worker_container(settings, seed=True)
    sent: list[str] = []
    sent_lock = threading.Lock()

    class CaptureAdapter(DeliveryAdapter):
        def send(
            self,
            *,
            connector: object,
            route: ReplyRoute,
            title: str,
            text: str,
        ) -> None:
            del connector, route, title
            with sent_lock:
                sent.append(text)

    try:
        runtime.result_delivery_service.adapters["postgres_capture"] = CaptureAdapter()
        session = runtime.agent_repository.create_session(
            project_code="default",
            source_channel="test",
            source_connector_id="connector-test",
            external_conversation_id="delivery-concurrency",
            requester_id="delivery-user",
            session_key=f"delivery-concurrency-{uuid.uuid4().hex}",
            reply_route={"type": "postgres_capture", "target": {}},
        )
        jobs = []
        for index in range(40):
            job = runtime.agent_repository.create_job(
                session_id=session.id,
                idempotency_key=f"delivery-concurrency-{uuid.uuid4().hex}",
                project_code="default",
                source_channel="test",
                source_connector_id="connector-test",
                requester_id="delivery-user",
                input_message="diagnose",
                max_retry_count=0,
                initial_status=JobStatus.SUCCEEDED,
                reply_route={"type": "postgres_capture", "target": {}},
                execution_policy={
                    "schema_version": 1,
                    "requested": {
                        "max_turns": 12,
                        "timeout_seconds": 300,
                        "max_tool_calls": 10,
                    },
                    "effective": {
                        "max_turns": 12,
                        "timeout_seconds": 300,
                        "max_tool_calls": 10,
                    },
                    "sources": {"source_kind": "runtime_default"},
                },
            )
            artifact_id = runtime.agent_repository.add_artifact(
                job_id=job.id,
                artifact_type="report",
                name="diagnostic-report.md",
                content=f"delivery-result-{index}",
            )
            runtime.result_delivery_service.enqueue_job_result(
                job_id=job.id,
                artifact_id=artifact_id,
                correlation_id=f"delivery-correlation-{index}",
            )
            jobs.append(job)

        dispatchers = [
            DeliveryOutboxDispatcher(
                repository=runtime.agent_repository,
                delivery_service=runtime.result_delivery_service,
                audit_service=runtime.audit_service,
                settings=runtime.settings.delivery,
                worker_id=f"postgres-delivery-dispatcher-{index}",
            )
            for index in range(2)
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda dispatcher: dispatcher.dispatch_pending(limit=40),
                    dispatchers,
                )
            )

        assert all(result.failed == result.dead == result.retrying == 0 for result in results)
        assert len(sent) == 40
        assert len(set(sent)) == 40
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from delivery_outbox
             where status = 'SUCCEEDED'
            """
        ) == {"count": 40}
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from delivery_attempt
             where status = 'SUCCEEDED'
            """
        ) == {"count": 40}
        assert all(
            runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED for job in jobs
        )
    finally:
        runtime.database.close()
