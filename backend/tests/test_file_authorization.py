from __future__ import annotations

from typing import Any

import pytest

from app.modules.file_workspace.authorization import FileAuthorizationService
from app.modules.file_workspace.domain import (
    FileAction,
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionPeriod,
    SnapshotSourceKind,
    WorkspaceFileRole,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.exceptions import PermissionDenied
from backend.tests.test_file_workspace_repository import EXPIRES_AT, TIMESTAMP, _database
from services.file_service.audit import FileMcpAudit


class _BusinessAccess:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[dict[str, str]] = []

    def require(self, **kwargs: str) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self.allowed:
            raise PermissionDenied(
                "Business Application access revoked",
                safe_message="业务应用访问已撤销",
                error_code="application_access_denied",
            )
        return {"decision": "ALLOW"}


def _insert_user(database: Any, user_id: str) -> None:
    database.execute(
        """
        insert into app_user
          (id, username, display_name, status, account_type, created_at, updated_at)
        values (?, ?, ?, 'enabled', 'human', ?, ?)
        """,
        (user_id, user_id, user_id, TIMESTAMP, TIMESTAMP),
    )


def _claims(*, job_id: str, session_id: str, user_id: str, tenant_id: str) -> dict[str, Any]:
    return {
        "sub": user_id,
        "tenant_id": tenant_id,
        "job_id": job_id,
        "session_id": session_id,
        "agent_publication_id": "agent-publication-a",
        "application_publication_id": "app-file-p1",
    }


def _create_job(
    database: Any,
    *,
    job_id: str,
    session_id: str,
    workspace_id: str,
    user_id: str,
) -> None:
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id, internal_user_id,
           business_application_id, business_application_publication_id,
           agent_publication_id, task_workspace_id)
        values (?, ?, ?, 'RUNNING', ?, 'dingding_stream', 'connector-a', ?, ?,
                'app-file', 'app-file-p1', 'agent-publication-a', ?)
        """,
        (job_id, session_id, f"{job_id}-key", TIMESTAMP, user_id, user_id, workspace_id),
    )


def _create_file(
    repository: FileWorkspaceRepository,
    *,
    file_id: str,
    version_id: str,
    owner: FileOwner,
    workspace_id: str,
    logical_name: str,
) -> None:
    repository.create_file(
        file_id=file_id,
        tenant_id="tenant-a",
        owner=owner,
        display_name=logical_name,
        actor_id="user-a",
    )
    repository.create_version(
        version_id=version_id,
        file_id=file_id,
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=5,
        content_sha256="a" * 64,
        object_key=f"opaque/{version_id}",
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="user-a",
        advance_current_from="",
    )
    repository.link_workspace_file(
        workspace_id=workspace_id,
        file_id=file_id,
        version_id=version_id,
        logical_name=logical_name,
        role=WorkspaceFileRole.INPUT,
    )


def test_private_file_authorization_rechecks_job_publication_owner_and_manifest_action() -> None:
    database = _database()
    _insert_user(database, "user-a")
    database.execute(
        """
        update agent_session
           set application_publication_id = 'app-file-p1',
               business_application_id = 'app-file'
         where id = 'session-file'
        """
    )
    repository = FileWorkspaceRepository(database)
    owner = FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")
    repository.create_workspace(
        workspace_id="workspace-private",
        tenant_id="tenant-a",
        session_id="session-file",
        owner=owner,
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at=EXPIRES_AT,
        actor_id="user-a",
    )
    _create_file(
        repository,
        file_id="file-private",
        version_id="version-private",
        owner=owner,
        workspace_id="workspace-private",
        logical_name="private.txt",
    )
    _create_job(
        database,
        job_id="job-private",
        session_id="session-file",
        workspace_id="workspace-private",
        user_id="user-a",
    )
    repository.create_job_snapshot(
        snapshot_id="snapshot-private",
        job_id="job-private",
        workspace_id="workspace-private",
        tenant_id="tenant-a",
        principal_user_id="user-a",
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        manifest_hash="b" * 64,
        items=[
            {
                "file_id": "file-private",
                "version_id": "version-private",
                "display_name": "private.txt",
                "source_kind": SnapshotSourceKind.CURRENT_MESSAGE,
                "allowed_actions": [FileAction.READ_METADATA, FileAction.MATERIALIZE],
            }
        ],
    )
    access = _BusinessAccess()
    authorization = FileAuthorizationService(database, access)
    context = authorization.require_job(
        claims=_claims(
            job_id="job-private",
            session_id="session-file",
            user_id="user-a",
            tenant_id="tenant-a",
        ),
        tool_identifier="file_get_metadata",
    )
    assert authorization.require_manifest_action(
        context,
        file_id="file-private",
        version_id="version-private",
        action=FileAction.MATERIALIZE,
    )["version_id"] == "version-private"
    assert access.calls[-1]["stage"] == "file_principal_resolve"

    audit = FileMcpAudit(McpAuditCoordinator(database, max_payload_bytes=4096))
    audit_claims = {
        **context.claims,
        "jti": "principal-jti-a",
    }
    handle = audit.begin(
        claims=audit_claims,
        authorization=context,
        tool_identifier="file_get_metadata",
        arguments={
            "file_id": "file-private",
            "version_id": "version-private",
            "body": "must-not-persist",
            "object_key": "must-not-persist",
        },
        invocation_id="job-private.attempt-0",
        correlation_id="correlation-a",
    )
    audit.authorized(handle)
    audit.complete(
        handle,
        status="SUCCEEDED",
        result={
            "status": "SUCCEEDED",
            "file_id": "file-private",
            "version_id": "version-private",
            "object_key": "must-not-persist",
            "body": "must-not-persist",
        },
        duration_ms=7,
    )
    operation = database.execute_one(
        "select * from mcp_operation_audit where id = ?", (handle.root_audit_id,)
    )
    assert operation is not None
    assert operation["server_code"] == "file-service"
    assert operation["operation"] == "file.metadata.read"
    assert operation["principal_jti"] == "principal-jti-a"
    persisted = str(operation)
    assert "must-not-persist" not in persisted

    with pytest.raises(PermissionDenied):
        authorization.require_manifest_action(
            context,
            file_id="file-private",
            version_id="version-private",
            action=FileAction.DELIVER,
        )
    with pytest.raises(PermissionDenied):
        authorization.require_job(
            claims=_claims(
                job_id="job-private",
                session_id="session-file",
                user_id="user-other",
                tenant_id="tenant-a",
            ),
            tool_identifier="file_get_metadata",
        )

    revoked = FileAuthorizationService(database, _BusinessAccess(allowed=False))
    with pytest.raises(PermissionDenied) as error:
        revoked.require_job(
            claims=_claims(
                job_id="job-private",
                session_id="session-file",
                user_id="user-a",
                tenant_id="tenant-a",
            ),
            tool_identifier="file_get_metadata",
        )
    assert error.value.error_code == "application_access_denied"

    repository.mark_content_unavailable(
        version_id="version-private", deleted_at=TIMESTAMP
    )
    with pytest.raises(PermissionDenied) as error:
        authorization.require_manifest_action(
            context,
            file_id="file-private",
            version_id="version-private",
            action=FileAction.MATERIALIZE,
        )
    assert error.value.error_code == "file_content_unavailable"

    database.execute(
        "update task_workspace set status = 'EXPIRED' where id = 'workspace-private'"
    )
    with pytest.raises(PermissionDenied) as error:
        authorization.require_job(
            claims=_claims(
                job_id="job-private",
                session_id="session-file",
                user_id="user-a",
                tenant_id="tenant-a",
            ),
            tool_identifier="file_get_metadata",
        )
    assert error.value.error_code == "file_job_not_authorized"


def test_group_authorization_uses_same_enterprise_connector_conversation_and_actual_sender() -> None:
    database = _database()
    _insert_user(database, "user-b")
    database.execute(
        """
        insert into agent_session
          (id, source_channel, source_connector_id, external_conversation_id,
           requester_id, project_code, session_key, conversation_type,
           business_application_id, application_publication_id,
           created_at, updated_at)
        values ('session-group', 'dingding_stream', 'connector-a', 'group-a',
                'user-b', 'default', 'group:group-a', 'group', 'app-file',
                'app-file-p1', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    repository = FileWorkspaceRepository(database)
    group_owner = FileOwner(
        WorkspaceOwnerType.GROUP_CONVERSATION,
        enterprise_id="tenant-a",
        connector_id="connector-a",
        conversation_id="group-a",
    )
    repository.create_workspace(
        workspace_id="workspace-group",
        tenant_id="tenant-a",
        session_id="session-group",
        owner=group_owner,
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at=EXPIRES_AT,
        actor_id="user-b",
    )
    _create_file(
        repository,
        file_id="file-group",
        version_id="version-group",
        owner=group_owner,
        workspace_id="workspace-group",
        logical_name="group.txt",
    )
    _create_job(
        database,
        job_id="job-group",
        session_id="session-group",
        workspace_id="workspace-group",
        user_id="user-b",
    )
    repository.create_job_snapshot(
        snapshot_id="snapshot-group",
        job_id="job-group",
        workspace_id="workspace-group",
        tenant_id="tenant-a",
        principal_user_id="user-b",
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        manifest_hash="c" * 64,
        items=[
            {
                "file_id": "file-group",
                "version_id": "version-group",
                "display_name": "group.txt",
                "source_kind": SnapshotSourceKind.WORKSPACE,
                "allowed_actions": [FileAction.EDIT],
            }
        ],
    )
    authorization = FileAuthorizationService(database, _BusinessAccess())
    context = authorization.require_job(
        claims=_claims(
            job_id="job-group",
            session_id="session-group",
            user_id="user-b",
            tenant_id="tenant-a",
        ),
        tool_identifier="file_create_commit_intent",
    )
    assert context.workspace["owner_conversation_id"] == "group-a"
    assert authorization.require_manifest_action(
        context,
        file_id="file-group",
        version_id="version-group",
        action=FileAction.EDIT,
    )["file_id"] == "file-group"

    database.execute(
        "update task_workspace set owner_conversation_id = 'group-other' where id = 'workspace-group'"
    )
    with pytest.raises(PermissionDenied) as error:
        authorization.require_job(
            claims=_claims(
                job_id="job-group",
                session_id="session-group",
                user_id="user-b",
                tenant_id="tenant-a",
            ),
            tool_identifier="file_create_commit_intent",
        )
    assert error.value.error_code == "file_group_boundary_denied"
