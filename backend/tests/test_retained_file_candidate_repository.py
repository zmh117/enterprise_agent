from __future__ import annotations

from app.modules.file_workspace.domain import (
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionReason,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.job.infrastructure.repositories import AgentRepository
from backend.tests.test_file_workspace_repository import TIMESTAMP, _database


NOW = "2026-08-20T00:00:00+00:00"
PAST = "2026-08-19T23:59:59+00:00"
FUTURE = "2027-08-20T00:00:00+00:00"


def _candidate() -> tuple[AgentRepository, FileWorkspaceRepository]:
    database = _database()
    files = FileWorkspaceRepository(database)
    owner = FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")
    files.create_file(
        file_id="file-retained",
        tenant_id="tenant-a",
        owner=owner,
        display_name="retained.docx",
        actor_id="user-a",
        source_received_at=TIMESTAMP,
    )
    files.create_version(
        version_id="version-retained",
        file_id="file-retained",
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        encoding="binary",
        size_bytes=5,
        content_sha256="a" * 64,
        object_key="opaque/version-retained",
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="user-a",
        advance_current_from="",
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id)
        values ('job-retained', 'session-file', 'job-retained-key', 'SUCCEEDED', ?,
                'dingding_stream', 'connector-a', 'user-a')
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, external_message_id,
           created_at, sequence_no)
        values ('message-retained', 'session-file', 'job-retained', 'user', '',
                'external-retained', ?, 1)
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           readability_status, retention_days, expires_at, created_at, updated_at)
        values ('attachment-retained', 'message-retained', 'job-retained', 0,
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'retained.docx', 'READY', 'AVAILABLE', 360, ?, ?, ?)
        """,
        (FUTURE, TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into message_attachment_file_binding
          (attachment_id, file_id, version_id, retention_expires_at, created_at)
        values ('attachment-retained', 'file-retained', 'version-retained', ?, ?)
        """,
        (FUTURE, TIMESTAMP),
    )
    return AgentRepository(database), files


def _rows(repository: AgentRepository) -> list[dict[str, object]]:
    return repository.list_session_retained_attachment_rows(
        session_id="session-file", now=NOW
    )


def test_retained_candidate_requires_current_retention_fact() -> None:
    repository, files = _candidate()
    assert _rows(repository) == []

    files.add_retention(
        version_id="version-retained",
        reason=RetentionReason.MESSAGE_ATTACHMENT,
        source_id="attachment-retained",
        starts_at=TIMESTAMP,
        expires_at=FUTURE,
    )
    assert [row["version_id"] for row in _rows(repository)] == ["version-retained"]


def test_retained_candidate_fails_closed_for_each_expired_boundary() -> None:
    repository, files = _candidate()
    files.add_retention(
        version_id="version-retained",
        reason=RetentionReason.MESSAGE_ATTACHMENT,
        source_id="attachment-retained",
        starts_at=TIMESTAMP,
        expires_at=FUTURE,
    )
    database = repository.database

    database.execute(
        "update message_attachment set status = 'FAILED' where id = 'attachment-retained'"
    )
    assert _rows(repository) == []
    database.execute(
        "update message_attachment set status = 'READY', expires_at = ? where id = 'attachment-retained'",
        (PAST,),
    )
    assert _rows(repository) == []
    database.execute(
        "update message_attachment set expires_at = ? where id = 'attachment-retained'",
        (FUTURE,),
    )
    database.execute(
        "update message_attachment_file_binding set retention_expires_at = ? where attachment_id = 'attachment-retained'",
        (PAST,),
    )
    assert _rows(repository) == []
    database.execute(
        "update message_attachment_file_binding set retention_expires_at = ? where attachment_id = 'attachment-retained'",
        (FUTURE,),
    )
    database.execute(
        "update file_retention_fact set expires_at = ? where version_id = 'version-retained'",
        (PAST,),
    )
    assert _rows(repository) == []


def test_cleanup_lag_does_not_extend_retained_candidate_visibility() -> None:
    repository, files = _candidate()
    files.add_retention(
        version_id="version-retained",
        reason=RetentionReason.MESSAGE_ATTACHMENT,
        source_id="attachment-retained",
        starts_at=TIMESTAMP,
        expires_at=PAST,
    )
    row = repository.database.execute_one(
        "select f.status as file_status, v.status as version_status from managed_file f join managed_file_version v on v.file_id = f.id where v.id = 'version-retained'"
    )
    assert row == {"file_status": "ACTIVE", "version_status": "AVAILABLE"}
    assert _rows(repository) == []
