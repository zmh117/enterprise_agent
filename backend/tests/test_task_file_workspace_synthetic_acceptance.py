from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.modules.audit.application.audit_service import AuditService
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.attachments.domain import AttachmentImportReceipt
from app.modules.delivery.application.delivery_dispatch_service import (
    DeliveryOutboxDispatcher,
)
from app.modules.document_processing import (
    DocumentProcessingRepository,
    GovernedDocumentProcessingService,
    SourceStreamGrantSigner,
)
from app.modules.file_workspace.application import FileWorkspaceApplicationService
from app.modules.file_workspace.authorization import (
    FileAuthorizationContext,
    FileAuthorizationService,
)
from app.modules.file_workspace.contracts import FILE_TRANSFER_META_KEY
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
from app.modules.file_workspace.domain import (
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionReason,
    WorkspaceFileRole,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.streaming_service import GovernedFileStreamingService
from app.modules.file_workspace.streaming_service import INTERNAL_TRANSFER_META
from app.modules.job.infrastructure.repositories import AgentRepository, AuditRepository
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.api.agent_job_debug_controller import _file_workspace_evidence
from app.modules.message_bus.application.message_publisher import ChannelEventMessage
from app.python_runtime.file_transfer import (
    FileTransferContext,
    FileTransferCoordinator,
    FileUploadReceipt,
)
from app.python_runtime.job_sandbox import JobSandboxManager
from app.shared.config import DeliverySettings
from backend.tests.test_continuous_multimodal_conversations import (
    FakeDownloader,
    RecordingAttachmentImporter,
    load_fixture,
    multimodal_container,
)
from backend.tests.test_file_authorization import _BusinessAccess
from backend.tests.test_file_commit_streaming import NOW, _Storage
from backend.tests.test_file_version_delivery import (
    _Authorization as _DeliveryAuthorization,
)
from backend.tests.test_file_version_delivery import (
    _ResponseLostSender,
    _StreamFileConnectorRegistry,
)


FEATURES = {
    "workspace_enabled": True,
    "file_mcp_enabled": True,
    "runtime_file_edit_enabled": True,
    "default_file_delivery_enabled": True,
}


def _group_text(
    *,
    msg_id: str,
    content: str,
    original_msg_id: str = "",
    conversation_id: str = "group-conversation-redacted",
) -> dict[str, object]:
    payload = load_fixture("group_text.json")
    payload["conversationId"] = conversation_id
    payload["msgId"] = msg_id
    payload["text"] = {"content": content}
    if original_msg_id:
        payload["originalMsgId"] = original_msg_id
    return payload


def _latest_system_notice(runtime: Any) -> dict[str, Any]:
    row = runtime.database.execute_one(
        """
        select id, job_id, session_id, delivery_kind, delivery_binding_json
          from delivery_outbox
         where delivery_kind = 'SYSTEM_NOTICE'
         order by created_at desc, id desc
        """
    )
    assert row is not None
    binding = json.loads(str(row["delivery_binding_json"] or "{}"))
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "session_id": row["session_id"],
        "title": str(binding.get("title") or ""),
        "markdown": str(binding.get("markdown") or ""),
        "reason_code": str(binding.get("reason_code") or ""),
        "notice_kind": str(binding.get("notice_kind") or ""),
    }


def _mark_readability(runtime: Any, *, file_name: str, status: str) -> None:
    runtime.database.execute(
        """
        update message_attachment
           set readability_status = ?, readability_updated_at = ?
         where file_name = ?
        """,
        (status, datetime.now(UTC).isoformat(), file_name),
    )


def _mcp_wire_result(result: dict[str, Any]) -> dict[str, Any]:
    value = dict(result)
    meta = value.pop(INTERNAL_TRANSFER_META)
    return {**value, "_meta": meta}


class _MutablePrincipal:
    context: FileAuthorizationContext | None = None

    def authenticate(
        self,
        token: str,
        *,
        tool_identifier: str = "task_workspace_get",
    ) -> tuple[dict[str, Any], FileAuthorizationContext, tuple[str, ...]]:
        assert token == "synthetic-principal"
        assert self.context is not None
        return self.context.claims, self.context, (tool_identifier,)


class _InProcessAttachmentImporter:
    def __init__(self, service: GovernedFileStreamingService) -> None:
        self.service = service

    def import_content(
        self,
        *,
        attachment_id: str,
        data: bytes,
        content_type: str,
    ) -> AttachmentImportReceipt:
        async def body() -> Any:
            yield data[:7]
            yield data[7:]

        result = asyncio.run(
            self.service.import_attachment(
                attachment_id=attachment_id,
                service_claims={"sub": "file-worker"},
                media_type=content_type,
                body=body(),
            )
        )
        return AttachmentImportReceipt(
            attachment_id=str(result["attachment_id"]),
            size_bytes=int(result["size_bytes"]),
            sha256=str(result["sha256"]),
            file_id=str(result["file_id"]),
            version_id=str(result["version_id"]),
            readability_status=str(result.get("readability_status") or "NOT_REQUIRED"),
            processing_run_id=str(result.get("processing_run_id") or ""),
        )


class _RecordingMcpSnapshotService:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.allowed_server_codes: frozenset[str] | None = None

    def freeze(self, **kwargs: Any) -> dict[str, Any]:
        self.allowed_server_codes = kwargs.get("allowed_server_codes")
        return self.delegate.freeze(**kwargs)

    def verify(self, job_id: str) -> dict[str, Any]:
        return self.delegate.verify(job_id)


class _StreamingPort:
    def __init__(self, service: GovernedFileStreamingService) -> None:
        self.service = service

    def download(
        self,
        *,
        transfer_id: str,
        job_id: str,
        principal_token: str,
    ) -> Iterable[bytes]:
        del job_id

        async def collect() -> list[bytes]:
            stream, _media_type = await self.service.download_transfer(
                transfer_id=transfer_id,
                token=principal_token,
            )
            return [chunk async for chunk in stream]

        return asyncio.run(collect())

    def upload(
        self,
        *,
        commit_id: str,
        job_id: str,
        principal_token: str,
        content: Iterable[bytes],
    ) -> FileUploadReceipt:
        del job_id
        chunks = list(content)

        async def body() -> Any:
            for chunk in chunks:
                yield chunk

        result = asyncio.run(
            self.service.upload_commit(
                commit_id=commit_id,
                token=principal_token,
                body=body(),
            )
        )
        return FileUploadReceipt(
            file_id=str(result["file_id"]),
            version_id=str(result["version_id"]),
            size_bytes=int(result["size_bytes"]),
            sha256=str(result["sha256"]),
            status=str(result["status"]),
            delivery_id=str(result["delivery_id"]),
            delivery_status=str(result["delivery_status"]),
        )


def _enable_in_process_attachment_import(
    runtime: Any,
) -> tuple[FileWorkspaceRepository, _Storage]:
    file_repository = FileWorkspaceRepository(runtime.database)
    storage = _Storage()
    streaming = GovernedFileStreamingService(
        file_repository,
        FileAuthorizationService(runtime.database, _BusinessAccess()),
        storage,
        _MutablePrincipal(),
        now=lambda: NOW,
    )
    runtime.attachment_service.importer = _InProcessAttachmentImporter(streaming)
    runtime.attachment_service.storage = None
    return file_repository, storage


def _enable_in_process_document_import(
    runtime: Any,
) -> tuple[FileWorkspaceRepository, _Storage]:
    file_repository = FileWorkspaceRepository(runtime.database)
    storage = _Storage()
    document_processing = GovernedDocumentProcessingService(
        DocumentProcessingRepository(runtime.database),
        file_repository,
        storage,
        SourceStreamGrantSigner(b"synthetic-document-source-grant-key"),
        AuditService(AuditRepository(runtime.database)),
        processor_version="1.30.0",
        processor_build_digest="sha256:" + "a" * 64,
    )
    streaming = GovernedFileStreamingService(
        file_repository,
        FileAuthorizationService(runtime.database, _BusinessAccess()),
        storage,
        _MutablePrincipal(),
        now=lambda: NOW,
        document_processing=document_processing,
    )
    runtime.attachment_service.importer = _InProcessAttachmentImporter(streaming)
    runtime.attachment_service.storage = None
    return file_repository, storage


SHANGHAI = ZoneInfo("Asia/Shanghai")
FROZEN_TODAY = datetime(2026, 8, 19, 12, 0, tzinfo=SHANGHAI)
FROZEN_MONDAY = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
LAST_WEEK_RECEIVED_AT = "2026-08-12T04:00:00+00:00"
TODAY_RECEIVED_AT = "2026-08-19T01:40:47+00:00"


def _freeze_resolver_now(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    monkeypatch.setattr(
        "app.modules.job.application.create_agent_job_service.resolver_now",
        lambda: now,
    )


def _expire_active_workspaces(runtime: Any) -> None:
    timestamp = datetime.now(UTC).isoformat()
    rows = runtime.database.execute("select id from task_workspace where status = 'ACTIVE'")
    for row in rows:
        runtime.database.execute(
            "update task_workspace set status = 'CLEANED', updated_at = ? where id = ?",
            (timestamp, row["id"]),
        )
        runtime.database.execute(
            """
            update task_workspace_file
               set status = 'REMOVED', removed_at = ?, updated_at = ?
             where workspace_id = ? and status = 'ACTIVE'
            """,
            (timestamp, timestamp, row["id"]),
        )


def _backdate_file(runtime: Any, *, file_id: str, received_at: str) -> None:
    runtime.database.execute(
        "update managed_file set source_received_at = ? where id = ?",
        (received_at, file_id),
    )


def _snapshot_items(runtime: Any, snapshot_id: str) -> list[dict[str, Any]]:
    return runtime.database.execute(
        """
        select display_name, source_kind, auto_materialize, file_id, version_id,
               allowed_actions_json
          from agent_job_file_snapshot_item
         where snapshot_id = ?
         order by ordinal
        """,
        (snapshot_id,),
    )


def _import_channel_file(
    runtime: Any,
    *,
    msg_id: str,
    file_name: str,
    content_type: str,
    data: bytes,
) -> dict[str, Any]:
    payload = load_fixture("file.json")
    payload["msgId"] = msg_id
    payload["content"] = {
        "downloadCode": f"{msg_id}-code",
        "fileName": file_name,
        "fileSize": len(data),
        "contentType": content_type,
    }
    staged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id=msg_id,
    )
    assert staged.status == "attachments_staged", (staged.reason, staged.error_code)
    task = runtime.message_bus.attachments.popleft()
    runtime.attachment_service.downloader = FakeDownloader({f"{msg_id}-code": data})
    runtime.attachment_service.process(task.attachment_id, msg_id)
    binding = runtime.database.execute_one(
        """
        select b.file_id, b.version_id, a.file_name
          from message_attachment_file_binding b
          join message_attachment a on a.id = b.attachment_id
         where a.id = ?
        """,
        (task.attachment_id,),
    )
    assert binding is not None
    return dict(binding)


def test_duplicate_original_attachment_names_use_readable_sequence() -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
    )
    _enable_in_process_attachment_import(runtime)

    _import_channel_file(
        runtime,
        msg_id="duplicate-original-name-1",
        file_name="生产记录.txt",
        content_type="text/plain",
        data=b"first\n",
    )
    _import_channel_file(
        runtime,
        msg_id="duplicate-original-name-2",
        file_name="生产记录.txt",
        content_type="text/plain",
        data=b"second\n",
    )

    rows = runtime.database.execute(
        """
        select logical_name from task_workspace_file
         where status = 'ACTIVE'
         order by logical_name
        """
    )
    assert [row["logical_name"] for row in rows] == [
        "生产记录 (2).txt",
        "生产记录.txt",
    ]


def test_unnamed_native_pictures_use_time_name_real_extension_and_sequence() -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
        document_processing_profile_code="docling-text-v1",
    )
    _enable_in_process_document_import(runtime)
    image = Image.new("RGB", (2, 2), "red")
    output = io.BytesIO()
    image.save(output, format="JPEG")
    source = output.getvalue()
    created_at = int(datetime(2026, 8, 19, 1, 40, 47, tzinfo=UTC).timestamp() * 1000)

    for sequence in (1, 2):
        payload = load_fixture("picture.json")
        payload["msgId"] = f"unnamed-native-picture-{sequence}"
        payload["createAt"] = created_at
        payload["content"] = {"downloadCode": f"unnamed-native-picture-{sequence}-code"}
        staged = runtime.dingtalk_stream_message_service.handle_callback(
            payload=payload,
            correlation_id=str(payload["msgId"]),
        )
        assert staged.status == "attachments_staged", (staged.reason, staged.error_code)
        task = runtime.message_bus.attachments.popleft()
        runtime.attachment_service.downloader = FakeDownloader(
            {f"unnamed-native-picture-{sequence}-code": source}
        )
        runtime.attachment_service.process(task.attachment_id, str(payload["msgId"]))

    rows = runtime.database.execute(
        """
        select logical_name from task_workspace_file
         where status = 'ACTIVE'
         order by logical_name
        """
    )
    assert [row["logical_name"] for row in rows] == [
        "图片-20260819-094047 (2).jpg",
        "图片-20260819-094047.jpg",
    ]


def _attach_markdown_representation(
    runtime: Any,
    *,
    file_id: str,
    version_id: str,
    markdown: bytes = b"caption\n",
) -> None:
    tenant = runtime.database.execute_one(
        "select tenant_id from managed_file where id = ?",
        (file_id,),
    )
    assert tenant is not None
    run_id = f"run-{version_id}"
    timestamp = datetime.now(UTC).isoformat()
    runtime.database.execute(
        """
        insert into file_processing_run
          (id, tenant_id, source_file_id, source_version_id, processor_code,
           processor_version, processor_build_digest, profile_code, profile_hash,
           status, source_size_bytes, completed_at, created_by, created_at, updated_at)
        values (?, ?, ?, ?, 'docling-serve', '1.30.0', ?, 'docling-text-v1', ?,
                'SUCCEEDED', ?, ?, 'file-processing-worker', ?, ?)
        """,
        (
            run_id,
            tenant["tenant_id"],
            file_id,
            version_id,
            "sha256:" + "b" * 64,
            "d" * 64,
            len(markdown),
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into file_representation
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           kind, media_type, encoding, status, size_bytes, content_sha256,
           object_key, profile_hash, created_at)
        values (?, ?, ?, ?, ?, 'MARKDOWN', 'text/markdown', 'utf-8', 'AVAILABLE',
                ?, ?, ?, ?, ?)
        """,
        (
            f"representation-{version_id}",
            run_id,
            tenant["tenant_id"],
            file_id,
            version_id,
            len(markdown),
            "e" * 64,
            f"opaque/representation-{version_id}",
            "d" * 64,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        update message_attachment
           set readability_status = 'AVAILABLE', readability_updated_at = ?
         where id in (
           select attachment_id from message_attachment_file_binding where version_id = ?
         )
        """,
        (timestamp, version_id),
    )


def _workspace_owner(workspace: dict[str, Any]) -> FileOwner:
    owner_type = WorkspaceOwnerType(str(workspace["owner_type"]))
    if owner_type is WorkspaceOwnerType.PRIVATE_USER:
        return FileOwner(owner_type, user_id=str(workspace["owner_user_id"]))
    return FileOwner(
        owner_type,
        enterprise_id=str(workspace["owner_enterprise_id"]),
        connector_id=str(workspace["owner_connector_id"]),
        conversation_id=str(workspace["owner_conversation_id"]),
    )


def _seed_png_with_session_attachment(
    runtime: Any,
    file_repository: FileWorkspaceRepository,
    *,
    file_id: str,
    version_id: str,
    display_name: str,
    received_at: str,
) -> None:
    workspace = runtime.database.execute_one(
        "select * from task_workspace where status = 'ACTIVE'"
    )
    assert workspace is not None
    file_repository.create_file(
        file_id=file_id,
        tenant_id=str(workspace["tenant_id"]),
        owner=_workspace_owner(workspace),
        display_name=display_name,
        actor_id="file-worker",
        format_code="PNG",
        source_received_at=received_at,
    )
    file_repository.create_version(
        version_id=version_id,
        file_id=file_id,
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="image/png",
        encoding="",
        size_bytes=12,
        content_sha256="f" * 64,
        object_key=f"opaque/{version_id}",
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="file-worker",
        format_code="PNG",
        advance_current_from="",
    )
    file_repository.link_workspace_file(
        workspace_id=str(workspace["id"]),
        file_id=file_id,
        version_id=version_id,
        logical_name=display_name,
        role=WorkspaceFileRole.INPUT,
    )
    message_id = runtime.agent_repository.add_message(
        session_id=str(workspace["session_id"]),
        job_id=None,
        role="user",
        content="",
        external_message_id=f"seed-{file_id}",
        message_type="file",
    )
    timestamp = datetime.now(UTC).isoformat()
    attachment_id = f"attachment-{file_id}"
    retention_expires_at = "2027-08-14T00:00:00+00:00"
    runtime.database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, declared_mime,
           declared_size, status, readability_status, task_workspace_id,
           retention_days, expires_at, created_at, updated_at,
           readability_updated_at, finished_at)
        values (?, ?, null, 0, 'image/png', ?, 'image/png', 12, 'READY', 'AVAILABLE',
                ?, 360, ?, ?, ?, ?, ?)
        """,
        (
            attachment_id,
            message_id,
            display_name,
            workspace["id"],
            retention_expires_at,
            timestamp,
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    file_repository.bind_attachment(
        attachment_id=attachment_id,
        file_id=file_id,
        version_id=version_id,
        retention_expires_at=retention_expires_at,
    )
    file_repository.add_retention(
        version_id=version_id,
        reason=RetentionReason.MESSAGE_ATTACHMENT,
        source_id=attachment_id,
        starts_at=received_at,
        expires_at=retention_expires_at,
    )
    _attach_markdown_representation(runtime, file_id=file_id, version_id=version_id)


def test_unsupported_picture_then_plain_text_does_not_freeze_file_mcp_tools() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    snapshot_service = _RecordingMcpSnapshotService(runtime.mcp_tool_snapshot_service)
    runtime.create_agent_job_service.mcp_tool_snapshot_service = snapshot_service

    picture = load_fixture("picture.json")
    picture["msgId"] = "unsupported-picture-before-plain-text"
    rejected = runtime.dingtalk_stream_message_service.handle_callback(
        payload=picture,
        correlation_id="unsupported-picture-before-plain-text",
    )
    assert rejected.accepted is False
    assert rejected.error_code == "file_workspace_type_unsupported"

    payload = load_fixture("direct_text.json")
    payload["msgId"] = "plain-text-with-file-enabled-publication"
    payload["text"] = {"content": "只回答这个普通文字问题"}

    accepted = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="plain-text-without-workspace",
    )

    job = runtime.agent_repository.get_job(accepted.job_id)
    assert job.task_workspace_id == ""
    assert job.business_application_route_decision["task_file_features"]["file_mcp_enabled"] is True
    assert snapshot_service.allowed_server_codes is not None
    assert "file-service" not in snapshot_service.allowed_server_codes
    frozen = snapshot_service.verify(job.id)
    server_codes = {str(item["server_code"]) for item in frozen["snapshot"]["tools"]}
    assert "file-service" not in server_codes


@pytest.mark.parametrize(
    ("file_name", "content_type"),
    (
        ("scan.png", "image/png"),
        ("scan.jpg", "image/jpeg"),
        ("scan.webp", "image/webp"),
        (
            "report.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (
            "table.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("report.pdf", "application/pdf"),
    ),
)
def test_docling_profile_stages_supported_document_attachments(
    file_name: str,
    content_type: str,
) -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
        document_processing_profile_code="docling-text-v1",
    )
    suffix = Path(file_name).suffix[1:]
    payload = load_fixture("file.json")
    payload["msgId"] = f"docling-stage-{suffix}"
    payload["content"] = {
        "downloadCode": f"download-{suffix}",
        "fileName": file_name,
        "fileSize": 1024,
        "contentType": content_type,
    }

    staged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id=str(payload["msgId"]),
    )

    assert staged.status == "attachments_staged", (staged.reason, staged.error_code)
    assert runtime.agent_repository.count_rows("agent_job") == 0
    assert len(runtime.message_bus.attachments) == 1


def test_old_publication_keeps_document_profile_none_behavior() -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
        document_processing_profile_code="NONE",
    )
    payload = load_fixture("file.json")
    payload["msgId"] = "legacy-none-docx"
    payload["content"] = {
        "downloadCode": "legacy-none-docx",
        "fileName": "legacy.docx",
        "fileSize": 1024,
        "contentType": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    }

    rejected = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="legacy-none-docx",
    )

    assert rejected.accepted is False
    assert rejected.error_code == "file_workspace_type_unsupported"
    assert runtime.agent_repository.count_rows("message_attachment") == 0
    assert runtime.agent_repository.count_rows("file_processing_run") == 0


def test_document_duplicate_ingress_and_job_replay_do_not_duplicate_facts() -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
        document_processing_profile_code="docling-text-v1",
    )
    _enable_in_process_document_import(runtime)
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    source = output.getvalue()
    payload = load_fixture("file.json")
    payload["msgId"] = "document-replay-pdf"
    payload["content"] = {
        "downloadCode": "document-replay-pdf",
        "fileName": "replay.pdf",
        "fileSize": len(source),
        "contentType": "application/pdf",
    }

    first_ingress = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="document-replay-pdf-1",
    )
    replayed_ingress = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="document-replay-pdf-2",
    )
    assert first_ingress.status == "attachments_staged"
    assert replayed_ingress.status == "attachments_staged"
    assert runtime.agent_repository.count_rows("message_attachment") == 1
    assert len(runtime.message_bus.attachments) == 1

    task = runtime.message_bus.attachments.popleft()
    runtime.attachment_service.downloader = FakeDownloader(
        {"document-replay-pdf": source}
    )
    assert runtime.attachment_service.process(task.attachment_id, task.correlation_id) == (
        "staged"
    )
    attachment = runtime.database.execute_one(
        """
        select a.file_processing_run_id, b.file_id, b.version_id
          from message_attachment a
          join message_attachment_file_binding b on b.attachment_id = a.id
         where a.id = ?
        """,
        (task.attachment_id,),
    )
    assert attachment is not None
    run_id = str(attachment["file_processing_run_id"])
    timestamp = datetime.now(UTC).isoformat()
    markdown = b"synthetic replay text\n"
    runtime.database.execute(
        """
        update file_processing_run
           set status = 'SUCCEEDED', page_count = 1, processing_time_ms = 10,
               completed_at = ?, updated_at = ?
         where id = ?
        """,
        (timestamp, timestamp, run_id),
    )
    run = runtime.database.execute_one(
        "select tenant_id, profile_hash from file_processing_run where id = ?",
        (run_id,),
    )
    assert run is not None
    runtime.database.execute(
        """
        insert into file_representation
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           kind, media_type, encoding, status, size_bytes, content_sha256,
           object_key, profile_hash, created_at)
        values ('representation-replay-pdf', ?, ?, ?, ?, 'MARKDOWN',
                'text/markdown', 'utf-8', 'AVAILABLE', ?, ?,
                'opaque/representation-replay-pdf', ?, ?)
        """,
        (
            run_id,
            run["tenant_id"],
            attachment["file_id"],
            attachment["version_id"],
            len(markdown),
            "b" * 64,
            run["profile_hash"],
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        update message_attachment
           set readability_status = 'AVAILABLE', readability_updated_at = ?
         where id = ?
        """,
        (timestamp, task.attachment_id),
    )

    instruction = _group_text(
        msg_id="document-replay-question",
        content="读取 replay.pdf 里写了什么",
    )
    first_job = runtime.dingtalk_stream_message_service.handle_callback(
        payload=instruction,
        correlation_id="document-replay-question-1",
    )
    replayed_job = runtime.dingtalk_stream_message_service.handle_callback(
        payload=instruction,
        correlation_id="document-replay-question-2",
    )

    assert first_job.job_id == replayed_job.job_id
    assert runtime.agent_repository.count_rows("agent_job") == 1
    assert runtime.agent_repository.count_rows("agent_job_file_snapshot") == 1
    assert runtime.agent_repository.count_rows("file_processing_run") == 1
    assert runtime.agent_repository.count_rows("file_representation") == 1


class RecordingDocumentImporter(RecordingAttachmentImporter):
    def import_content(
        self,
        *,
        attachment_id: str,
        data: bytes,
        content_type: str,
    ) -> AttachmentImportReceipt:
        receipt = super().import_content(
            attachment_id=attachment_id,
            data=data,
            content_type=content_type,
        )
        return AttachmentImportReceipt(
            attachment_id=receipt.attachment_id,
            size_bytes=receipt.size_bytes,
            sha256=receipt.sha256,
            file_id="managed_file_pdf_test",
            version_id="file_version_pdf_test",
            readability_status="PENDING",
            processing_run_id="file_processing_run_pdf_test",
        )


def test_docling_profile_imports_pdf_when_dingtalk_omits_content_type() -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
        document_processing_profile_code="docling-text-v1",
    )
    payload = load_fixture("file.json")
    payload["msgId"] = "docling-pdf-no-mime"
    payload["content"] = {
        "downloadCode": "pdf-empty-mime",
        "fileName": "每周行情.pdf",
        "fileSize": 16,
        "contentType": "",
    }
    staged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="docling-pdf-no-mime",
    )
    assert staged.status == "attachments_staged", (staged.reason, staged.error_code)
    task = runtime.message_bus.attachments.popleft()
    importer = RecordingDocumentImporter()
    runtime.attachment_service.importer = importer
    runtime.attachment_service.storage = None
    runtime.attachment_service.downloader = FakeDownloader(
        {"pdf-empty-mime": b"%PDF-1.4\n%%EOF\n"}
    )

    outcome = runtime.attachment_service.process(task.attachment_id, "docling-pdf-no-mime")

    assert outcome == "staged"
    attachment = runtime.agent_repository.get_attachment(task.attachment_id)
    assert attachment.status == "READY"
    assert importer.calls[0][2] == "application/pdf"


def test_draw_txt_request_creates_workspace_and_freezes_file_tools() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    snapshot_service = _RecordingMcpSnapshotService(runtime.mcp_tool_snapshot_service)
    runtime.create_agent_job_service.mcp_tool_snapshot_service = snapshot_service
    payload = load_fixture("direct_text.json")
    payload["msgId"] = "draw-txt-output-request"
    payload["text"] = {"content": "画一个天安门的txt文件"}

    accepted = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="draw-txt-output-request",
    )

    job = runtime.agent_repository.get_job(accepted.job_id)
    assert job.task_workspace_id
    assert snapshot_service.allowed_server_codes is None
    manifest = FileWorkspaceRepository(runtime.database).get_job_snapshot(job.id)
    assert manifest is not None
    assert manifest["items"] == []


def test_text_v2_mixed_txt_log_markdown_attachments_freeze_one_manifest() -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
    )
    file_repository, _storage = _enable_in_process_attachment_import(runtime)
    contents = {
        "txt-code": b"plain text\n",
        "log-code": b"service log\n",
        "md-code": b"# untrusted markdown\n",
    }
    runtime.attachment_service.downloader = FakeDownloader(contents)
    fixtures = (
        ("mixed-text-v2-txt", "txt-code", "input.txt", "text/plain"),
        ("mixed-text-v2-log", "log-code", "service.log", "application/octet-stream"),
        ("mixed-text-v2-md", "md-code", "report.md", "text/markdown"),
    )
    conversation_id = "group-conversation-redacted"
    for message_id, download_code, file_name, media_type in fixtures:
        payload = load_fixture("file.json")
        payload["conversationId"] = conversation_id
        payload["msgId"] = message_id
        payload["content"] = {
            "downloadCode": download_code,
            "fileName": file_name,
            "fileSize": len(contents[download_code]),
            "contentType": media_type,
        }
        staged = runtime.dingtalk_stream_message_service.handle_callback(
            payload=payload,
            correlation_id=message_id,
        )
        assert staged.status == "attachments_staged", (
            staged.reason,
            staged.error_code,
        )
        queued = runtime.message_bus.attachments.popleft()
        assert (
            runtime.attachment_service.process(
                queued.attachment_id,
                queued.correlation_id,
            )
            == "staged"
        )

    instruction = load_fixture("group_text.json")
    instruction["conversationId"] = conversation_id
    instruction["msgId"] = "mixed-text-v2-instruction"
    instruction["text"] = {"content": "读取刚才发送的三个文件并总结"}
    accepted = runtime.dingtalk_stream_message_service.handle_callback(
        payload=instruction,
        correlation_id="mixed-text-v2-instruction",
    )
    job = runtime.agent_repository.get_job(accepted.job_id)
    assert job.agent_runtime_protocol_version == "1.3"
    manifest_service = runtime.agent_executor.context_builder.file_manifest_service
    assert manifest_service is not None
    manifest = manifest_service.runtime_manifest(job.id)
    assert manifest is not None
    assert manifest["schema_version"] == 5
    assert manifest["file_format_policy_version"] == "text-v2"
    by_format = {item["format_code"]: item for item in manifest["items"]}
    assert set(by_format) == {"TXT", "LOG", "MARKDOWN"}
    assert "EDIT" not in by_format["LOG"]["allowed_actions"]
    assert "COMMIT" not in by_format["LOG"]["allowed_actions"]
    assert {"EDIT", "COMMIT"}.issubset(by_format["MARKDOWN"]["allowed_actions"])
    evidence = _file_workspace_evidence(
        runtime,
        job_id=job.id,
        route_decision=dict(job.business_application_route_decision or {}),
    )
    assert evidence["file_format_policy_version"] == "text-v2"
    assert evidence["policy_source"] == "job_file_manifest"
    assert {item["format_code"] for item in evidence["formats"]} == {
        "TXT",
        "LOG",
        "MARKDOWN",
    }


def test_text_v1_publication_rejects_log_before_workspace_or_job_creation() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    payload = load_fixture("file.json")
    payload["msgId"] = "text-v1-log-denied"
    payload["content"] = {
        "downloadCode": "log-code",
        "fileName": "service.log",
        "fileSize": 12,
        "contentType": "text/plain",
    }

    rejected = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="text-v1-log-denied",
    )

    assert rejected.accepted is False
    assert rejected.error_code == "file_workspace_type_unsupported"
    assert runtime.agent_repository.count_rows("agent_job") == 0
    assert runtime.agent_repository.count_rows("task_workspace") == 0


def test_text_v2_binary_log_fails_without_managed_version_or_object() -> None:
    runtime = multimodal_container(
        task_file_features=FEATURES,
        file_format_policy_version="text-v2",
    )
    file_repository, storage = _enable_in_process_attachment_import(runtime)
    runtime.attachment_service.downloader = FakeDownloader({"binary-log": b"line\x00binary\n"})
    payload = load_fixture("file.json")
    payload["msgId"] = "binary-log-denied"
    payload["content"] = {
        "downloadCode": "binary-log",
        "fileName": "service.log",
        "fileSize": 12,
        "contentType": "application/octet-stream",
    }
    staged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="binary-log-denied",
    )
    queued = runtime.message_bus.attachments.popleft()

    assert staged.status == "attachments_staged"
    assert (
        runtime.attachment_service.process(
            queued.attachment_id,
            queued.correlation_id,
        )
        == "staged"
    )
    assert runtime.agent_repository.get_attachment(queued.attachment_id).status == "REJECTED"
    assert file_repository.database.execute_one(
        "select count(*) as value from managed_file_version"
    ) == {"value": 0}
    assert storage.objects == {}


def test_synthetic_private_txt_crosses_channel_file_worker_sandbox_commit_and_delivery(
    tmp_path: Any,
) -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    file_repository = FileWorkspaceRepository(runtime.database)
    storage = _Storage()
    principal = _MutablePrincipal()
    authorization = FileAuthorizationService(runtime.database, _BusinessAccess())
    streaming = GovernedFileStreamingService(
        file_repository,
        authorization,
        storage,
        principal,
        now=lambda: NOW,
    )
    runtime.attachment_service.importer = _InProcessAttachmentImporter(streaming)
    runtime.attachment_service.storage = None
    source = b"synthetic channel input\n"
    runtime.attachment_service.downloader = FakeDownloader({"fixture-file-code": source})
    payload = load_fixture("file.json")
    payload["content"] = {
        "downloadCode": "fixture-file-code",
        "fileName": "input.txt",
        "fileSize": len(source),
        "contentType": "text/plain",
    }

    ingress = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="synthetic-file-acceptance",
    )
    assert ingress.status == "attachments_staged"
    assert ingress.job_id == ""
    assert runtime.agent_repository.count_rows("agent_job") == 0
    queued = runtime.message_bus.attachments.popleft()
    processing = runtime.attachment_service.process(
        queued.attachment_id,
        queued.correlation_id,
    )
    attachment_after_processing = runtime.agent_repository.get_attachment(queued.attachment_id)
    assert processing == "staged", attachment_after_processing.failure_code
    text_payload = load_fixture("group_text.json")
    text_payload["conversationId"] = payload["conversationId"]
    text_payload["msgId"] = "synthetic-text-instruction"
    text_payload["text"] = {"content": "读取刚才上传的文件并生成结果"}
    triggered = runtime.dingtalk_stream_message_service.handle_callback(
        payload=text_payload,
        correlation_id="synthetic-text-trigger",
    )
    assert triggered.status == "received"
    job = runtime.agent_repository.get_job(triggered.job_id)
    assert job.input_message == "读取刚才上传的文件并生成结果"
    assert job.task_workspace_id
    manifest = file_repository.get_job_snapshot(job.id)
    assert manifest is not None
    item = runtime.database.execute_one(
        "select * from agent_job_file_snapshot_item where snapshot_id = ?",
        (manifest["id"],),
    )
    assert item is not None
    assert {"EDIT", "COMMIT"}.issubset(set(json.loads(str(item["allowed_actions_json"]))))
    file_id = str(item["file_id"])
    base_version_id = str(item["version_id"])
    runtime.database.execute(
        "update agent_job set status = 'RUNNING', started_at = ? where id = ?",
        (datetime.now(UTC).isoformat(), job.id),
    )
    workspace = file_repository.get_workspace(str(job.task_workspace_id))
    claims = {
        "sub": str(job.internal_user_id),
        "tenant_id": str(workspace["tenant_id"]),
        "job_id": job.id,
        "session_id": job.session_id,
        "agent_publication_id": str(job.agent_publication_id),
        "application_publication_id": str(job.business_application_publication_id),
    }
    principal.context = authorization.require_job(
        claims=claims,
        tool_identifier="file_prepare_materialization",
    )
    delivery = FileVersionDeliveryService(
        file_repository,
        AgentRepository(runtime.database),
        DeliverySettings(),
    )
    streaming.delivery_intents = delivery
    manager = JobSandboxManager(tmp_path / "runtime-sandboxes")
    sandbox = manager.create(job.id)
    try:
        transfer = streaming.prepare_materialization(
            context=principal.context,
            arguments={"file_id": file_id, "version_id": base_version_id},
        )
        coordinator = FileTransferCoordinator(_StreamingPort(streaming))
        transfer_context = FileTransferContext(
            job_id=job.id,
            workspace_path=sandbox.path,
            principal_token="synthetic-principal",
            sandbox=sandbox,
        )
        materialized = coordinator.process_mcp_control_result(
            _mcp_wire_result(transfer),
            transfer_context,
            materialization_identity=(file_id, base_version_id),
        )
        relative_path = str(materialized["relative_path"])
        local_file = sandbox.path / relative_path
        assert local_file.read_bytes() == source
        sandbox.authorize_tool(
            "Edit",
            {
                "file_path": relative_path,
                "old_string": "channel input",
                "new_string": "agent edited output",
            },
        )
        edited = b"synthetic agent edited output\n"
        local_file.write_bytes(edited)
        commit = streaming.prepare_commit(
            context=principal.context,
            arguments={
                "sandbox_entry_handle": str(materialized["sandbox_entry_handle"]),
                "file_id": file_id,
                "base_version_id": base_version_id,
                "display_name": "input.txt",
                "user_intent": "MODIFY",
                "delivery_mode": "DEFAULT",
            },
        )
        committed = coordinator.process_mcp_control_result(
            _mcp_wire_result(commit), transfer_context
        )
        assert committed["action"] == "COMMITTED"
        assert file_repository.get_file(file_id)["current_version_id"] == committed["version_id"]
    finally:
        sandbox.cleanup()
    assert not sandbox.path.exists()

    current = runtime.agent_repository.get_job(job.id)
    AgentResultService(runtime.agent_repository).save_result(
        current,
        "TXT 已生成新版本并进入交付队列。",
    )
    runtime.agent_repository.transition_job(job_id=job.id, target=JobStatus.SUCCEEDED)
    sender = _ResponseLostSender(streaming)
    dispatcher = DeliveryOutboxDispatcher(
        repository=runtime.agent_repository,
        delivery_service=type(
            "DeliveryRuntime",
            (),
            {
                "connector_registry": _StreamFileConnectorRegistry(),
                "business_authorization_service": _DeliveryAuthorization(),
            },
        )(),
        audit_service=runtime.audit_service,
        settings=DeliverySettings(),
        worker_id="synthetic-delivery-worker",
        file_delivery_sender=sender,
        file_delivery_service=delivery,
    )
    first = dispatcher.dispatch_pending(limit=10)
    assert first.retrying == 1
    event = runtime.database.execute_one(
        "select id from delivery_outbox where job_id = ? and delivery_kind = 'FILE_VERSION'",
        (job.id,),
    )
    assert event is not None
    runtime.database.execute(
        "update delivery_outbox set next_attempt_at = ? where id = ?",
        (datetime.now(UTC).isoformat(), event["id"]),
    )
    second = dispatcher.dispatch_pending(limit=10)
    assert second.succeeded == 1
    assert list(sender.external_files.values()) == [b"synthetic agent edited output\n"]
    assert runtime.database.execute_one(
        "select count(*) as value from agent_artifact where job_id = ? and artifact_type = 'file_commit_results'",
        (job.id,),
    ) == {"value": 1}
    safe_projection = json.dumps(
        {
            "ingress": ingress.job_id,
            "manifest": manifest["manifest_hash"],
            "commit": committed,
            "delivery": second.succeeded,
        },
        sort_keys=True,
    )
    assert source.decode().strip() not in safe_projection
    assert b"synthetic agent edited output" not in safe_projection.encode()


def test_multiple_file_only_messages_stage_silently_then_one_text_claims_one_job() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    _enable_in_process_attachment_import(runtime)
    sources = {
        "code-1": b"first\n",
        "code-2": b"second\n",
        "code-3": b"third\n",
    }
    runtime.attachment_service.downloader = FakeDownloader(sources)

    for ordinal in (1, 2, 3):
        payload = load_fixture("file.json")
        payload["msgId"] = f"staged-file-{ordinal}"
        payload["content"] = {
            "downloadCode": f"code-{ordinal}",
            "fileName": f"input-{ordinal}.txt",
            "fileSize": len(sources[f"code-{ordinal}"]),
            "contentType": "text/plain",
        }
        accepted = runtime.dingtalk_stream_message_service.handle_callback(
            payload=payload,
            correlation_id=f"stage-{ordinal}",
        )
        assert accepted.status == "attachments_staged"
        assert accepted.job_id == ""

    assert runtime.agent_repository.count_rows("agent_job") == 0
    assert runtime.agent_repository.count_rows("delivery_outbox") == 0
    staged = runtime.database.execute(
        "select id, job_id, task_workspace_id from message_attachment order by created_at, id"
    )
    assert len(staged) == 3
    assert all(row["job_id"] is None for row in staged)
    assert len({str(row["task_workspace_id"]) for row in staged}) == 1

    text_payload = load_fixture("group_text.json")
    text_payload["conversationId"] = "group-conversation-redacted"
    text_payload["msgId"] = "claim-staged-files"
    text_payload["text"] = {"content": "比较这些文件，只回复一次"}
    triggered = runtime.dingtalk_stream_message_service.handle_callback(
        payload=text_payload,
        correlation_id="claim-staged-files",
    )

    assert triggered.status == "system_notice"
    assert triggered.job_id == ""
    assert runtime.agent_repository.count_rows("agent_job") == 0
    notice = _latest_system_notice(runtime)
    assert notice["job_id"] is None
    assert "请指明" in str(notice["title"])
    assert "agent_runtime_error" not in str(notice["markdown"])
    assert "{" not in str(notice["markdown"])

    queued = list(runtime.message_bus.attachments)
    runtime.message_bus.attachments.clear()
    outcomes = [
        runtime.attachment_service.process(item.attachment_id, item.correlation_id)
        for item in queued
    ]
    assert outcomes == ["staged", "staged", "staged"]

    text_payload["msgId"] = "later-unrelated-text"
    text_payload["text"] = {"content": "ONES MCP 的权限应该放在哪里？"}
    later = runtime.dingtalk_stream_message_service.handle_callback(
        payload=text_payload,
        correlation_id="later-unrelated-text",
    )
    assert later.status == "received"
    assert runtime.agent_repository.count_rows("agent_job") == 1
    later_job = runtime.agent_repository.get_job(later.job_id)
    assert later_job.status == JobStatus.PENDING
    assert runtime.agent_repository.list_attachments(later_job.id) == []

    text_payload["msgId"] = "named-file-text"
    text_payload["text"] = {"content": "请看 input-1.txt 里写了什么"}
    named = runtime.dingtalk_stream_message_service.handle_callback(
        payload=text_payload,
        correlation_id="named-file-text",
    )
    assert named.status == "received"
    assert runtime.agent_repository.count_rows("agent_job") == 2
    named_job = runtime.agent_repository.get_job(named.job_id)
    claimed = runtime.agent_repository.list_attachments(named_job.id)
    assert [item.file_name for item in claimed] == ["input-1.txt"]


def test_text_job_does_not_wait_when_concurrent_attachment_claim_is_lost(
    monkeypatch: Any,
) -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    file_payload = load_fixture("file.json")
    file_payload["msgId"] = "concurrent-claim-file"
    file_payload["content"] = {
        "downloadCode": "concurrent-code",
        "fileName": "concurrent.txt",
        "fileSize": 8,
        "contentType": "text/plain",
    }
    staged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=file_payload,
        correlation_id="concurrent-claim-file",
    )
    assert staged.status == "attachments_staged"
    monkeypatch.setattr(
        runtime.agent_repository,
        "claim_staged_attachments",
        lambda **_arguments: [],
    )

    text_payload = load_fixture("group_text.json")
    text_payload["conversationId"] = file_payload["conversationId"]
    text_payload["msgId"] = "concurrent-claim-text"
    text_payload["text"] = {"content": "处理此前文件"}
    triggered = runtime.dingtalk_stream_message_service.handle_callback(
        payload=text_payload,
        correlation_id="concurrent-claim-text",
    )

    job = runtime.agent_repository.get_job(triggered.job_id)
    assert job.status == JobStatus.PENDING
    assert runtime.agent_repository.list_attachments(job.id) == []


def test_staged_attachments_are_claimed_only_by_the_same_channel_session() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    file_payload = load_fixture("file.json")
    file_payload["conversationId"] = "direct-conversation-redacted"
    file_payload["conversationType"] = "1"
    file_payload["msgId"] = "private-staged-file"
    file_payload["content"] = {
        "downloadCode": "private-code",
        "fileName": "private.txt",
        "fileSize": 8,
        "contentType": "text/plain",
    }
    staged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=file_payload,
        correlation_id="private-staged-file",
    )
    assert staged.status == "attachments_staged"

    group_text = load_fixture("group_text.json")
    group_text["msgId"] = "other-session-text"
    group_job_result = runtime.dingtalk_stream_message_service.handle_callback(
        payload=group_text,
        correlation_id="other-session-text",
    )
    assert runtime.agent_repository.list_attachments(group_job_result.job_id) == []
    attachment = runtime.database.execute_one(
        "select job_id from message_attachment where file_name = 'private.txt'"
    )
    assert attachment == {"job_id": None}

    private_text = load_fixture("direct_text.json")
    private_text["msgId"] = "same-session-text"
    private_text["text"] = {"content": "请看 private.txt"}
    private_job_result = runtime.dingtalk_stream_message_service.handle_callback(
        payload=private_text,
        correlation_id="same-session-text",
    )
    assert [
        item.file_name
        for item in runtime.agent_repository.list_attachments(private_job_result.job_id)
    ] == ["private.txt"]


def test_managed_channel_marks_file_only_ingress_as_staged_without_job() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    payload = load_fixture("file.json")
    payload["msgId"] = "managed-staged-file"
    payload["content"] = {
        "downloadCode": "managed-code",
        "fileName": "managed.txt",
        "fileSize": 8,
        "contentType": "text/plain",
    }
    event, created = runtime.managed_channel_repository.receive_event(
        source_type="dingding_stream",
        connector_id="connector-dingtalk-stream-default",
        external_event_id="managed-staged-file",
        correlation_id="managed-staged-file",
        payload_hash="safe-test-hash",
        request_bytes=256,
        safe_summary={"msgtype": "file"},
        normalized_event=payload,
        reply_credential_ciphertext="",
    )
    assert created is True

    runtime.channel_dispatch_service.handle(
        ChannelEventMessage(
            channel_event_id=str(event["id"]),
            correlation_id="managed-staged-file",
        )
    )

    stored = runtime.managed_channel_repository.get_event(str(event["id"]))
    assert stored["status"] == "ATTACHMENTS_STAGED"
    assert stored["job_id"] is None
    assert runtime.agent_repository.count_rows("agent_job") == 0


def test_named_file_waits_only_for_source_import() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    _enable_in_process_attachment_import(runtime)
    runtime.attachment_service.downloader = FakeDownloader({"wait-code": b"body\n"})
    payload = load_fixture("file.json")
    payload["msgId"] = "wait-source-file"
    payload["content"] = {
        "downloadCode": "wait-code",
        "fileName": "input-wait.txt",
        "fileSize": 5,
        "contentType": "text/plain",
    }
    staged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="wait-source-file",
    )
    assert staged.status == "attachments_staged"
    asked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="wait-source-text", content="请看 input-wait.txt 里写了什么"),
        correlation_id="wait-source-text",
    )
    assert asked.status == "received"
    job = runtime.agent_repository.get_job(asked.job_id)
    assert job.status == JobStatus.WAITING_INPUT
    claimed = runtime.agent_repository.list_attachments(job.id)
    assert [item.file_name for item in claimed] == ["input-wait.txt"]
    task = runtime.message_bus.attachments.popleft()
    assert runtime.attachment_service.process(task.attachment_id, task.correlation_id) == "released"
    assert runtime.agent_repository.get_job(job.id).status == JobStatus.PENDING


def test_processing_document_metadata_executes_while_content_is_system_notice() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    _enable_in_process_attachment_import(runtime)
    runtime.attachment_service.downloader = FakeDownloader({"meta-code": b"secret-body\n"})
    payload = load_fixture("file.json")
    payload["msgId"] = "pending-meta-file"
    payload["content"] = {
        "downloadCode": "meta-code",
        "fileName": "input-meta.txt",
        "fileSize": 12,
        "contentType": "text/plain",
    }
    runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="pending-meta-file",
    )
    task = runtime.message_bus.attachments.popleft()
    assert runtime.attachment_service.process(task.attachment_id, task.correlation_id) == "staged"
    _mark_readability(runtime, file_name="input-meta.txt", status="PENDING")

    metadata = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="pending-meta-text", content="input-meta.txt 叫什么名字？"),
        correlation_id="pending-meta-text",
    )
    assert metadata.status == "received"
    meta_job = runtime.agent_repository.get_job(metadata.job_id)
    assert meta_job.status == JobStatus.PENDING
    snapshot = FileWorkspaceRepository(runtime.database).get_job_snapshot(meta_job.id)
    items = runtime.database.execute(
        """
        select display_name, auto_materialize
          from agent_job_file_snapshot_item
         where snapshot_id = ?
        """,
        (snapshot["id"],),
    )
    assert all(not bool(row["auto_materialize"]) for row in items)

    content = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="pending-content-text", content="总结 input-meta.txt"),
        correlation_id="pending-content-text",
    )
    assert content.status == "system_notice"
    assert runtime.agent_repository.count_rows("agent_job") == 1
    notice = _latest_system_notice(runtime)
    assert "可读内容" in notice["markdown"]
    assert "agent_runtime_error" not in notice["markdown"]
    assert runtime.database.execute_one(
        "select count(*) as value from file_readiness_blocked_turn where status = 'OPEN'"
    ) == {"value": 1}


def test_quote_binds_referenced_file_instead_of_workspace_siblings() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    _enable_in_process_attachment_import(runtime)
    sources = {"quote-1": b"one\n", "quote-2": b"two\n"}
    runtime.attachment_service.downloader = FakeDownloader(sources)
    for ordinal in (1, 2):
        payload = load_fixture("file.json")
        payload["msgId"] = f"quoted-file-{ordinal}"
        payload["content"] = {
            "downloadCode": f"quote-{ordinal}",
            "fileName": f"quoted-{ordinal}.txt",
            "fileSize": len(sources[f"quote-{ordinal}"]),
            "contentType": "text/plain",
        }
        runtime.dingtalk_stream_message_service.handle_callback(
            payload=payload,
            correlation_id=f"quoted-file-{ordinal}",
        )
    while runtime.message_bus.attachments:
        task = runtime.message_bus.attachments.popleft()
        runtime.attachment_service.process(task.attachment_id, task.correlation_id)

    asked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(
            msg_id="quote-text",
            content="请总结这个附件",
            original_msg_id="quoted-file-2",
        ),
        correlation_id="quote-text",
    )
    assert asked.status == "received"
    claimed = runtime.agent_repository.list_attachments(asked.job_id)
    assert [item.file_name for item in claimed] == ["quoted-2.txt"]


def test_blocked_turn_notifies_once_without_replaying_and_ordinary_upload_stays_silent() -> None:
    runtime = multimodal_container(task_file_features=FEATURES)
    _enable_in_process_attachment_import(runtime)
    runtime.attachment_service.downloader = FakeDownloader(
        {"ready-code": b"ready-body\n", "silent-code": b"silent\n"}
    )
    silent = load_fixture("file.json")
    silent["msgId"] = "silent-upload"
    silent["content"] = {
        "downloadCode": "silent-code",
        "fileName": "silent.txt",
        "fileSize": 7,
        "contentType": "text/plain",
    }
    runtime.dingtalk_stream_message_service.handle_callback(
        payload=silent,
        correlation_id="silent-upload",
    )
    silent_task = runtime.message_bus.attachments.popleft()
    runtime.attachment_service.process(silent_task.attachment_id, silent_task.correlation_id)
    assert runtime.attachment_service.reconcile_file_readiness_notices() == {
        "expired": 0,
        "notified": 0,
    }
    assert runtime.database.execute_one(
        "select count(*) as value from delivery_outbox where delivery_kind = 'SYSTEM_NOTICE'"
    ) == {"value": 0}

    payload = load_fixture("file.json")
    payload["msgId"] = "blocked-ready-file"
    payload["content"] = {
        "downloadCode": "ready-code",
        "fileName": "blocked.txt",
        "fileSize": 11,
        "contentType": "text/plain",
    }
    runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="blocked-ready-file",
    )
    task = runtime.message_bus.attachments.popleft()
    runtime.attachment_service.process(task.attachment_id, task.correlation_id)
    _mark_readability(runtime, file_name="blocked.txt", status="PENDING")
    blocked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="blocked-content", content="总结 blocked.txt"),
        correlation_id="blocked-content",
    )
    assert blocked.status == "system_notice"
    assert runtime.agent_repository.count_rows("agent_job") == 0
    first_notice = _latest_system_notice(runtime)
    _mark_readability(runtime, file_name="blocked.txt", status="AVAILABLE")
    result = runtime.attachment_service.reconcile_file_readiness_notices()
    assert result["notified"] == 1
    assert result["expired"] == 0
    ready = _latest_system_notice(runtime)
    assert ready["id"] != first_notice["id"]
    assert "已经生成" in ready["markdown"]
    assert runtime.agent_repository.count_rows("agent_job") == 0
    assert runtime.database.execute_one(
        "select status from file_readiness_blocked_turn"
    ) == {"status": "NOTIFIED"}

    runtime.database.execute(
        """
        insert into file_readiness_blocked_turn
          (id, session_id, workspace_id, user_message_id, reason_code,
           status, created_at, expires_at, notified_at)
        values (
          'file_turn_expired',
          (select session_id from file_readiness_blocked_turn limit 1),
          (select workspace_id from file_readiness_blocked_turn limit 1),
          (select user_message_id from file_readiness_blocked_turn limit 1),
          'file_readable_content_not_ready',
          'OPEN', ?, ?, null
        )
        """,
        (
            datetime.now(UTC).isoformat(),
            (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        ),
    )
    expired = runtime.attachment_service.reconcile_file_readiness_notices()
    assert expired["expired"] == 1
    assert expired["notified"] == 0
    assert runtime.agent_repository.count_rows("agent_job") == 0


def test_today_image_question_binds_ready_workspace_png_and_unrelated_text_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_resolver_now(monkeypatch, FROZEN_TODAY)
    runtime = multimodal_container(task_file_features=FEATURES)
    file_repository, _storage = _enable_in_process_attachment_import(runtime)
    runtime.attachment_service.downloader = FakeDownloader({"notes-code": b"notes\n"})
    payload = load_fixture("file.json")
    payload["msgId"] = "prior-notes-file"
    payload["content"] = {
        "downloadCode": "notes-code",
        "fileName": "notes.txt",
        "fileSize": 6,
        "contentType": "text/plain",
    }
    runtime.dingtalk_stream_message_service.handle_callback(
        payload=payload,
        correlation_id="prior-notes-file",
    )
    task = runtime.message_bus.attachments.popleft()
    runtime.attachment_service.process(task.attachment_id, task.correlation_id)

    workspace = runtime.database.execute_one(
        "select * from task_workspace where status = 'ACTIVE'"
    )
    assert workspace is not None
    owner_type = WorkspaceOwnerType(str(workspace["owner_type"]))
    if owner_type is WorkspaceOwnerType.PRIVATE_USER:
        owner = FileOwner(owner_type, user_id=str(workspace["owner_user_id"]))
    else:
        owner = FileOwner(
            owner_type,
            enterprise_id=str(workspace["owner_enterprise_id"]),
            connector_id=str(workspace["owner_connector_id"]),
            conversation_id=str(workspace["owner_conversation_id"]),
        )
    markdown = b"a red square\n"
    file_repository.create_file(
        file_id="file-today-image",
        tenant_id=str(workspace["tenant_id"]),
        owner=owner,
        display_name="image-1-980757d6.png",
        actor_id="file-worker",
        format_code="PNG",
        source_received_at="2026-08-19T01:40:47+00:00",
    )
    file_repository.create_version(
        version_id="version-today-image",
        file_id="file-today-image",
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="image/png",
        encoding="",
        size_bytes=12,
        content_sha256="f" * 64,
        object_key="opaque/version-today-image",
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="file-worker",
        format_code="PNG",
        advance_current_from="",
    )
    file_repository.link_workspace_file(
        workspace_id=str(workspace["id"]),
        file_id="file-today-image",
        version_id="version-today-image",
        logical_name="image-1-980757d6.png",
        role=WorkspaceFileRole.INPUT,
    )
    runtime.database.execute(
        """
        insert into file_processing_run
          (id, tenant_id, source_file_id, source_version_id, processor_code,
           processor_version, processor_build_digest, profile_code, profile_hash,
           status, source_size_bytes, completed_at, created_by, created_at, updated_at)
        values ('run-today-image', ?, 'file-today-image', 'version-today-image',
                'docling-serve', '1.30.0', ?, 'docling-text-v1', ?, 'SUCCEEDED',
                12, ?, 'file-processing-worker', ?, ?)
        """,
        (
            str(workspace["tenant_id"]),
            "sha256:" + "b" * 64,
            "d" * 64,
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
        ),
    )
    runtime.database.execute(
        """
        insert into file_representation
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           kind, media_type, encoding, status, size_bytes, content_sha256,
           object_key, profile_hash, created_at)
        values ('representation-today-image', 'run-today-image', ?,
                'file-today-image', 'version-today-image', 'MARKDOWN',
                'text/markdown', 'utf-8', 'AVAILABLE', ?, ?,
                'opaque/representation-today-image', ?, ?)
        """,
        (
            str(workspace["tenant_id"]),
            len(markdown),
            "e" * 64,
            "d" * 64,
            datetime.now(UTC).isoformat(),
        ),
    )

    unrelated = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="unrelated-nearby", content="昨天的附近有什么安排"),
        correlation_id="unrelated-nearby",
    )
    assert unrelated.status == "received"
    unrelated_job = runtime.agent_repository.get_job(unrelated.job_id)
    unrelated_snapshot = file_repository.get_job_snapshot(unrelated_job.id)
    unrelated_items = {
        str(row["display_name"]): row
        for row in runtime.database.execute(
            """
            select display_name, source_kind, auto_materialize, representation_id
              from agent_job_file_snapshot_item
             where snapshot_id = ?
            """,
            (unrelated_snapshot["id"],),
        )
    }
    assert unrelated_items == {}
    assert runtime.agent_repository.list_attachments(unrelated_job.id) == []

    asked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="today-image-content", content="今天发的图片什么内容"),
        correlation_id="today-image-content",
    )
    assert asked.status == "received"
    asked_job = runtime.agent_repository.get_job(asked.job_id)
    asked_snapshot = file_repository.get_job_snapshot(asked_job.id)
    image_item = runtime.database.execute_one(
        """
        select display_name, source_kind, auto_materialize, representation_id
          from agent_job_file_snapshot_item
         where snapshot_id = ? and display_name = 'image-1-980757d6.png'
        """,
        (asked_snapshot["id"],),
    )
    assert image_item is not None
    assert image_item["source_kind"] == "EXPLICIT_REFERENCE"
    assert bool(image_item["auto_materialize"]) is False
    assert image_item["representation_id"] == "representation-today-image"


def test_last_week_image_is_recalled_after_workspace_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_resolver_now(monkeypatch, FROZEN_MONDAY)
    runtime = multimodal_container(task_file_features=FEATURES)
    file_repository, _storage = _enable_in_process_attachment_import(runtime)
    _import_channel_file(
        runtime,
        msg_id="carrier-txt",
        file_name="carrier.txt",
        content_type="text/plain",
        data=b"carrier\n",
    )
    _seed_png_with_session_attachment(
        runtime,
        file_repository,
        file_id="file-last-week-png",
        version_id="version-last-week-png",
        display_name="last-week.png",
        received_at=LAST_WEEK_RECEIVED_AT,
    )
    old_workspace_id = str(
        runtime.database.execute_one("select id from task_workspace where status = 'ACTIVE'")["id"]
    )
    _expire_active_workspaces(runtime)

    asked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-last-week-image", content="上周的图什么内容"),
        correlation_id="ask-last-week-image",
    )
    assert asked.status == "received"
    job = runtime.agent_repository.get_job(asked.job_id)
    assert job.task_workspace_id
    assert job.task_workspace_id != old_workspace_id
    assert (
        runtime.database.execute_one(
            "select status from task_workspace where id = ?",
            (old_workspace_id,),
        )["status"]
        == "CLEANED"
    )
    assert (
        runtime.database.execute_one(
            """
            select id from task_workspace_file
             where workspace_id = ? and file_id = ? and status = 'ACTIVE'
            """,
            (job.task_workspace_id, "file-last-week-png"),
        )
        is None
    )
    snapshot = file_repository.get_job_snapshot(job.id)
    item = runtime.database.execute_one(
        """
        select display_name, source_kind, auto_materialize
          from agent_job_file_snapshot_item
         where snapshot_id = ? and file_id = ?
        """,
        (snapshot["id"], "file-last-week-png"),
    )
    assert item is not None
    assert item["display_name"] == "last-week.png"
    assert item["source_kind"] == "EXPLICIT_REFERENCE"
    assert bool(item["auto_materialize"]) is False


def test_calendar_date_and_range_recall_txt_after_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_resolver_now(monkeypatch, FROZEN_MONDAY)
    runtime = multimodal_container(task_file_features=FEATURES)
    file_repository, _storage = _enable_in_process_attachment_import(runtime)
    first = _import_channel_file(
        runtime,
        msg_id="aug12-txt",
        file_name="aug12.txt",
        content_type="text/plain",
        data=b"hello\n",
    )
    second = _import_channel_file(
        runtime,
        msg_id="aug14-txt",
        file_name="aug14.txt",
        content_type="text/plain",
        data=b"world\n",
    )
    _backdate_file(runtime, file_id=str(first["file_id"]), received_at=LAST_WEEK_RECEIVED_AT)
    _backdate_file(
        runtime,
        file_id=str(second["file_id"]),
        received_at="2026-08-14T04:00:00+00:00",
    )
    _expire_active_workspaces(runtime)

    named = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-aug12-file", content="8月12日的文件什么内容"),
        correlation_id="ask-aug12-file",
    )
    assert named.status == "received"
    named_job = runtime.agent_repository.get_job(named.job_id)
    named_snapshot = file_repository.get_job_snapshot(named_job.id)
    names = {row["display_name"] for row in _snapshot_items(runtime, named_snapshot["id"])}
    assert names == {"aug12.txt"}

    ranged = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-aug-range", content="8月10日到15日发了哪些文件"),
        correlation_id="ask-aug-range",
    )
    assert ranged.status == "received"
    ranged_job = runtime.agent_repository.get_job(ranged.job_id)
    ranged_snapshot = file_repository.get_job_snapshot(ranged_job.id)
    items = _snapshot_items(runtime, ranged_snapshot["id"])
    assert {row["display_name"] for row in items} == {"aug12.txt", "aug14.txt"}
    assert all(not bool(row["auto_materialize"]) for row in items)


def test_date_chat_without_file_token_does_not_recall_or_create_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_resolver_now(monkeypatch, FROZEN_MONDAY)
    runtime = multimodal_container(task_file_features=FEATURES)
    _enable_in_process_attachment_import(runtime)
    imported = _import_channel_file(
        runtime,
        msg_id="aug12-plan",
        file_name="plan.txt",
        content_type="text/plain",
        data=b"plan\n",
    )
    _backdate_file(runtime, file_id=str(imported["file_id"]), received_at=LAST_WEEK_RECEIVED_AT)
    _expire_active_workspaces(runtime)
    asked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-aug12-chat", content="8月12日附近有什么安排"),
        correlation_id="ask-aug12-chat",
    )
    assert asked.status == "received"
    job = runtime.agent_repository.get_job(asked.job_id)
    assert job.task_workspace_id == ""
    assert runtime.agent_repository.count_rows("agent_job_file_snapshot") == 0


def test_time_window_multiple_files_list_metadata_without_preload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_resolver_now(monkeypatch, FROZEN_MONDAY)
    runtime = multimodal_container(task_file_features=FEATURES)
    _enable_in_process_attachment_import(runtime)
    first = _import_channel_file(
        runtime,
        msg_id="week-a",
        file_name="a.txt",
        content_type="text/plain",
        data=b"a\n",
    )
    second = _import_channel_file(
        runtime,
        msg_id="week-b",
        file_name="b.txt",
        content_type="text/plain",
        data=b"b\n",
    )
    _backdate_file(runtime, file_id=str(first["file_id"]), received_at=LAST_WEEK_RECEIVED_AT)
    _backdate_file(
        runtime,
        file_id=str(second["file_id"]),
        received_at="2026-08-13T04:00:00+00:00",
    )
    _expire_active_workspaces(runtime)

    content = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-week-content", content="上周的文件什么内容"),
        correlation_id="ask-week-content",
    )
    assert content.status == "received"
    content_job = runtime.agent_repository.get_job(content.job_id)
    content_items = _snapshot_items(
        runtime,
        FileWorkspaceRepository(runtime.database).get_job_snapshot(content_job.id)["id"],
    )
    assert {row["display_name"] for row in content_items} == {"a.txt", "b.txt"}
    assert all(not bool(row["auto_materialize"]) for row in content_items)

    listed = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-week-names", content="上周发了哪些文件"),
        correlation_id="ask-week-names",
    )
    assert listed.status == "received"
    listed_job = runtime.agent_repository.get_job(listed.job_id)
    items = _snapshot_items(
        runtime, FileWorkspaceRepository(runtime.database).get_job_snapshot(listed_job.id)["id"]
    )
    assert {row["display_name"] for row in items} == {"a.txt", "b.txt"}
    assert all(not bool(row["auto_materialize"]) for row in items)


def test_empty_time_window_notice_does_not_claim_never_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_resolver_now(monkeypatch, FROZEN_MONDAY)
    runtime = multimodal_container(task_file_features=FEATURES)
    asked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-empty-week", content="上周的附件"),
        correlation_id="ask-empty-week",
    )
    assert asked.status == "system_notice"
    notice = _latest_system_notice(runtime)
    assert notice["notice_kind"] == "time_window_empty"
    assert "仍可访问" in notice["markdown"]
    assert "没发过" not in notice["markdown"]
    assert runtime.agent_repository.count_rows("agent_job") == 0
    assert runtime.database.execute_one("select id from task_workspace") is None


def test_recalled_available_file_can_materialize_and_cleaned_file_lists_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_resolver_now(monkeypatch, FROZEN_MONDAY)
    runtime = multimodal_container(task_file_features=FEATURES)
    file_repository, storage = _enable_in_process_attachment_import(runtime)
    imported = _import_channel_file(
        runtime,
        msg_id="retain-txt",
        file_name="keep.txt",
        content_type="text/plain",
        data=b"keep\n",
    )
    extra = _import_channel_file(
        runtime,
        msg_id="extra-this-week",
        file_name="extra.txt",
        content_type="text/plain",
        data=b"extra\n",
    )
    _backdate_file(runtime, file_id=str(imported["file_id"]), received_at=LAST_WEEK_RECEIVED_AT)
    _backdate_file(
        runtime,
        file_id=str(extra["file_id"]),
        received_at="2026-08-18T01:00:00+00:00",
    )
    _expire_active_workspaces(runtime)
    asked = runtime.dingtalk_stream_message_service.handle_callback(
        payload=_group_text(msg_id="ask-keep", content="上周的文件什么内容"),
        correlation_id="ask-keep",
    )
    assert asked.status == "received"
    job = runtime.agent_repository.get_job(asked.job_id)
    snapshot = file_repository.get_job_snapshot(job.id)
    runtime.database.execute("update agent_job set status = 'RUNNING' where id = ?", (job.id,))
    claims = {
        "sub": job.internal_user_id,
        "tenant_id": snapshot["tenant_id"],
        "job_id": job.id,
        "session_id": job.session_id,
        "agent_publication_id": job.agent_publication_id,
        "application_publication_id": job.business_application_publication_id,
    }
    authorization = FileAuthorizationService(runtime.database, _BusinessAccess())
    context = authorization.require_job(
        claims=claims,
        tool_identifier="file_prepare_materialization",
    )
    application = FileWorkspaceApplicationService(
        file_repository,
        authorization,
        GovernedFileStreamingService(
            file_repository,
            authorization,
            storage,
            _MutablePrincipal(),
            now=lambda: NOW,
        ),
    )
    listed = application.invoke(
        context=context,
        tool_identifier="task_workspace_list_files",
        arguments={},
    )
    assert [item["display_name"] for item in listed["items"]] == ["keep.txt"]
    assert extra["file_id"] not in {item["file_id"] for item in listed["items"]}
    prepared = application.invoke(
        context=context,
        tool_identifier="file_prepare_materialization",
        arguments={
            "file_id": imported["file_id"],
            "version_id": imported["version_id"],
        },
    )
    transfer = prepared[INTERNAL_TRANSFER_META][FILE_TRANSFER_META_KEY]
    assert str(transfer["relative_path"]).startswith("inputs/")

    file_repository.mark_content_unavailable(
        version_id=str(imported["version_id"]),
        deleted_at=datetime.now(UTC).isoformat(),
    )
    listed_after = application.invoke(
        context=context,
        tool_identifier="task_workspace_list_files",
        arguments={},
    )
    assert listed_after["items"][0]["version_status"] == "CONTENT_UNAVAILABLE"
    with pytest.raises(Exception) as error:
        application.invoke(
            context=context,
            tool_identifier="file_prepare_materialization",
            arguments={
                "file_id": imported["file_id"],
                "version_id": imported["version_id"],
            },
        )
    assert getattr(error.value, "error_code", "") == "file_content_unavailable"
