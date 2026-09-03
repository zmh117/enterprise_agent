from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from app.modules.agent.application.runtime_v14_cutover import (
    RuntimeV14CutoverPreflight,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, SchemaHeadError
from app.shared.schema_baseline import LEGACY_MANIFEST_FILENAME


TIMESTAMP = "2026-08-25T00:00:00+00:00"


def _queue_facts(*, messages: int = 0, consumers: int = 0) -> dict[str, dict[str, object]]:
    return {
        label: {"exists": True, "messages": messages, "consumers": consumers}
        for label in ("job_queue", "retry_queue", "legacy_retry_queue", "dead_queue")
    }


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'runtime-v14-preflight.db'}")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="runtime-v14-preflight-test",
    ).run()
    return database


def _insert_v13_job(database: Database, *, status: str) -> None:
    database.execute(
        """
        insert into agent_session
          (id, source_channel, source_connector_id, external_conversation_id,
           requester_id, project_code, session_key, created_at, updated_at)
        values ('runtime-v14-session', 'test', 'connector-test', 'conversation-test',
                'user-test', 'default', 'runtime-v14-session', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at, source_channel,
           source_connector_id, requester_id, agent_runtime_protocol_version)
        values ('runtime-v14-job', 'runtime-v14-session', 'runtime-v14-job', ?, ?,
                'test', 'connector-test', 'user-test', '1.3')
        """,
        (status, TIMESTAMP),
    )


def test_runtime_v14_cutover_preflight_is_ready_only_for_drained_facts(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        report = RuntimeV14CutoverPreflight(database).run(_queue_facts())
    finally:
        database.close()

    assert report == {
        "mode": "read-only",
        "target_protocol_version": "1.4",
        "schema_head": "129",
        "database": {
            "protocol_v13_nonterminal_jobs": 0,
            "protocol_v13_dispatch_outbox_nonterminal": 0,
            "protocol_v13_delivery_outbox_nonterminal": 0,
        },
        "queues": {
            label: {"exists": True, "messages": 0, "consumers": 0}
            for label in ("job_queue", "retry_queue", "legacy_retry_queue", "dead_queue")
        },
        "status": "ready",
    }


def test_runtime_v14_cutover_preflight_blocks_v13_job_outboxes_and_queue_facts(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        _insert_v13_job(database, status="RUNNING")
        database.execute(
            """
            insert into job_dispatch_outbox
              (id, event_key, idempotency_key, job_id, correlation_id, status,
               next_attempt_at, created_at, updated_at)
            values ('dispatch-v13', 'dispatch-v13', 'dispatch-v13', 'runtime-v14-job',
                    'correlation-v13', 'PENDING', ?, ?, ?)
            """,
            (TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        database.execute(
            """
            insert into agent_artifact
              (id, job_id, artifact_type, name, content, created_at)
            values ('artifact-v13', 'runtime-v14-job', 'report', 'report.md', '', ?)
            """,
            (TIMESTAMP,),
        )
        database.execute(
            """
            insert into delivery_outbox
              (id, event_key, job_id, result_artifact_id, delivery_binding_json,
               correlation_id, status, max_attempts, next_attempt_at, created_at,
               updated_at)
            values ('delivery-v13', 'delivery-v13', 'runtime-v14-job', 'artifact-v13',
                    '{}', 'correlation-v13', 'RETRY_WAIT', 8, ?, ?, ?)
            """,
            (TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        report = RuntimeV14CutoverPreflight(database).run(_queue_facts(messages=1, consumers=1))
    finally:
        database.close()

    assert report["status"] == "blocked"
    assert report["database"] == {
        "protocol_v13_nonterminal_jobs": 1,
        "protocol_v13_dispatch_outbox_nonterminal": 1,
        "protocol_v13_delivery_outbox_nonterminal": 1,
    }
    assert all(
        fact == {"exists": True, "messages": 1, "consumers": 1}
        for fact in report["queues"].values()
    )


def test_runtime_v14_cutover_preflight_rejects_incomplete_queue_facts(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        with pytest.raises(ValueError, match="queue fact is missing"):
            RuntimeV14CutoverPreflight(database).run({})
    finally:
        database.close()


def test_runtime_v14_cutover_preflight_rejects_unknown_schema_head(
    tmp_path: Path,
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    shutil.copy2(
        default_migrations_dir() / LEGACY_MANIFEST_FILENAME,
        migrations / LEGACY_MANIFEST_FILENAME,
    )
    for path in default_migrations_dir().glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 118:
            shutil.copy2(path, migrations / path.name)
    database = Database(f"sqlite:///{tmp_path / 'runtime-v14-old-head.db'}")
    Migrator(database, migrations, migrator_build="runtime-v14-old-head-test").run()
    try:
        with pytest.raises(SchemaHeadError, match="expected one of"):
            RuntimeV14CutoverPreflight(database).run(_queue_facts())
    finally:
        database.close()
