from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.file_workspace.authorization import FileAuthorizationContext
from app.modules.file_workspace.contracts import FILE_TRANSFER_META_KEY
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
from app.modules.file_workspace.manifest_service import JobFileManifestService
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.storage import InternalStoredObject
from app.modules.file_workspace.streaming_service import (
    INTERNAL_TRANSFER_META,
    GovernedFileStreamingService,
)
from app.modules.file_workspace.workspace_service import TaskWorkspaceService
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_file_workspace_repository import EXPIRES_AT, TIMESTAMP, _database


NOW = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)


async def _body(value: bytes) -> AsyncIterator[bytes]:
    midpoint = len(value) // 2
    yield value[:midpoint]
    yield value[midpoint:]


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_put = False
        self.fail_delete = False
        self.sequence = 0

    def new_object_key(self, *, kind: str) -> str:
        self.sequence += 1
        return f"managed/{kind}/opaque-{self.sequence}"

    def put_stream(
        self,
        stream: Any,
        *,
        kind: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        internal_object_key: str | None = None,
    ) -> InternalStoredObject:
        assert kind in {"staging", "attachment"}
        assert content_type == "text/plain"
        if self.fail_put:
            raise OSError("simulated object write failure")
        key = internal_object_key or self.new_object_key(kind=kind)
        content = bytes(stream.read())
        assert len(content) == size_bytes
        self.objects[key] = content
        return InternalStoredObject(key, size_bytes, content_sha256)

    def open_stream(self, *, internal_object_key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[internal_object_key])

    def delete(self, *, internal_object_key: str) -> None:
        if self.fail_delete:
            raise OSError("simulated object delete failure")
        self.objects.pop(internal_object_key, None)

    def exists(self, *, internal_object_key: str) -> bool:
        return internal_object_key in self.objects

    def list_keys(self) -> list[str]:
        return sorted(self.objects)


class _Authorization:
    def __init__(self, repository: FileWorkspaceRepository) -> None:
        self.repository = repository

    def require_manifest_action(
        self,
        context: FileAuthorizationContext,
        *,
        file_id: str,
        version_id: str,
        action: FileAction,
    ) -> dict[str, Any]:
        row = self.repository.database.execute_one(
            """
            select * from agent_job_file_snapshot_item
             where snapshot_id = ? and file_id = ? and version_id = ?
            """,
            (context.manifest["id"], file_id, version_id),
        )
        assert row is not None
        assert action.value in json.loads(str(row["allowed_actions_json"]))
        return row


class _Principal:
    def __init__(self, context: FileAuthorizationContext) -> None:
        self.context = context

    def authenticate(
        self, token: str, *, tool_identifier: str = "task_workspace_get"
    ) -> tuple[dict[str, Any], FileAuthorizationContext, tuple[str, ...]]:
        assert token == "file-principal-token"
        assert tool_identifier in {
            "file_create_commit_intent",
            "file_prepare_materialization",
        }
        return self.context.claims, self.context, (tool_identifier,)


def _fixture() -> tuple[
    FileWorkspaceRepository,
    GovernedFileStreamingService,
    FileAuthorizationContext,
    _Storage,
]:
    repository = FileWorkspaceRepository(_database())
    owner = FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")
    workspace = repository.create_workspace(
        workspace_id="workspace-a",
        tenant_id="tenant-a",
        session_id="session-file",
        owner=owner,
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at=EXPIRES_AT,
        actor_id="user-a",
    )
    repository.database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id, internal_user_id,
           business_application_id, business_application_publication_id,
           task_workspace_id)
        values ('job-file', 'session-file', 'job-file-key', 'RUNNING', ?,
                'dingding_stream', 'connector-a', 'user-a', 'user-a',
                'app-file', 'app-file-p1', 'workspace-a')
        """,
        (TIMESTAMP,),
    )
    repository.create_file(
        file_id="file-source",
        tenant_id="tenant-a",
        owner=owner,
        display_name="source.txt",
        actor_id="user-a",
    )
    storage = _Storage()
    source = b"source"
    source_key = storage.new_object_key(kind="staging")
    storage.objects[source_key] = source
    repository.create_version(
        version_id="version-source-1",
        file_id="file-source",
        version_number=1,
        version_kind=FileVersionKind.WORKING,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=len(source),
        content_sha256="41cf6794ba4200b839c8ca125aef2132a40e96f5a5f9327da5309c22995239d6",
        object_key=source_key,
        source_kind=FileSourceKind.AGENT_EDITED,
        actor_id="user-a",
        advance_current_from="",
    )
    repository.link_workspace_file(
        workspace_id="workspace-a",
        file_id="file-source",
        version_id="version-source-1",
        logical_name="source.txt",
        role=WorkspaceFileRole.WORKING,
    )
    manifest = repository.create_job_snapshot(
        snapshot_id="snapshot-file",
        job_id="job-file",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
        principal_user_id="user-a",
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        manifest_hash="a" * 64,
        items=[
            {
                "file_id": "file-source",
                "version_id": "version-source-1",
                "display_name": "source.txt",
                "source_kind": SnapshotSourceKind.WORKSPACE,
                "allowed_actions": [
                    FileAction.READ_METADATA,
                    FileAction.MATERIALIZE,
                    FileAction.EDIT,
                    FileAction.COMMIT,
                ],
            }
        ],
    )
    claims = {
        "sub": "user-a",
        "tenant_id": "tenant-a",
        "job_id": "job-file",
    }
    context = FileAuthorizationContext(claims, {"id": "job-file"}, workspace, manifest)
    authorization = _Authorization(repository)
    service = GovernedFileStreamingService(
        repository,
        authorization,  # type: ignore[arg-type]
        storage,
        _Principal(context),
        now=lambda: NOW,
    )
    return repository, service, context, storage


def _new_intent(
    service: GovernedFileStreamingService,
    context: FileAuthorizationContext,
    *,
    handle: str = "sandbox-output",
) -> str:
    prepared = service.prepare_commit(
        context=context,
        arguments={
            "sandbox_entry_handle": handle,
            "display_name": f"{handle}.txt",
            "user_intent": "GENERATE",
            "delivery_mode": "DEFAULT",
        },
    )
    control = prepared.pop(INTERNAL_TRANSFER_META)[FILE_TRANSFER_META_KEY]
    assert control["sandbox_entry_handle"] == handle
    return str(control["commit_id"])


def test_commit_is_two_phase_strictly_idempotent_and_publishes_safe_outbox() -> None:
    repository, service, context, _storage = _fixture()
    commit_id = _new_intent(service, context)
    first = asyncio.run(
        service.upload_commit(
            commit_id=commit_id,
            token="file-principal-token",
            body=_body(b"generated output\n"),
        )
    )
    repeated = asyncio.run(
        service.upload_commit(
            commit_id=commit_id,
            token="file-principal-token",
            body=_body(b"generated output\n"),
        )
    )
    assert repeated == first
    assert first["status"] == "COMMITTED"
    version = repository.get_version(str(first["version_id"]))
    assert version["status"] == "AVAILABLE"
    staging = repository.database.execute_one(
        "select status from file_object_staging where commit_intent_id = (select id from file_commit_intent where commit_id = ?)",
        (commit_id,),
    )
    assert staging == {"status": "PUBLISHED"}
    outbox = repository.database.execute_one(
        "select payload_json from file_domain_outbox where aggregate_id = ?",
        (first["version_id"],),
    )
    assert outbox is not None
    payload = json.loads(str(outbox["payload_json"]))
    assert payload["version_id"] == first["version_id"]
    assert "object_key" not in payload

    with pytest.raises(NonRetryableExecutionError) as error:
        asyncio.run(
            service.upload_commit(
                commit_id=commit_id,
                token="file-principal-token",
                body=_body(b"different output\n"),
            )
        )
    assert error.value.error_code == "file_commit_idempotency_conflict"


def test_materialization_is_exact_version_job_bound_and_one_time() -> None:
    _repository, service, context, _storage = _fixture()
    prepared = service.prepare_materialization(
        context=context,
        arguments={"file_id": "file-source", "version_id": "version-source-1"},
    )
    control = prepared[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]
    async def download_once() -> tuple[bytes, str]:
        stream, media_type = await service.download_transfer(
            transfer_id=str(control["transfer_id"]), token="file-principal-token"
        )
        return b"".join([chunk async for chunk in stream]), media_type

    content, media_type = asyncio.run(download_once())
    assert content == b"source"
    assert media_type == "application/octet-stream"
    with pytest.raises(NonRetryableExecutionError) as error:
        asyncio.run(
            service.download_transfer(
                transfer_id=str(control["transfer_id"]),
                token="file-principal-token",
            )
        )
    assert error.value.error_code == "file_transfer_consumed"


def test_stale_base_creates_conflict_without_advancing_current() -> None:
    repository, service, context, storage = _fixture()
    prepared = service.prepare_commit(
        context=context,
        arguments={
            "sandbox_entry_handle": "edited-source",
            "file_id": "file-source",
            "base_version_id": "version-source-1",
            "display_name": "source.txt",
            "user_intent": "MODIFY",
            "delivery_mode": "DEFAULT",
        },
    )
    commit_id = str(
        prepared[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]["commit_id"]
    )
    concurrent_key = storage.new_object_key(kind="staging")
    storage.objects[concurrent_key] = b"concurrent"
    repository.create_version(
        version_id="version-source-2",
        file_id="file-source",
        version_number=2,
        version_kind=FileVersionKind.WORKING,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=10,
        content_sha256="0123456789abcdef" * 4,
        object_key=concurrent_key,
        source_kind=FileSourceKind.AGENT_EDITED,
        actor_id="other-job",
        parent_version_id="version-source-1",
        base_version_id="version-source-1",
        advance_current_from="version-source-1",
    )
    repository.update_workspace_file_version(
        workspace_id="workspace-a",
        file_id="file-source",
        version_id="version-source-2",
        role=WorkspaceFileRole.WORKING,
        logical_name="source.txt",
    )
    result = asyncio.run(
        service.upload_commit(
            commit_id=commit_id,
            token="file-principal-token",
            body=_body(b"my stale edit\n"),
        )
    )
    assert result["status"] == "CONFLICT"
    assert repository.get_file("file-source")["current_version_id"] == "version-source-2"
    selected = repository.database.execute_one(
        "select selected_version_id from task_workspace_file where workspace_id = 'workspace-a' and file_id = 'file-source'"
    )
    assert selected == {"selected_version_id": "version-source-2"}
    conflict = repository.database.execute_one(
        "select candidate_version_id, status from file_conflict_candidate where commit_intent_id = (select id from file_commit_intent where commit_id = ?)",
        (commit_id,),
    )
    assert conflict == {"candidate_version_id": result["version_id"], "status": "OPEN"}

    repository.database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id, internal_user_id,
           business_application_id, business_application_publication_id,
           task_workspace_id)
        values ('job-after-conflict', 'session-file', 'job-after-conflict-key',
                'PENDING', ?, 'dingding_stream', 'connector-a', 'user-a',
                'user-a', 'app-file', 'app-file-p1', 'workspace-a')
        """,
        (TIMESTAMP,),
    )
    manifest_service = JobFileManifestService(
        repository, TaskWorkspaceService(repository)
    )
    workspace = repository.get_workspace("workspace-a")
    manifest_service.register_request(
        job_id="job-after-conflict",
        workspace=workspace,
        requester_id="user-a",
        publication_id="app-file-p1",
        file_references=(),
    )
    later = manifest_service.finalize("job-after-conflict")
    assert later is not None
    identities = {
        (str(item["version_id"]), str(item["source_kind"]))
        for item in later["items"]
        if item["file_id"] == "file-source"
    }
    assert identities == {
        ("version-source-2", "WORKSPACE"),
        (str(result["version_id"]), "CONFLICT"),
    }


def test_object_and_database_failures_leave_retryable_cleanup_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, service, context, storage = _fixture()
    storage.fail_put = True
    object_failure_commit = _new_intent(service, context, handle="object-failure")
    with pytest.raises(OSError):
        asyncio.run(
            service.upload_commit(
                commit_id=object_failure_commit,
                token="file-principal-token",
                body=_body(b"will fail\n"),
            )
        )
    assert repository.database.execute_one(
        "select count(*) as value from file_cleanup_fact"
    ) == {"value": 1}

    storage.fail_put = False
    database_failure_commit = _new_intent(service, context, handle="database-failure")

    def fail_outbox(**_: Any) -> dict[str, Any]:
        raise RuntimeError("simulated database publish failure")

    monkeypatch.setattr(repository, "add_domain_outbox", fail_outbox)
    with pytest.raises(RuntimeError):
        asyncio.run(
            service.upload_commit(
                commit_id=database_failure_commit,
                token="file-principal-token",
                body=_body(b"database fail\n"),
            )
        )
    intent = repository.get_commit_intent_by_commit_id(database_failure_commit)
    assert intent["status"] == "REJECTED"
    assert repository.database.execute_one(
        "select count(*) as value from managed_file_version where content_sha256 = ?",
        (intent["content_sha256"],),
    ) == {"value": 0}
    assert repository.database.execute_one(
        "select count(*) as value from file_cleanup_fact"
    ) == {"value": 2}


def test_three_file_partial_conflict_never_rolls_back_successful_versions() -> None:
    repository, service, context, storage = _fixture()
    successful = [
        _new_intent(service, context, handle=f"output-{index}") for index in range(2)
    ]
    stale = service.prepare_commit(
        context=context,
        arguments={
            "sandbox_entry_handle": "stale-third-file",
            "file_id": "file-source",
            "base_version_id": "version-source-1",
            "display_name": "source.txt",
            "user_intent": "MODIFY",
            "delivery_mode": "WORKSPACE_ONLY",
        },
    )
    stale_commit = str(
        stale[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]["commit_id"]
    )
    concurrent_key = storage.new_object_key(kind="staging")
    storage.objects[concurrent_key] = b"new current"
    repository.create_version(
        version_id="version-source-concurrent",
        file_id="file-source",
        version_number=2,
        version_kind=FileVersionKind.WORKING,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=11,
        content_sha256="abcdef0123456789" * 4,
        object_key=concurrent_key,
        source_kind=FileSourceKind.AGENT_EDITED,
        actor_id="other-job",
        parent_version_id="version-source-1",
        base_version_id="version-source-1",
        advance_current_from="version-source-1",
    )
    repository.update_workspace_file_version(
        workspace_id="workspace-a",
        file_id="file-source",
        version_id="version-source-concurrent",
        role=WorkspaceFileRole.WORKING,
        logical_name="source.txt",
    )
    results = [
        asyncio.run(
            service.upload_commit(
                commit_id=commit_id,
                token="file-principal-token",
                body=_body(f"successful {index}\n".encode()),
            )
        )
        for index, commit_id in enumerate(successful)
    ]
    results.append(
        asyncio.run(
            service.upload_commit(
                commit_id=stale_commit,
                token="file-principal-token",
                body=_body(b"stale third edit\n"),
            )
        )
    )
    assert [result["status"] for result in results] == [
        "COMMITTED",
        "COMMITTED",
        "CONFLICT",
    ]
    assert repository.database.execute_one(
        "select count(*) as value from managed_file_version where source_kind = 'AGENT_GENERATED'"
    ) == {"value": 2}
    for result in results[:2]:
        assert repository.get_version(str(result["version_id"]))["status"] == "AVAILABLE"
    assert repository.get_file("file-source")["current_version_id"] == (
        "version-source-concurrent"
    )


def test_file_worker_attachment_import_is_idempotent_and_builds_txt_lineage() -> None:
    repository, service, _context, _storage = _fixture()
    repository.database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-attachment', 'session-file', 'job-file', 'user', '', ?, 1)
        """,
        (TIMESTAMP,),
    )
    repository.database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           retention_days, expires_at, created_at, updated_at)
        values ('attachment-txt', 'message-attachment', 'job-file', 0,
                'document', 'input.txt', 'DOWNLOADING', 360, ?, ?, ?)
        """,
        ("2027-08-09T00:00:00+00:00", TIMESTAMP, TIMESTAMP),
    )
    imported = asyncio.run(
        service.import_attachment(
            attachment_id="attachment-txt",
            service_claims={"sub": "file-worker"},
            media_type="text/plain",
            body=_body(b"hello from DingTalk\n"),
        )
    )
    repeated = asyncio.run(
        service.import_attachment(
            attachment_id="attachment-txt",
            service_claims={"sub": "file-worker"},
            media_type="text/plain",
            body=_body(b"hello from DingTalk\n"),
        )
    )
    assert repeated == imported
    assert imported["file_id"]
    assert imported["version_id"]
    assert "object_key" not in imported
    version = repository.get_version(str(imported["version_id"]))
    assert version["source_kind"] == "MESSAGE_ATTACHMENT"
    assert repository.get_file(str(imported["file_id"]))["source_received_at"] == TIMESTAMP
    assert repository.database.execute_one(
        "select provider, source_type, source_id from file_external_reference where version_id = ?",
        (imported["version_id"],),
    ) == {
        "provider": "DINGTALK",
        "source_type": "CHAT_ATTACHMENT",
        "source_id": "attachment-txt",
    }
    assert repository.database.execute_one(
        "select reason, retention_days from file_retention_fact where version_id = ?",
        (imported["version_id"],),
    ) == {"reason": "MESSAGE_ATTACHMENT", "retention_days": 360}
    with pytest.raises(NonRetryableExecutionError) as error:
        asyncio.run(
            service.import_attachment(
                attachment_id="attachment-txt",
                service_claims={"sub": "file-worker"},
                media_type="text/plain",
                body=_body(b"changed bytes\n"),
            )
        )
    assert error.value.error_code == "file_attachment_idempotency_conflict"
