from __future__ import annotations

from datetime import UTC, datetime

from app.cli.backfill_task_file_attachments import build_parser
from app.modules.file_workspace.attachment_backfill import AttachmentFileBackfill
from backend.tests.test_file_commit_streaming import TIMESTAMP, _fixture


def _insert_attachment(
    database: object,
    *,
    attachment_id: str,
    ordinal: int,
    managed_file_id: str = "",
    managed_version_id: str = "",
) -> None:
    database.execute(  # type: ignore[attr-defined]
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           object_bucket, object_key, sha256, size_bytes,
           managed_file_id, managed_file_version_id,
           retention_days, created_at, updated_at)
        values (?, 'message-backfill', 'job-file', ?, 'document', 'bounded.txt',
                'READY', 'legacy-private', 'redacted-object-location', ?, 7,
                ?, ?, 360, ?, ?)
        """,
        (attachment_id, ordinal, "a" * 64, managed_file_id, managed_version_id, TIMESTAMP, TIMESTAMP),
    )


def test_attachment_backfill_is_dry_run_resumable_and_performs_no_object_io() -> None:
    repository, _streaming, _context, storage = _fixture()
    repository.database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-backfill', 'session-file', 'job-file', 'user', '', ?, 1)
        """,
        (TIMESTAMP,),
    )
    _insert_attachment(
        repository.database,
        attachment_id="attachment-01-associated",
        ordinal=0,
        managed_file_id="file-source",
        managed_version_id="version-source-1",
    )
    _insert_attachment(
        repository.database,
        attachment_id="attachment-02-legacy",
        ordinal=1,
    )
    before_objects = dict(storage.objects)
    service = AttachmentFileBackfill(
        repository.database,
        now=datetime(2026, 8, 15, tzinfo=UTC),
    )

    dry = service.run(batch_size=1)

    assert dry == {
        "mode": "dry-run",
        "status": "ready",
        "scanned": 1,
        "expiry_updates": 1,
        "binding_inserts": 1,
        "binding_column_repairs": 0,
        "cleanup_fact_inserts": 1,
        "unassociated_legacy": 0,
        "blocking_count": 0,
        "blocking_attachment_ids": [],
        "next_cursor": "attachment-01-associated",
        "has_more": True,
        "object_io_performed": False,
    }
    assert repository.database.execute_one(
        "select expires_at from message_attachment where id = 'attachment-01-associated'"
    ) == {"expires_at": None}
    assert storage.objects == before_objects

    first = service.run(apply=True, batch_size=1)
    second = service.run(
        apply=True,
        cursor=str(first["next_cursor"]),
        batch_size=1,
    )
    repeat = service.run(apply=True, batch_size=10)

    assert first["binding_inserts"] == 1
    assert second["unassociated_legacy"] == 1
    assert second["next_cursor"] == "attachment-02-legacy"
    assert repeat["binding_inserts"] == 0
    assert repeat["cleanup_fact_inserts"] == 0
    assert repository.database.execute_one(
        """
        select file_id, version_id from message_attachment_file_binding
         where attachment_id = 'attachment-01-associated'
        """
    ) == {"file_id": "file-source", "version_id": "version-source-1"}
    assert repository.database.execute_one(
        """
        select count(*) as value from file_cleanup_fact
         where resource_type = 'ATTACHMENT_CONTENT'
           and resource_id in ('attachment-01-associated', 'attachment-02-legacy')
        """
    ) == {"value": 2}
    assert storage.objects == before_objects


def test_attachment_backfill_reconcile_blocks_divergent_binding_without_writes() -> None:
    repository, _streaming, _context, _storage = _fixture()
    repository.database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-backfill', 'session-file', 'job-file', 'user', '', ?, 1)
        """,
        (TIMESTAMP,),
    )
    _insert_attachment(
        repository.database,
        attachment_id="attachment-divergent",
        ordinal=0,
        managed_file_id="file-source",
        managed_version_id="version-source-1",
    )
    repository.database.execute(
        """
        insert into message_attachment_file_binding
          (attachment_id, file_id, version_id, retention_expires_at, created_at)
        values ('attachment-divergent', 'file-source', 'version-source-1',
                '2099-01-01T00:00:00+00:00', ?)
        """,
        (TIMESTAMP,),
    )

    report = AttachmentFileBackfill(repository.database).run(
        apply=True,
        reconcile=False,
    )

    assert report["status"] == "blocked"
    assert report["blocking_attachment_ids"] == ["attachment-divergent"]
    assert repository.database.execute_one(
        "select expires_at from message_attachment where id = 'attachment-divergent'"
    ) == {"expires_at": None}
    assert repository.database.execute_one(
        "select count(*) as value from file_cleanup_fact where resource_id = 'attachment-divergent'"
    ) == {"value": 0}


def test_attachment_backfill_cli_defaults_to_dry_run_and_supports_reconcile() -> None:
    default = build_parser().parse_args([])
    reconcile = build_parser().parse_args(["--reconcile", "--cursor", "a", "--batch-size", "7"])

    assert default.apply is False
    assert default.reconcile is False
    assert default.batch_size == 100
    assert reconcile.reconcile is True
    assert reconcile.cursor == "a"
    assert reconcile.batch_size == 7
