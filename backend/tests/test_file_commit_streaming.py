from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.modules.audit.application.audit_service import AuditService
from app.modules.file_workspace.authorization import FileAuthorizationContext
from app.modules.document_processing import (
    DocumentProcessingRepository,
    GovernedDocumentProcessingService,
    SourceStreamGrantSigner,
)
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
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
from app.modules.file_workspace.workspace_service import TaskWorkspaceService
from app.modules.job.infrastructure.repositories import AgentRepository, AuditRepository
from app.shared.config import DeliverySettings
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
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
        assert content_type in {
            "text/plain",
            "text/markdown",
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/webp",
        }
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
        if row is None or action.value not in json.loads(
            str(row.get("allowed_actions_json") or "[]")
        ):
            raise PermissionDenied(
                "File manifest action denied",
                safe_message="当前任务无权访问该文件",
                error_code="file_manifest_item_denied",
            )
        return row

    def require_manifest_representation(
        self,
        context: FileAuthorizationContext,
        *,
        file_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        row = self.repository.database.execute_one(
            """
            select i.*, r.object_key,
                   r.size_bytes as live_representation_size_bytes,
                   r.content_sha256 as live_representation_sha256
              from agent_job_file_snapshot_item i
              join file_representation r on r.id = i.representation_id
             where i.snapshot_id = ? and i.file_id = ? and i.version_id = ?
               and r.status = 'AVAILABLE'
            """,
            (context.manifest["id"], file_id, version_id),
        )
        if row is None:
            raise PermissionDenied(
                "File representation denied",
                safe_message="当前任务无权访问该文件",
                error_code="file_representation_denied",
            )
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


def _fixture(
    *, file_format_policy_version: str = "text-v1"
) -> tuple[
    FileWorkspaceRepository,
    GovernedFileStreamingService,
    FileAuthorizationContext,
    _Storage,
]:
    repository = FileWorkspaceRepository(_database())
    repository.database.execute(
        "update business_application_publication set file_format_policy_version = ? where id = ?",
        (file_format_policy_version, "app-file-p1"),
    )
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
        file_format_policy_version=file_format_policy_version,
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
    display_name: str | None = None,
) -> str:
    prepared = service.prepare_commit(
        context=context,
        arguments={
            "sandbox_entry_handle": handle,
            "display_name": display_name or f"{handle}.txt",
            "user_intent": "GENERATE",
            "delivery_mode": "DEFAULT",
        },
    )
    control = prepared.pop(INTERNAL_TRANSFER_META)[FILE_TRANSFER_META_KEY]
    assert control["sandbox_entry_handle"] == handle
    return str(control["commit_id"])


def test_text_v2_markdown_commit_is_exact_and_log_commit_fails_before_upload() -> None:
    repository, service, context, storage = _fixture(file_format_policy_version="text-v2")
    with pytest.raises(NonRetryableExecutionError) as readonly:
        service.prepare_commit(
            context=context,
            arguments={
                "sandbox_entry_handle": "log-output",
                "display_name": "service.log",
                "user_intent": "GENERATE",
                "delivery_mode": "WORKSPACE_ONLY",
            },
        )
    assert readonly.value.error_code == "file_format_read_only"
    assert (
        repository.database.execute_one(
            "select id from file_commit_intent where sandbox_entry_handle = ?",
            ("log-output",),
        )
        is None
    )

    commit_id = _new_intent(
        service,
        context,
        handle="markdown-output",
        display_name="report.md",
    )
    first = asyncio.run(
        service.upload_commit(
            commit_id=commit_id,
            token="file-principal-token",
            body=_body(b"# report\n<script>not rendered</script>\n"),
        )
    )
    repeated = asyncio.run(
        service.upload_commit(
            commit_id=commit_id,
            token="file-principal-token",
            body=_body(b"# report\n<script>not rendered</script>\n"),
        )
    )
    assert repeated == first
    assert first["format_code"] == "MARKDOWN"
    version = repository.get_version(str(first["version_id"]))
    assert version["format_code"] == "MARKDOWN"
    assert version["media_type"] == "text/markdown"
    assert storage.objects[str(version["object_key"])] == (
        b"# report\n<script>not rendered</script>\n"
    )


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
    assert first["file_id"]
    assert first["delivery_id"] == ""
    assert first["delivery_status"] == "NOT_REQUESTED"
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


def test_duplicate_logical_name_is_rejected_before_commit_intent_or_staging() -> None:
    repository, service, context, storage = _fixture()
    before_objects = dict(storage.objects)

    with pytest.raises(NonRetryableExecutionError) as error:
        service.prepare_commit(
            context=context,
            arguments={
                "sandbox_entry_handle": "duplicate-output",
                "display_name": "source.txt",
                "user_intent": "GENERATE",
                "delivery_mode": "WORKSPACE_ONLY",
            },
        )

    assert error.value.error_code == "file_logical_name_conflict"
    assert storage.objects == before_objects
    assert repository.database.execute_one("select count(*) as value from file_commit_intent") == {
        "value": 0
    }
    assert repository.database.execute_one("select count(*) as value from file_object_staging") == {
        "value": 0
    }


def test_duplicate_logical_name_publish_race_uses_stable_error_and_compensation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, service, context, _storage = _fixture()
    commit_id = _new_intent(service, context, handle="race-output")

    def lose_name_race(**_: Any) -> dict[str, Any]:
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: task_workspace_file.workspace_id, "
            "task_workspace_file.logical_name"
        )

    monkeypatch.setattr(repository, "link_workspace_file", lose_name_race)
    with pytest.raises(NonRetryableExecutionError) as error:
        asyncio.run(
            service.upload_commit(
                commit_id=commit_id,
                token="file-principal-token",
                body=_body(b"race output\n"),
            )
        )

    assert error.value.error_code == "file_logical_name_conflict"
    intent = repository.get_commit_intent_by_commit_id(commit_id)
    assert intent["status"] == "REJECTED"
    assert intent["failure_code"] == "file_logical_name_conflict"
    assert repository.database.execute_one(
        "select count(*) as value from managed_file where display_name = 'race-output.txt'"
    ) == {"value": 0}
    assert repository.database.execute_one(
        "select status, failure_code from file_object_staging where commit_intent_id = ?",
        (intent["id"],),
    ) == {
        "status": "CLEANUP_PENDING",
        "failure_code": "file_logical_name_conflict",
    }


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


def test_manifest_v4_materializes_frozen_markdown_not_original_document() -> None:
    repository, service, context, storage = _fixture(file_format_policy_version="text-v2")
    owner = FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")
    original = b"%PDF-1.7 confidential binary"
    markdown = b"# Governed representation\n"
    original_sha256 = hashlib.sha256(original).hexdigest()
    representation_sha256 = hashlib.sha256(markdown).hexdigest()
    original_key = storage.new_object_key(kind="attachment")
    representation_key = storage.new_object_key(kind="representation")
    storage.objects[original_key] = original
    storage.objects[representation_key] = markdown
    repository.create_file(
        file_id="file-document",
        tenant_id="tenant-a",
        owner=owner,
        display_name="input.pdf",
        actor_id="file-worker",
        format_code="PDF",
    )
    repository.create_version(
        version_id="version-document-1",
        file_id="file-document",
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="application/pdf",
        encoding="",
        size_bytes=len(original),
        content_sha256=original_sha256,
        object_key=original_key,
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="file-worker",
        format_code="PDF",
        advance_current_from="",
    )
    repository.database.execute(
        """
        insert into file_processing_run
          (id, tenant_id, source_file_id, source_version_id, processor_code,
           processor_version, processor_build_digest, profile_code, profile_hash,
           status, source_size_bytes, completed_at, created_by, created_at, updated_at)
        values ('run-document', 'tenant-a', 'file-document', 'version-document-1',
                'docling-serve', '1.30.0', ?, 'docling-text-v1', ?, 'SUCCEEDED',
                ?, ?, 'file-processing-worker', ?, ?)
        """,
        ("sha256:" + "c" * 64, "d" * 64, len(original), TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    repository.database.execute(
        """
        insert into file_representation
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           kind, media_type, encoding, status, size_bytes, content_sha256,
           object_key, profile_hash, created_at)
        values ('representation-document-md', 'run-document', 'tenant-a',
                'file-document', 'version-document-1', 'MARKDOWN', 'text/markdown',
                'utf-8', 'AVAILABLE', ?, ?, ?, ?, ?)
        """,
        (len(markdown), representation_sha256, representation_key, "d" * 64, TIMESTAMP),
    )
    repository.database.execute(
        """
        insert into agent_job_file_snapshot_item
          (id, snapshot_id, ordinal, file_id, version_id, display_name, format_code,
           source_kind, allowed_actions_json, auto_materialize, conflict_candidate,
           version_created_at, representation_id, representation_kind,
           representation_size_bytes, representation_sha256,
           representation_format_code, representation_created_at, created_at)
        values ('snapshot-item-document', 'snapshot-file', 1, 'file-document',
                'version-document-1', 'input.pdf', 'PDF', 'CURRENT_MESSAGE', ?, 1, 0,
                ?, 'representation-document-md', 'MARKDOWN', ?, ?, 'MARKDOWN', ?, ?)
        """,
        (
            json.dumps(["READ_METADATA", "RETAIN", "DELIVER"]),
            TIMESTAMP,
            len(markdown),
            representation_sha256,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )

    prepared = service.prepare_materialization(
        context=context,
        arguments={"file_id": "file-document", "version_id": "version-document-1"},
    )
    control = prepared[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]
    assert control["relative_path"].startswith("inputs/readonly/")
    assert control["relative_path"].endswith(".md")
    assert control["expected_sha256"] == representation_sha256
    assert prepared["allowed_actions"] == [FileAction.MATERIALIZE.value]
    same_name = service.prepare_materialization(
        context=context,
        arguments={
            "file_id": "file-document",
            "version_id": "version-document-1",
            "preferred_name": "input.md",
        },
    )
    same_name_control = same_name[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]
    assert same_name_control["relative_path"] != control["relative_path"]
    assert same_name_control["relative_path"].startswith("inputs/readonly/input-")

    async def download() -> bytes:
        stream, _media_type = await service.download_transfer(
            transfer_id=str(control["transfer_id"]), token="file-principal-token"
        )
        return b"".join([chunk async for chunk in stream])

    assert asyncio.run(download()) == markdown
    assert original != markdown

    tampered = service.prepare_materialization(
        context=context,
        arguments={"file_id": "file-document", "version_id": "version-document-1"},
    )
    repository.database.execute(
        """
        update file_representation
           set size_bytes = size_bytes + 1, content_sha256 = ?
         where id = 'representation-document-md'
        """,
        ("f" * 64,),
    )
    with pytest.raises(NonRetryableExecutionError) as integrity_error:
        asyncio.run(
            service.download_transfer(
                transfer_id=str(
                    tampered[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]["transfer_id"]
                ),
                token="file-principal-token",
            )
        )
    assert integrity_error.value.error_code == "file_transfer_integrity_mismatch"

    repository.database.execute(
        """
        update file_representation
           set status = 'CONTENT_UNAVAILABLE', content_deleted_at = ?
         where id = 'representation-document-md'
        """,
        (TIMESTAMP,),
    )
    with pytest.raises(NonRetryableExecutionError) as expired:
        service.prepare_materialization(
            context=context,
            arguments={"file_id": "file-document", "version_id": "version-document-1"},
        )
    assert expired.value.error_code == "file_readable_content_not_ready"


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
    commit_id = str(prepared[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]["commit_id"])
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
    manifest_service = JobFileManifestService(repository, TaskWorkspaceService(repository))
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
    assert repository.database.execute_one("select count(*) as value from file_cleanup_fact") == {
        "value": 1
    }

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
    assert repository.database.execute_one("select count(*) as value from file_cleanup_fact") == {
        "value": 2
    }


def test_three_file_partial_conflict_never_rolls_back_successful_versions() -> None:
    repository, service, context, storage = _fixture()
    successful = [_new_intent(service, context, handle=f"output-{index}") for index in range(2)]
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
    stale_commit = str(stale[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]["commit_id"])
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
    assert repository.get_file("file-source")["current_version_id"] == ("version-source-concurrent")


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


def test_file_worker_document_import_sniffs_source_and_queues_processing() -> None:
    repository, existing_service, context, storage = _fixture(file_format_policy_version="text-v2")
    repository.database.execute(
        """
        update business_application_publication
           set document_processing_profile_code = 'docling-text-v1',
               document_processing_profile_version = '1',
               document_processing_profile_hash = ?
         where id = 'app-file-p1'
        """,
        ("337dc23bd405e7225e8ffca06b72852ed19121723bc8b1abeafdc05cf5ceac42",),
    )
    document_processing = GovernedDocumentProcessingService(
        DocumentProcessingRepository(repository.database),
        repository,
        storage,
        SourceStreamGrantSigner(b"document-processing-test-signing-key-32"),
        AuditService(AuditRepository(repository.database)),
        processor_version="1.30.0",
        processor_build_digest="sha256:" + "a" * 64,
    )
    service = GovernedFileStreamingService(
        repository,
        existing_service.authorization,
        storage,
        _Principal(context),
        now=lambda: NOW,
        document_processing=document_processing,
    )
    repository.database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-document', 'session-file', 'job-file', 'user', '', ?, 2)
        """,
        (TIMESTAMP,),
    )
    repository.database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           retention_days, expires_at, created_at, updated_at)
        values ('attachment-pdf', 'message-document', 'job-file', 0,
                'application/pdf', 'input.pdf', 'DOWNLOADING', 360, ?, ?, ?)
        """,
        ("2027-08-09T00:00:00+00:00", TIMESTAMP, TIMESTAMP),
    )
    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf)
    imported = asyncio.run(
        service.import_attachment(
            attachment_id="attachment-pdf",
            service_claims={"sub": "file-worker"},
            media_type="application/pdf",
            body=_body(pdf.getvalue()),
        )
    )
    version = repository.get_version(str(imported["version_id"]))
    assert version["format_code"] == "PDF"
    assert version["media_type"] == "application/pdf"
    attachment = repository.database.execute_one(
        """
        select readability_status, file_processing_run_id, readability_error_code
          from message_attachment where id = 'attachment-pdf'
        """
    )
    assert attachment is not None
    assert attachment["readability_status"] == "PENDING"
    assert attachment["file_processing_run_id"]
    assert attachment["readability_error_code"] == ""
    with pytest.raises(NonRetryableExecutionError) as pending_materialize:
        service.prepare_materialization(
            context=context,
            arguments={
                "file_id": str(imported["file_id"]),
                "version_id": str(imported["version_id"]),
            },
        )
    assert pending_materialize.value.error_code == "file_readable_content_not_ready"
    assert repository.database.execute_one(
        "select count(*) as value from file_materialization_transfer"
    ) == {"value": 0}
    run = document_processing.repository.get_run(str(attachment["file_processing_run_id"]))
    assert run["source_version_id"] == imported["version_id"]
    assert run["status"] == "QUEUED"
    assert repository.database.execute_one(
        """
        select count(*) as value from file_domain_outbox
         where event_type = 'file.processing.requested' and aggregate_id = ?
        """,
        (run["id"],),
    ) == {"value": 1}

    repository.database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           retention_days, expires_at, created_at, updated_at)
        values ('attachment-pdf-bad', 'message-document', 'job-file', 1,
                'application/pdf', 'bad.pdf', 'DOWNLOADING', 360, ?, ?, ?)
        """,
        ("2027-08-09T00:00:00+00:00", TIMESTAMP, TIMESTAMP),
    )
    with pytest.raises(NonRetryableExecutionError) as malformed:
        asyncio.run(
            service.import_attachment(
                attachment_id="attachment-pdf-bad",
                service_claims={"sub": "file-worker"},
                media_type="application/pdf",
                body=_body(b"not a pdf"),
            )
        )
    assert malformed.value.error_code == "document_source_signature_mismatch"


def test_file_worker_canonicalizes_misnamed_images_and_disambiguates_names() -> None:
    repository, existing_service, context, storage = _fixture(file_format_policy_version="text-v2")
    repository.database.execute(
        """
        update business_application_publication
           set document_processing_profile_code = 'docling-text-v1',
               document_processing_profile_version = '1',
               document_processing_profile_hash = ?
         where id = 'app-file-p1'
        """,
        ("337dc23bd405e7225e8ffca06b72852ed19121723bc8b1abeafdc05cf5ceac42",),
    )
    document_processing = GovernedDocumentProcessingService(
        DocumentProcessingRepository(repository.database),
        repository,
        storage,
        SourceStreamGrantSigner(b"document-processing-test-signing-key-32"),
        AuditService(AuditRepository(repository.database)),
        processor_version="1.30.0",
        processor_build_digest="sha256:" + "a" * 64,
    )
    service = GovernedFileStreamingService(
        repository,
        existing_service.authorization,
        storage,
        _Principal(context),
        now=lambda: NOW,
        document_processing=document_processing,
    )
    repository.database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-images', 'session-file', 'job-file', 'user', '', ?, 2)
        """,
        (TIMESTAMP,),
    )
    image = io.BytesIO()
    Image.new("RGB", (3, 2), color="white").save(image, format="JPEG")
    body = image.getvalue()
    imported: list[dict[str, Any]] = []
    for ordinal, attachment_id in enumerate(
        ("attachment-misnamed-image-1", "attachment-misnamed-image-2")
    ):
        repository.database.execute(
            """
            insert into message_attachment
              (id, message_id, job_id, ordinal, media_type, file_name, status,
               retention_days, expires_at, created_at, updated_at)
            values (?, 'message-images', 'job-file', ?,
                    'image', 'channel-image.png', 'DOWNLOADING', 360, ?, ?, ?)
            """,
            (
                attachment_id,
                ordinal,
                "2027-08-09T00:00:00+00:00",
                TIMESTAMP,
                TIMESTAMP,
            ),
        )
        imported.append(
            asyncio.run(
                service.import_attachment(
                    attachment_id=attachment_id,
                    service_claims={"sub": "file-worker"},
                    media_type="image/jpeg",
                    body=_body(body),
                )
            )
        )

    versions = [repository.get_version(str(item["version_id"])) for item in imported]
    files = [repository.get_file(str(item["file_id"])) for item in imported]
    assert [item["format_code"] for item in versions] == ["JPEG", "JPEG"]
    assert [item["media_type"] for item in versions] == ["image/jpeg", "image/jpeg"]
    assert files[0]["display_name"] == "channel-image.jpg"
    assert files[1]["display_name"].startswith("channel-image-")
    assert files[1]["display_name"].endswith(".jpg")
    assert files[1]["display_name"] != files[0]["display_name"]
    assert repository.database.execute_one(
        "select count(*) as value from file_processing_run where source_file_id in (?, ?)",
        (imported[0]["file_id"], imported[1]["file_id"]),
    ) == {"value": 2}


def test_unreadable_document_rejects_materialization_but_allows_original_delivery() -> None:
    repository, service, context, storage = _fixture()
    owner = FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")
    original = b"%PDF-1.4 pending source\n"
    object_key = storage.new_object_key(kind="attachment")
    storage.objects[object_key] = original
    repository.create_file(
        file_id="file-pending-pdf",
        tenant_id="tenant-a",
        owner=owner,
        display_name="pending.pdf",
        actor_id="file-worker",
        format_code="PDF",
    )
    repository.create_version(
        version_id="version-pending-pdf",
        file_id="file-pending-pdf",
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="application/pdf",
        encoding="",
        size_bytes=len(original),
        content_sha256=hashlib.sha256(original).hexdigest(),
        object_key=object_key,
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="file-worker",
        format_code="PDF",
        advance_current_from="",
    )
    repository.link_workspace_file(
        workspace_id="workspace-a",
        file_id="file-pending-pdf",
        version_id="version-pending-pdf",
        logical_name="pending.pdf",
        role=WorkspaceFileRole.INPUT,
    )
    repository.database.execute(
        """
        insert into agent_job_file_snapshot_item
          (id, snapshot_id, ordinal, file_id, version_id, display_name, format_code,
           source_kind, allowed_actions_json, auto_materialize, conflict_candidate,
           version_created_at, created_at)
        values ('snapshot-item-pending-pdf', 'snapshot-file', 2, 'file-pending-pdf',
                'version-pending-pdf', 'pending.pdf', 'PDF', 'CURRENT_MESSAGE', ?, 0, 0, ?, ?)
        """,
        (
            json.dumps(
                [
                    FileAction.READ_METADATA.value,
                    FileAction.MATERIALIZE.value,
                    FileAction.RETAIN.value,
                    FileAction.DELIVER.value,
                ]
            ),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    repository.database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-pending-pdf', 'session-file', 'job-file', 'user', '', ?, 3)
        """,
        (TIMESTAMP,),
    )
    repository.database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           readability_status, retention_days, expires_at, created_at, updated_at)
        values ('attachment-pending-pdf', 'message-pending-pdf', 'job-file', 0,
                'application/pdf', 'pending.pdf', 'READY', 'PENDING', 360, ?, ?, ?)
        """,
        ("2027-08-09T00:00:00+00:00", TIMESTAMP, TIMESTAMP),
    )
    repository.database.execute(
        """
        insert into message_attachment_file_binding
          (attachment_id, file_id, version_id, retention_expires_at, created_at)
        values ('attachment-pending-pdf', 'file-pending-pdf', 'version-pending-pdf', ?, ?)
        """,
        ("2027-08-09T00:00:00+00:00", TIMESTAMP),
    )
    refreshed = FileAuthorizationContext(
        context.claims,
        context.job,
        context.workspace,
        repository.get_job_snapshot("job-file"),
    )
    with pytest.raises(NonRetryableExecutionError) as pending:
        service.prepare_materialization(
            context=refreshed,
            arguments={"file_id": "file-pending-pdf", "version_id": "version-pending-pdf"},
        )
    assert pending.value.error_code == "file_readable_content_not_ready"
    repository.database.execute(
        """
        update message_attachment
           set readability_status = 'UNAVAILABLE'
         where id = 'attachment-pending-pdf'
        """
    )
    with pytest.raises(NonRetryableExecutionError) as failed:
        service.prepare_materialization(
            context=refreshed,
            arguments={"file_id": "file-pending-pdf", "version_id": "version-pending-pdf"},
        )
    assert failed.value.error_code == "file_processing_failed"
    assert repository.database.execute_one(
        "select count(*) as value from file_materialization_transfer"
    ) == {"value": 0}

    service.delivery_intents = FileVersionDeliveryService(
        repository,
        AgentRepository(repository.database),
        DeliverySettings(),
    )
    delivered = service.deliver_version(
        context=refreshed,
        arguments={"file_id": "file-pending-pdf", "version_id": "version-pending-pdf"},
    )
    assert delivered["file_id"] == "file-pending-pdf"
    assert delivered["version_id"] == "version-pending-pdf"
    assert delivered["delivery_status"]
