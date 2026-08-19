from __future__ import annotations

import pytest

from app.modules.file_workspace.domain import (
    CleanupResourceType,
    CommitDeliveryMode,
    CommitIntentStatus,
    CommitUserIntent,
    FileAction,
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionPeriod,
    RetentionReason,
    SnapshotSourceKind,
    WorkspaceFileRole,
    WorkspaceOwnerType,
    WorkspaceStatus,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


TIMESTAMP = "2026-08-14T00:00:00+00:00"
SHANGHAI_TIMESTAMP = "2026-08-14T08:00:00+08:00"
EXPIRES_AT = "2026-08-17T16:00:00+00:00"


def _database() -> Database:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="file-repository-test").run()
    database.execute(
        """
        insert into business_application
          (id, code, name, project_code, status, revision,
           created_by, created_at, updated_at)
        values ('app-file', 'app-file', 'File App', 'default', 'enabled', 1,
                'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, created_by, created_at, updated_at)
        values ('app-file-r1', 'app-file', 1, 'published', 'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, schema_version,
           snapshot_json, config_hash, published_by, published_at)
        values ('app-file-p1', 'app-file', 'app-file-r1', 1, 1, '{}', ?,
                'user-a', ?)
        """,
        ("a" * 64, TIMESTAMP),
    )
    database.execute(
        """
        insert into agent_session
          (id, source_channel, source_connector_id, external_conversation_id,
           requester_id, project_code, session_key, created_at, updated_at)
        values ('session-file', 'dingding_stream', 'connector-a', 'conversation-a',
                'user-a', 'default', 'direct:user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    return database


def _private_owner() -> FileOwner:
    return FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")


def test_repository_maps_all_file_aggregate_records_and_state_transitions() -> None:
    database = _database()
    repository = FileWorkspaceRepository(database)
    workspace = repository.create_workspace(
        workspace_id="workspace-a",
        tenant_id="tenant-a",
        session_id="session-file",
        owner=_private_owner(),
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at=EXPIRES_AT,
        actor_id="user-a",
    )
    assert workspace["status"] == WorkspaceStatus.ACTIVE.value
    assert repository.get_active_workspace("session-file") is not None

    file_row = repository.create_file(
        file_id="file-a",
        tenant_id="tenant-a",
        owner=_private_owner(),
        display_name="input.txt",
        actor_id="user-a",
    )
    assert file_row["current_version_id"] is None
    version = repository.create_version(
        version_id="version-a-1",
        file_id="file-a",
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=5,
        content_sha256="b" * 64,
        object_key="opaque/version-a-1",
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="user-a",
        advance_current_from="",
    )
    assert version["version_number"] == 1
    assert repository.get_file("file-a")["current_version_id"] == "version-a-1"
    link = repository.link_workspace_file(
        workspace_id="workspace-a",
        file_id="file-a",
        version_id="version-a-1",
        logical_name="input.txt",
        role=WorkspaceFileRole.INPUT,
    )
    assert link["selected_version_id"] == "version-a-1"
    reference = repository.add_external_reference(
        file_id="file-a",
        version_id="version-a-1",
        provider="DINGTALK",
        source_type="CHAT_ATTACHMENT",
        source_id="attachment-source-a",
    )
    assert reference["source_id"] == "attachment-source-a"

    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id, task_workspace_id)
        values ('job-file', 'session-file', 'job-file-key', 'RUNNING', ?,
                'dingding_stream', 'connector-a', 'user-a', 'workspace-a')
        """,
        (TIMESTAMP,),
    )
    snapshot = repository.create_job_snapshot(
        snapshot_id="snapshot-a",
        job_id="job-file",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
        principal_user_id="user-a",
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        manifest_hash="c" * 64,
        items=[
            {
                "file_id": "file-a",
                "version_id": "version-a-1",
                "display_name": "input.txt",
                "source_kind": SnapshotSourceKind.CURRENT_MESSAGE,
                "allowed_actions": [FileAction.MATERIALIZE, FileAction.EDIT],
                "auto_materialize": True,
            }
        ],
    )
    assert snapshot["items"][0]["allowed_actions_json"] == '["MATERIALIZE","EDIT"]'

    intent = repository.create_commit_intent(
        intent_id="intent-a",
        commit_id="commit-a",
        job_id="job-file",
        workspace_id="workspace-a",
        target_file_id="file-a",
        base_version_id="version-a-1",
        sandbox_entry_handle="sandbox-entry-a",
        display_name="input.txt",
        user_intent=CommitUserIntent.MODIFY,
        delivery_mode=CommitDeliveryMode.DEFAULT,
        metadata_hash="d" * 64,
        expires_at=EXPIRES_AT,
    )
    assert intent["status"] == CommitIntentStatus.INTENT.value
    assert repository.transition_commit_intent(
        "intent-a", CommitIntentStatus.UPLOADING
    )["status"] == CommitIntentStatus.UPLOADING.value
    assert repository.create_staging(
        intent_id="intent-a", object_key="opaque/staging-a"
    )["status"] == "UPLOADING"

    repository.create_version(
        version_id="version-a-conflict",
        file_id="file-a",
        version_number=2,
        version_kind=FileVersionKind.CONFLICT,
        status=FileVersionStatus.CONFLICT,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=7,
        content_sha256="e" * 64,
        object_key="opaque/version-a-conflict",
        source_kind=FileSourceKind.CONFLICT,
        actor_id="user-a",
        parent_version_id="version-a-1",
        base_version_id="version-a-1",
    )
    assert repository.record_conflict(
        intent_id="intent-a",
        file_id="file-a",
        base_version_id="version-a-1",
        current_version_id="version-a-1",
        candidate_version_id="version-a-conflict",
    )["status"] == "OPEN"
    assert repository.add_retention(
        version_id="version-a-1",
        reason=RetentionReason.USER_SAVED,
        source_id="job-file",
        starts_at=TIMESTAMP,
        expires_at="2027-08-09T00:00:00+00:00",
    )["retention_days"] == 360
    cleanup = repository.enqueue_cleanup(
        resource_type=CleanupResourceType.STAGING_OBJECT,
        resource_id="intent-a",
        reason="ORPHANED_STAGING",
        due_at=TIMESTAMP,
    )
    assert repository.claim_cleanup(
        str(cleanup["id"]), worker_id="file-worker-a", now=TIMESTAMP
    )["status"] == "CLAIMED"

    assert repository.transition_workspace(
        "workspace-a", WorkspaceStatus.CLOSED, at=TIMESTAMP
    )["status"] == WorkspaceStatus.CLOSED.value


def test_repository_rolls_back_version_when_current_pointer_compare_and_set_fails() -> None:
    database = _database()
    repository = FileWorkspaceRepository(database)
    repository.create_file(
        file_id="file-a",
        tenant_id="tenant-a",
        owner=_private_owner(),
        display_name="input.txt",
        actor_id="user-a",
    )
    with pytest.raises(NonRetryableExecutionError) as error:
        repository.create_version(
            version_id="version-rolled-back",
            file_id="file-a",
            version_number=1,
            version_kind=FileVersionKind.WORKING,
            status=FileVersionStatus.AVAILABLE,
            media_type="text/plain",
            encoding="utf-8",
            size_bytes=5,
            content_sha256="f" * 64,
            object_key="opaque/version-rolled-back",
            source_kind=FileSourceKind.AGENT_EDITED,
            actor_id="user-a",
            advance_current_from="missing-version",
        )
    assert error.value.error_code == "file_state_conflict"
    assert database.execute_one(
        "select id from managed_file_version where id = 'version-rolled-back'"
    ) is None


def test_file_owner_and_active_workspace_fail_closed() -> None:
    with pytest.raises(NonRetryableExecutionError):
        FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a", conversation_id="group-a")

    database = _database()
    repository = FileWorkspaceRepository(database)
    arguments = {
        "tenant_id": "tenant-a",
        "session_id": "session-file",
        "owner": _private_owner(),
        "publication_id": "app-file-p1",
        "retention_period": RetentionPeriod.WEEK,
        "expires_at": EXPIRES_AT,
        "actor_id": "user-a",
    }
    repository.create_workspace(workspace_id="workspace-a", **arguments)
    with pytest.raises(NonRetryableExecutionError) as error:
        repository.create_workspace(workspace_id="workspace-b", **arguments)
    assert error.value.error_code == "workspace_active_conflict"
