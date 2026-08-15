from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.modules.file_workspace.lifecycle_service import FileLifecycleService
from app.modules.file_workspace.domain import CleanupResourceType
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_file_commit_streaming import NOW, _body, _fixture
from backend.tests.test_file_workspace_repository import TIMESTAMP


def test_workspace_expiry_defers_running_job_then_retries_physical_cleanup() -> None:
    repository, _streaming, _context, storage = _fixture()
    repository.database.execute(
        "update task_workspace set expires_at = ? where id = 'workspace-a'",
        ((NOW - timedelta(minutes=1)).isoformat(),),
    )
    clock = [NOW]
    lifecycle = FileLifecycleService(repository, storage, now=lambda: clock[0])

    deferred = lifecycle.run_once()
    assert deferred["workspaces_deferred"] == 1
    assert repository.get_workspace("workspace-a")["status"] == "ACTIVE"

    repository.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = 'job-file'"
    )
    storage.fail_delete = True
    first = lifecycle.run_once()
    assert first["workspaces_expired"] == 1
    assert first["cleanup_retried"] >= 1
    assert repository.get_workspace("workspace-a")["status"] == "CLEANED"
    assert repository.get_version("version-source-1")["status"] == "AVAILABLE"

    storage.fail_delete = False
    clock[0] += timedelta(hours=2)
    recovered = lifecycle.run_once()
    assert recovered["cleanup_completed"] >= 1
    assert repository.get_version("version-source-1")["status"] == (
        "CONTENT_UNAVAILABLE"
    )


def test_unknown_orphans_are_reported_not_deleted_and_missing_refs_are_counted() -> None:
    repository, _streaming, _context, storage = _fixture()
    lifecycle = FileLifecycleService(repository, storage, now=lambda: NOW)
    orphan = "managed/staging/report-only-orphan"
    storage.objects[orphan] = b"orphan"
    source_key = str(repository.get_version("version-source-1")["object_key"])

    report = lifecycle.run_once()
    assert report["unknown_orphan_objects"] == 1
    assert orphan in storage.objects
    assert report["missing_referenced_objects"] == 0

    storage.objects.pop(source_key)
    missing = lifecycle.run_once()
    assert missing["missing_referenced_objects"] == 1
    assert orphan in storage.objects


def test_expired_chat_attachment_content_is_deleted_and_cannot_be_recovered() -> None:
    repository, streaming, _context, storage = _fixture()
    repository.database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-expired', 'session-file', 'job-file', 'user', '', ?, 1)
        """,
        (TIMESTAMP,),
    )
    repository.database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           retention_days, expires_at, created_at, updated_at)
        values ('attachment-expired', 'message-expired', 'job-file', 0,
                'document', 'expired.txt', 'DOWNLOADING', 360, ?, ?, ?)
        """,
        ((NOW + timedelta(days=360)).isoformat(), TIMESTAMP, TIMESTAMP),
    )
    receipt = asyncio.run(
        streaming.import_attachment(
            attachment_id="attachment-expired",
            service_claims={"sub": "file-worker"},
            media_type="text/plain",
            body=_body(b"expired internal copy\n"),
        )
    )
    version_id = str(receipt["version_id"])
    repository.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = 'job-file'"
    )
    repository.database.execute(
        "update task_workspace set expires_at = ? where id = 'workspace-a'",
        ((NOW - timedelta(days=1)).isoformat(),),
    )
    repository.database.execute(
        "update message_attachment set expires_at = ? where id = 'attachment-expired'",
        ((NOW - timedelta(seconds=1)).isoformat(),),
    )
    repository.database.execute(
        "update file_retention_fact set expires_at = ? where version_id = ?",
        ((NOW - timedelta(seconds=1)).isoformat(), version_id),
    )
    repository.database.execute(
        """
        update file_cleanup_fact set due_at = ?, next_attempt_at = ?
         where resource_type = 'ATTACHMENT_CONTENT'
           and resource_id = 'attachment-expired'
        """,
        ((NOW - timedelta(seconds=1)).isoformat(), (NOW - timedelta(seconds=1)).isoformat()),
    )
    result = FileLifecycleService(repository, storage, now=lambda: NOW).run_once()
    assert result["cleanup_completed"] >= 2
    assert repository.database.execute_one(
        "select status, object_key from message_attachment where id = 'attachment-expired'"
    ) == {"status": "DELETED", "object_key": ""}
    with pytest.raises(NonRetryableExecutionError) as error:
        repository.require_content_available(version_id)
    assert error.value.error_code == "file_content_unavailable"


def _insert_expired_attachment(
    repository: object,
    *,
    attachment_id: str,
    object_bucket: str,
    object_key: str,
) -> None:
    database = repository.database  # type: ignore[attr-defined]
    database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values (?, 'session-file', 'job-file', 'user', '', ?, 7)
        """,
        (f"message-{attachment_id}", TIMESTAMP),
    )
    database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           object_bucket, object_key, sha256, size_bytes, retention_days,
           expires_at, created_at, updated_at)
        values (?, ?, 'job-file', 0, 'document', 'legacy.txt', 'READY',
                ?, ?, ?, 7, 360, ?, ?, ?)
        """,
        (
            attachment_id,
            f"message-{attachment_id}",
            object_bucket,
            object_key,
            "a" * 64,
            (NOW - timedelta(seconds=1)).isoformat(),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    repository.enqueue_cleanup(  # type: ignore[attr-defined]
        resource_type=CleanupResourceType.ATTACHMENT_CONTENT,
        resource_id=attachment_id,
        reason="RETENTION_EXPIRED",
        due_at=(NOW - timedelta(seconds=1)).isoformat(),
    )
    database.execute("update agent_job set status = 'SUCCEEDED' where id = 'job-file'")


def test_expired_legacy_attachment_is_deleted_only_from_legacy_bucket() -> None:
    repository, _streaming, _context, storage = _fixture()
    legacy_storage = type(storage)()
    legacy_key = "attachments/legacy-expired/content.txt"
    legacy_storage.objects[legacy_key] = b"legacy\n"
    _insert_expired_attachment(
        repository,
        attachment_id="attachment-legacy-expired",
        object_bucket="agent-attachments",
        object_key=legacy_key,
    )
    main_before = dict(storage.objects)

    result = FileLifecycleService(
        repository,
        storage,
        legacy_attachment_storage=legacy_storage,
        legacy_attachment_bucket="agent-attachments",
        now=lambda: NOW,
    ).run_once()

    assert result["cleanup_completed"] >= 1
    assert legacy_key not in legacy_storage.objects
    assert storage.objects == main_before
    assert repository.database.execute_one(
        """
        select status, object_bucket, object_key, content_deleted_at
          from message_attachment where id = 'attachment-legacy-expired'
        """
    ) == {
        "status": "DELETED",
        "object_bucket": "",
        "object_key": "",
        "content_deleted_at": NOW.isoformat(),
    }


def test_unmanaged_attachment_bucket_retries_without_claiming_content_deleted() -> None:
    repository, _streaming, _context, storage = _fixture()
    legacy_storage = type(storage)()
    unknown_key = "outside/unknown.txt"
    _insert_expired_attachment(
        repository,
        attachment_id="attachment-unmanaged",
        object_bucket="unmanaged-bucket",
        object_key=unknown_key,
    )
    main_before = dict(storage.objects)
    legacy_before = dict(legacy_storage.objects)

    result = FileLifecycleService(
        repository,
        storage,
        legacy_attachment_storage=legacy_storage,
        legacy_attachment_bucket="agent-attachments",
        now=lambda: NOW,
    ).run_once()

    assert result["cleanup_retried"] >= 1
    assert storage.objects == main_before
    assert legacy_storage.objects == legacy_before
    assert repository.database.execute_one(
        """
        select status, object_bucket, object_key, content_deleted_at
          from message_attachment where id = 'attachment-unmanaged'
        """
    ) == {
        "status": "READY",
        "object_bucket": "unmanaged-bucket",
        "object_key": unknown_key,
        "content_deleted_at": None,
    }
    assert repository.database.execute_one(
        """
        select status, failure_code from file_cleanup_fact
         where resource_type = 'ATTACHMENT_CONTENT'
           and resource_id = 'attachment-unmanaged'
        """
    ) == {"status": "RETRY", "failure_code": "RuntimeError"}
