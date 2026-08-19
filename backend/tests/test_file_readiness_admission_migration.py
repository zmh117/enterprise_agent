from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.schema_baseline import LEGACY_MANIFEST_FILENAME


TIMESTAMP = "2026-08-18T00:00:00+00:00"


def _catalog_through(tmp_path: Path, head: int) -> Path:
    source = default_migrations_dir()
    target = tmp_path / f"migrations-through-{head}"
    target.mkdir()
    shutil.copy2(source / LEGACY_MANIFEST_FILENAME, target / LEGACY_MANIFEST_FILENAME)
    for path in source.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= head:
            shutil.copy2(path, target / path.name)
    return target


def _seed_delivery_row(database: Database) -> None:
    database.execute(
        """
        insert into agent_session
          (id, source_channel, source_connector_id, external_conversation_id,
           requester_id, project_code, session_key, created_at, updated_at)
        values ('session-notice', 'dingding_stream', 'connector-a', 'conversation-a',
                'user-a', 'default', 'direct:user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id)
        values ('job-notice', 'session-notice', 'job-notice-key', 'SUCCEEDED', ?,
                'dingding_stream', 'connector-a', 'user-a')
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into agent_artifact
          (id, job_id, artifact_type, name, content, created_at)
        values ('artifact-notice', 'job-notice', 'report', 'report.md', 'ok', ?)
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into delivery_outbox
          (id, event_key, job_id, result_artifact_id, delivery_binding_json,
           correlation_id, status, max_attempts, next_attempt_at, created_at, updated_at)
        values ('delivery-existing', 'delivery.result:artifact-notice', 'job-notice',
                'artifact-notice', '{"delivery_kind":"result"}', 'corr-a', 'SUCCEEDED',
                8, ?, ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )


def test_file_turn_admission_expand_schema() -> None:
    database = Database("sqlite:///:memory:")
    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="file-turn-admission-schema-test",
    ).run()
    assert result.head == "115"
    tables = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'table'")
    }
    assert {
        "file_readiness_blocked_turn",
        "file_readiness_blocked_turn_version",
    } <= tables
    message_columns = {
        str(row["name"]) for row in database.execute("pragma table_info(agent_message)")
    }
    assert "quoted_external_message_id" in message_columns
    outbox = {
        str(row["name"]): row
        for row in database.execute("pragma table_info(delivery_outbox)")
    }
    assert int(outbox["job_id"]["notnull"]) == 0
    assert int(outbox["result_artifact_id"]["notnull"]) == 0
    attempt = {
        str(row["name"]): row
        for row in database.execute("pragma table_info(delivery_attempt)")
    }
    assert int(attempt["job_id"]["notnull"]) == 0
    sql = database.execute_one(
        "select sql from sqlite_master where type = 'table' and name = 'delivery_outbox'"
    )
    assert sql is not None
    assert "SYSTEM_NOTICE" in str(sql["sql"])


def test_system_notice_insert_requires_session_and_null_job(tmp_path: Path) -> None:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="file-turn-admission-insert-test",
    ).run()
    _seed_delivery_row(database)
    database.execute(
        """
        insert into delivery_outbox
          (id, event_key, job_id, result_artifact_id, delivery_binding_json,
           correlation_id, status, max_attempts, next_attempt_at, created_at,
           updated_at, delivery_kind, session_id)
        values ('delivery-notice', 'delivery.system_notice:key-a', null, null,
                '{"delivery_kind":"system_notice","markdown":"文件尚未可阅读"}',
                'corr-notice', 'PENDING', 8, ?, ?, ?, 'SYSTEM_NOTICE', 'session-notice')
        """,
        (TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    row = database.execute_one(
        "select job_id, result_artifact_id, delivery_kind, session_id from delivery_outbox where id = 'delivery-notice'"
    )
    assert row == {
        "job_id": None,
        "result_artifact_id": None,
        "delivery_kind": "SYSTEM_NOTICE",
        "session_id": "session-notice",
    }
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into delivery_outbox
              (id, event_key, job_id, result_artifact_id, delivery_binding_json,
               correlation_id, status, max_attempts, next_attempt_at, created_at,
               updated_at, delivery_kind, session_id)
            values ('delivery-bad', 'delivery.system_notice:key-b', null, null,
                    '{}', 'corr-bad', 'PENDING', 8, ?, ?, ?, 'SYSTEM_NOTICE', '')
            """,
            (TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )


def test_upgrade_from_114_preserves_existing_delivery_rows(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'upgrade.db'}")
    Migrator(
        database,
        _catalog_through(tmp_path, 114),
        migrator_build="file-turn-admission-before",
    ).run()
    _seed_delivery_row(database)
    upgraded = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="file-turn-admission-after",
    ).run()
    assert upgraded.applied == ("115",)
    existing = database.execute_one(
        "select job_id, result_artifact_id, delivery_kind from delivery_outbox where id = 'delivery-existing'"
    )
    assert existing == {
        "job_id": "job-notice",
        "result_artifact_id": "artifact-notice",
        "delivery_kind": "RESULT",
    }
    quoted = {
        str(row["name"]) for row in database.execute("pragma table_info(agent_message)")
    }
    assert "quoted_external_message_id" in quoted
