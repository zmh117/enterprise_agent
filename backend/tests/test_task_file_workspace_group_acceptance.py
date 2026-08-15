from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.modules.file_workspace.authorization import (
    FileAuthorizationContext,
    FileAuthorizationService,
)
from app.modules.file_workspace.contracts import FILE_TRANSFER_META_KEY
from app.modules.file_workspace.domain import (
    FileAction,
    FileOwner,
    RetentionPeriod,
    SnapshotSourceKind,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.streaming_service import (
    INTERNAL_TRANSFER_META,
    GovernedFileStreamingService,
)
from app.shared.exceptions import PermissionDenied
from backend.tests.test_file_authorization import (
    _BusinessAccess,
    _claims,
    _create_file,
    _create_job,
    _insert_user,
)
from backend.tests.test_file_commit_streaming import NOW, _Storage, _body
from backend.tests.test_file_workspace_repository import EXPIRES_AT, TIMESTAMP, _database


class _BoundPrincipal:
    def __init__(self, context: FileAuthorizationContext) -> None:
        self.context = context

    def authenticate(
        self,
        token: str,
        *,
        tool_identifier: str = "task_workspace_get",
    ) -> tuple[dict[str, Any], FileAuthorizationContext, tuple[str, ...]]:
        assert token == "synthetic-principal"
        return self.context.claims, self.context, (tool_identifier,)


def _prepare_group_edit(
    service: GovernedFileStreamingService,
    context: FileAuthorizationContext,
    *,
    handle: str,
) -> str:
    result = service.prepare_commit(
        context=context,
        arguments={
            "sandbox_entry_handle": handle,
            "file_id": "file-group",
            "base_version_id": "version-group-1",
            "display_name": "group.txt",
            "user_intent": "MODIFY",
            "delivery_mode": "WORKSPACE_ONLY",
        },
    )
    return str(result[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]["commit_id"])


def test_two_group_members_share_workspace_but_concurrent_edits_keep_one_current_version() -> None:
    database = _database()
    _insert_user(database, "user-a")
    _insert_user(database, "user-b")
    database.execute(
        """
        insert into agent_session
          (id, source_channel, source_connector_id, external_conversation_id,
           requester_id, project_code, session_key, conversation_type,
           business_application_id, application_publication_id,
           created_at, updated_at)
        values ('session-group-shared', 'dingding_stream', 'connector-a', 'group-a',
                'user-a', 'default', 'group:group-a', 'group', 'app-file',
                'app-file-p1', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    repository = FileWorkspaceRepository(database)
    owner = FileOwner(
        WorkspaceOwnerType.GROUP_CONVERSATION,
        enterprise_id="tenant-a",
        connector_id="connector-a",
        conversation_id="group-a",
    )
    workspace = repository.create_workspace(
        workspace_id="workspace-group-shared",
        tenant_id="tenant-a",
        session_id="session-group-shared",
        owner=owner,
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at=EXPIRES_AT,
        actor_id="user-a",
    )
    _create_file(
        repository,
        file_id="file-group",
        version_id="version-group-1",
        owner=owner,
        workspace_id=str(workspace["id"]),
        logical_name="group.txt",
    )
    authorization = FileAuthorizationService(database, _BusinessAccess())
    contexts: dict[str, FileAuthorizationContext] = {}
    for user_id in ("user-a", "user-b"):
        job_id = f"job-{user_id}"
        _create_job(
            database,
            job_id=job_id,
            session_id="session-group-shared",
            workspace_id="workspace-group-shared",
            user_id=user_id,
        )
        repository.create_job_snapshot(
            snapshot_id=f"snapshot-{user_id}",
            job_id=job_id,
            workspace_id="workspace-group-shared",
            tenant_id="tenant-a",
            principal_user_id=user_id,
            publication_id="app-file-p1",
            retention_period=RetentionPeriod.WEEK,
            manifest_hash=("a" if user_id == "user-a" else "b") * 64,
            items=[
                {
                    "file_id": "file-group",
                    "version_id": "version-group-1",
                    "display_name": "group.txt",
                    "source_kind": SnapshotSourceKind.WORKSPACE,
                    "allowed_actions": [FileAction.EDIT, FileAction.COMMIT],
                }
            ],
        )
        contexts[user_id] = authorization.require_job(
            claims=_claims(
                job_id=job_id,
                session_id="session-group-shared",
                user_id=user_id,
                tenant_id="tenant-a",
            ),
            tool_identifier="file_create_commit_intent",
        )

    storage = _Storage()
    services = {
        user_id: GovernedFileStreamingService(
            repository,
            authorization,
            storage,
            _BoundPrincipal(context),
            now=lambda: NOW,
        )
        for user_id, context in contexts.items()
    }
    commit_a = _prepare_group_edit(services["user-a"], contexts["user-a"], handle="a")
    commit_b = _prepare_group_edit(services["user-b"], contexts["user-b"], handle="b")
    result_a = asyncio.run(
        services["user-a"].upload_commit(
            commit_id=commit_a,
            token="synthetic-principal",
            body=_body(b"edit from member a\n"),
        )
    )
    result_b = asyncio.run(
        services["user-b"].upload_commit(
            commit_id=commit_b,
            token="synthetic-principal",
            body=_body(b"edit from member b\n"),
        )
    )

    assert result_a["status"] == "COMMITTED"
    assert result_b["status"] == "CONFLICT"
    assert repository.get_file("file-group")["current_version_id"] == result_a["version_id"]
    assert database.execute_one(
        "select count(*) as value from file_conflict_candidate where file_id = 'file-group'"
    ) == {"value": 1}
    assert database.execute(
        """
        select i.commit_id, j.internal_user_id
          from file_commit_intent i join agent_job j on j.id = i.job_id
         order by j.internal_user_id
        """
    ) == [
        {"commit_id": commit_a, "internal_user_id": "user-a"},
        {"commit_id": commit_b, "internal_user_id": "user-b"},
    ]

    database.execute(
        "update agent_session set external_conversation_id = 'group-other' where id = 'session-group-shared'"
    )
    with pytest.raises(PermissionDenied) as error:
        authorization.require_job(
            claims=_claims(
                job_id="job-user-b",
                session_id="session-group-shared",
                user_id="user-b",
                tenant_id="tenant-a",
            ),
            tool_identifier="file_create_commit_intent",
        )
    assert error.value.error_code == "file_group_boundary_denied"
