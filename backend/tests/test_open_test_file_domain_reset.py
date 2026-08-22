from __future__ import annotations

import hashlib
import json
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


class FakePostgresDatabase:
    engine = "postgres"

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del parameters
        if "information_schema.table_constraints" in statement:
            return []
        self.statements.append(statement)
        return []


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


def _snapshot_hash(snapshot: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _insert_agent_publication(
    database: Database,
    *,
    publication_id: str,
    revision: int,
    protocols: list[str],
) -> None:
    timestamp = "2026-08-22T00:00:00+00:00"
    revision_id = f"agent-revision-{revision}"
    snapshot: dict[str, object] = {
        "runtime_kind": "python-v1",
        "supported_runtime_protocol_versions": protocols,
    }
    database.execute(
        """
        insert into agent_revision
          (id, agent_id, revision, status, created_at, updated_at)
        values (?, 'current-agent', ?, 'published', ?, ?)
        """,
        (revision_id, revision, timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_publication
          (id, agent_id, revision_id, revision, schema_version, snapshot_json,
           config_hash, runtime_kind, status, published_at)
        values (?, 'current-agent', ?, ?, 3, ?, ?, 'python-v1', 'inactive', ?)
        """,
        (
            publication_id,
            revision_id,
            revision,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            _snapshot_hash(snapshot),
            timestamp,
        ),
    )


def _insert_application_revision(
    database: Database,
    *,
    revision_id: str,
    revision: int,
    agent_publication_id: str,
) -> None:
    timestamp = "2026-08-22T00:00:00+00:00"
    publication_id = f"application-publication-{revision}"
    database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, agent_publication_id,
           document_processing_profile_code, created_by, created_at, updated_at)
        values (?, 'current-application', ?, 'published', ?,
                'docling-layout-ocr-v2', 'test-user', ?, ?)
        """,
        (revision_id, revision, agent_publication_id, timestamp, timestamp),
    )
    database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, schema_version,
           snapshot_json, config_hash, document_processing_profile_code,
           published_by, published_at)
        values (?, 'current-application', ?, ?, 6, '{}', ?,
                'docling-layout-ocr-v2', 'test-user', ?)
        """,
        (publication_id, revision_id, revision, "a" * 64, timestamp),
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


def test_postgres_reset_truncates_polymorphic_file_domain_tables() -> None:
    database = FakePostgresDatabase()
    service = OpenTestFileDomainResetService(  # type: ignore[arg-type]
        database,
        FakeStorage(),
        FakeStorage(),
    )

    service._clear_database_rows()

    assert len(database.statements) == 1
    statement = database.statements[0]
    assert statement.startswith("truncate table ")
    assert '"file_cleanup_fact"' in statement
    assert '"file_domain_outbox"' in statement
    assert statement.endswith(" cascade")


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


def test_reset_rejects_only_claimed_cleanup_work(tmp_path: Path) -> None:
    database = _database(tmp_path)
    timestamp = "2026-08-22T00:00:00+00:00"
    database.execute(
        """
        insert into file_cleanup_fact
          (id, resource_type, resource_id, reason, status, due_at,
           next_attempt_at, created_at, updated_at)
        values ('claimed-cleanup', 'STAGING_OBJECT', 'staging-1', 'TEST',
                'CLAIMED', ?, ?, ?, ?)
        """,
        (timestamp, timestamp, timestamp, timestamp),
    )

    report = OpenTestFileDomainResetService(
        database,
        FakeStorage(),
        FakeStorage(),
    ).report()

    assert report["ready"] is False
    assert report["blockers"]["cleanup_work"] == 1


def test_reset_deletes_drained_database_roots_and_both_object_namespaces(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _insert_job(database, status="SUCCEEDED")
    timestamp = "2026-08-22T00:00:00+00:00"
    database.execute(
        """
        insert into file_cleanup_fact
          (id, resource_type, resource_id, reason, status, due_at,
           next_attempt_at, created_at, updated_at)
        values ('legacy-cleanup', 'ATTACHMENT_CONTENT', 'attachment-1', 'TEST',
                'PENDING', ?, ?, ?, ?)
        """,
        (timestamp, timestamp, timestamp, timestamp),
    )
    current = FakeStorage(("managed/a", "managed/b"))
    legacy = FakeStorage(("legacy/c",))
    service = OpenTestFileDomainResetService(database, current, legacy)
    report = service.report()

    assert report["ready"] is True
    assert report["table_counts"]["file_cleanup_fact"] == 1

    result = service.apply(
        expected_digest=str(report["inventory_digest"]),
        confirmation=CONFIRMATION,
    )

    assert result["status"] == "APPLIED"
    assert result["deleted_managed_objects"] == 3
    assert current.deleted == ["managed/a", "managed/b"]
    assert legacy.deleted == ["legacy/c"]
    assert database.execute_one("select count(*) as count from agent_job") == {"count": 0}
    assert database.execute_one("select count(*) as count from file_cleanup_fact") == {"count": 0}
    assert service.report()["ready"] is True


def test_reset_deletes_only_publications_outside_current_runtime_contract(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    timestamp = "2026-08-22T00:00:00+00:00"
    database.execute(
        """
        insert into agent_definition
          (id, code, name, current_publication_id, runtime_kind,
           created_at, updated_at)
        values ('current-agent', 'current-agent', 'Current Agent', null,
                'python-v1', ?, ?)
        """,
        (timestamp, timestamp),
    )
    _insert_agent_publication(
        database,
        publication_id="old-protocol-publication",
        revision=1,
        protocols=["1.2", "1.3"],
    )
    _insert_agent_publication(
        database,
        publication_id="current-protocol-publication",
        revision=2,
        protocols=["1.3"],
    )
    database.execute(
        """
        update agent_definition
           set current_publication_id = 'current-protocol-publication'
         where id = 'current-agent'
        """
    )
    database.execute(
        """
        insert into business_application
          (id, code, name, project_code, status, created_by, created_at, updated_at)
        values ('current-application', 'current-application', 'Current Application',
                'default', 'enabled', 'test-user', ?, ?)
        """,
        (timestamp, timestamp),
    )
    _insert_application_revision(
        database,
        revision_id="old-application-revision",
        revision=1,
        agent_publication_id="old-protocol-publication",
    )
    _insert_application_revision(
        database,
        revision_id="current-application-revision",
        revision=2,
        agent_publication_id="current-protocol-publication",
    )
    service = OpenTestFileDomainResetService(database, FakeStorage(), FakeStorage())

    report = service.report()

    assert report["legacy_contract_counts"] == {
        "agent_definitions": 0,
        "agent_publications": 1,
        "application_revisions": 1,
        "application_publications": 1,
    }
    result = service.apply(
        expected_digest=str(report["inventory_digest"]),
        confirmation=CONFIRMATION,
    )

    assert result["deleted_legacy_contract_rows"] == 3
    assert (
        database.execute_one(
            "select id from agent_publication where id = 'old-protocol-publication'"
        )
        is None
    )
    assert (
        database.execute_one(
            "select id from business_application_revision where id = 'old-application-revision'"
        )
        is None
    )
    assert (
        database.execute_one(
            "select id from business_application_publication where id = 'application-publication-1'"
        )
        is None
    )
    assert database.execute_one(
        "select id from agent_publication where id = 'current-protocol-publication'"
    ) == {"id": "current-protocol-publication"}
    assert database.execute_one(
        "select id from business_application_revision where id = 'current-application-revision'"
    ) == {"id": "current-application-revision"}
    assert database.execute_one(
        "select id from business_application_publication where id = 'application-publication-2'"
    ) == {"id": "application-publication-2"}
