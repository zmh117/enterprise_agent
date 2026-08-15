from __future__ import annotations

import sqlite3

import pytest

from app.modules.job.domain.job_dispatch import (
    JobDispatchStatus,
    can_transition_dispatch,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, load_migration_catalog
from app.shared.schema_baseline import LEGACY_MANIFEST_FILENAME, load_legacy_manifest


def test_job_dispatch_outbox_migration_has_stable_contract_and_indexes() -> None:
    database = Database("sqlite:///:memory:")
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="job-dispatch-schema-test",
        ).run()

        assert result.head == "107"
        columns = {
            str(row["name"]): row
            for row in database.execute("pragma table_info(job_dispatch_outbox)")
        }
        assert {
            "id",
            "event_key",
            "idempotency_key",
            "job_id",
            "correlation_id",
            "status",
            "attempt_count",
            "max_attempts",
            "replay_count",
            "max_replay_count",
            "next_attempt_at",
            "claimed_by",
            "claimed_at",
            "published_at",
            "dead_at",
            "last_replayed_at",
            "last_replayed_by",
            "last_error_code",
            "last_error_summary",
            "created_at",
            "updated_at",
        } == set(columns)
        assert columns["status"]["dflt_value"] == "'PENDING'"
        assert columns["attempt_count"]["dflt_value"] == "0"
        assert columns["max_attempts"]["dflt_value"] == "8"
        assert columns["replay_count"]["dflt_value"] == "0"
        assert columns["max_replay_count"]["dflt_value"] == "3"

        indexes = {
            str(row["name"]) for row in database.execute("pragma index_list(job_dispatch_outbox)")
        }
        assert {
            "idx_job_dispatch_outbox_due",
            "idx_job_dispatch_outbox_claim",
            "idx_job_dispatch_outbox_job_status",
            "idx_job_dispatch_outbox_audit",
        }.issubset(indexes)
        quarantine_columns = {
            str(row["name"])
            for row in database.execute("pragma table_info(job_dispatch_cutover_quarantine)")
        }
        assert quarantine_columns == {
            "id",
            "source_queue",
            "message_digest",
            "job_id",
            "reason_code",
            "observed_at",
            "observed_by",
        }
    finally:
        database.close()


def test_job_dispatch_outbox_rejects_invalid_status_and_attempt_bounds() -> None:
    database = Database("sqlite:///:memory:")
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="job-dispatch-schema-test",
        ).run()
        timestamp = "2026-07-29T00:00:00+00:00"
        database.execute(
            """
            insert into agent_session
              (id, project_code, created_at, updated_at, source_channel,
               source_connector_id, external_conversation_id, requester_id,
               session_key)
            values ('session-outbox', 'default', ?, ?, 'test',
                    'connector-test', 'conversation', 'user', 'session-outbox')
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into agent_job
              (id, session_id, idempotency_key, project_code, source_channel,
               source_connector_id, requester_id, status, created_at)
            values ('job-outbox', 'session-outbox', 'job-key', 'default',
                    'test', 'connector-test', 'user', 'PENDING', ?)
            """,
            (timestamp,),
        )

        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                insert into job_dispatch_outbox
                  (id, event_key, idempotency_key, job_id, correlation_id,
                   status, attempt_count, max_attempts, next_attempt_at,
                   created_at, updated_at)
                values ('event-invalid-status', 'event-key-1', 'dispatch-key-1',
                        'job-outbox', 'correlation', 'UNKNOWN', 0, 8, ?, ?, ?)
                """,
                (timestamp, timestamp, timestamp),
            )

        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                insert into job_dispatch_outbox
                  (id, event_key, idempotency_key, job_id, correlation_id,
                   status, attempt_count, max_attempts, next_attempt_at,
                   created_at, updated_at)
                values ('event-invalid-attempt', 'event-key-2', 'dispatch-key-2',
                        'job-outbox', 'correlation', 'PENDING', 2, 1, ?, ?, ?)
                """,
                (timestamp, timestamp, timestamp),
            )
    finally:
        database.close()


def test_job_dispatch_status_is_finite_and_terminal_states_do_not_transition() -> None:
    assert {status.value for status in JobDispatchStatus} == {
        "PENDING",
        "RUNNING",
        "RETRY_WAIT",
        "PUBLISHED",
        "DEAD",
    }
    assert can_transition_dispatch(
        JobDispatchStatus.PENDING,
        JobDispatchStatus.RUNNING,
    )
    assert can_transition_dispatch(
        JobDispatchStatus.RUNNING,
        JobDispatchStatus.RETRY_WAIT,
    )
    assert not can_transition_dispatch(
        JobDispatchStatus.PUBLISHED,
        JobDispatchStatus.RUNNING,
    )
    assert not can_transition_dispatch(
        JobDispatchStatus.DEAD,
        JobDispatchStatus.RUNNING,
    )


def test_job_dispatch_legacy_evidence_is_frozen_but_active_catalog_is_current() -> None:
    catalog = load_migration_catalog(default_migrations_dir())
    manifest = load_legacy_manifest(default_migrations_dir() / LEGACY_MANIFEST_FILENAME)
    job_dispatch = next(
        artifact for artifact in manifest["catalog"] if artifact["version"] == "019"
    )

    assert catalog[-1].version == "107"
    assert job_dispatch["name"] == "019_job_dispatch_outbox.sql"
