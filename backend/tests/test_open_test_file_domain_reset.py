from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.file_workspace.open_test_reset import (
    CONFIRMATION,
    OpenTestFileDomainResetService,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


class FakeStorage:
    def __init__(self, keys: tuple[str, ...] = ()) -> None:
        self.keys = list(keys)
        self.deleted: list[str] = []

    def list_keys(self) -> list[str]:
        return list(self.keys)

    def delete(self, *, internal_object_key: str) -> None:
        self.keys.remove(internal_object_key)
        self.deleted.append(internal_object_key)


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'open-test-reset.db'}")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="open-test-reset-test",
    ).run()
    return database


def _insert_job(database: Database, *, status: str) -> None:
    timestamp = "2026-08-22T00:00:00+00:00"
    database.execute(
        """
        insert into agent_session
          (id, project_code, created_at, updated_at, source_channel,
           source_connector_id, external_conversation_id, requester_id, session_key)
        values ('reset-session', 'default', ?, ?, 'test', 'connector-test',
                'reset-conversation', 'reset-user', 'reset-session')
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, project_code, status, created_at,
           source_channel, source_connector_id, requester_id,
           agent_runtime_kind, agent_runtime_protocol_version)
        values ('reset-job', 'reset-session', 'reset-job', 'default', ?, ?,
                'test', 'connector-test', 'reset-user', 'python-v1', '1.3')
        """,
        (status, timestamp),
    )


def test_reset_report_is_redacted_stable_and_requires_exact_confirmation(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    current = FakeStorage(("managed/a",))
    legacy = FakeStorage(("legacy/b",))
    service = OpenTestFileDomainResetService(database, current, legacy)

    first = service.report()
    second = service.report()

    assert first == second
    assert first["ready"] is True
    assert first["managed_object_count"] == 1
    assert first["legacy_managed_object_count"] == 1
    assert "managed/a" not in str(first)
    assert "legacy/b" not in str(first)
    with pytest.raises(NonRetryableExecutionError) as rejected:
        service.apply(
            expected_digest=str(first["inventory_digest"]),
            confirmation="wrong",
        )
    assert rejected.value.error_code == "open_test_reset_confirmation_invalid"


def test_reset_rejects_nonterminal_work_and_inventory_drift(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_job(database, status="PENDING")
    current = FakeStorage()
    service = OpenTestFileDomainResetService(database, current, FakeStorage())
    report = service.report()

    assert report["ready"] is False
    assert report["blockers"]["agent_jobs"] == 1
    with pytest.raises(NonRetryableExecutionError) as blocked:
        service.apply(
            expected_digest=str(report["inventory_digest"]),
            confirmation=CONFIRMATION,
        )
    assert blocked.value.error_code == "open_test_reset_not_drained"

    database.execute("update agent_job set status = 'SUCCEEDED' where id = 'reset-job'")
    with pytest.raises(NonRetryableExecutionError) as changed:
        service.apply(
            expected_digest=str(report["inventory_digest"]),
            confirmation=CONFIRMATION,
        )
    assert changed.value.error_code == "open_test_reset_inventory_changed"


def test_reset_deletes_drained_database_roots_and_both_object_namespaces(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _insert_job(database, status="SUCCEEDED")
    current = FakeStorage(("managed/a", "managed/b"))
    legacy = FakeStorage(("legacy/c",))
    service = OpenTestFileDomainResetService(database, current, legacy)
    report = service.report()

    result = service.apply(
        expected_digest=str(report["inventory_digest"]),
        confirmation=CONFIRMATION,
    )

    assert result["status"] == "APPLIED"
    assert result["deleted_managed_objects"] == 3
    assert current.deleted == ["managed/a", "managed/b"]
    assert legacy.deleted == ["legacy/c"]
    assert database.execute_one("select count(*) as count from agent_job") == {"count": 0}
    assert service.report()["ready"] is True
