from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.attachments.domain import AttachmentImportReceipt
from app.modules.delivery.application.delivery_dispatch_service import (
    DeliveryOutboxDispatcher,
)
from app.modules.file_workspace.authorization import (
    FileAuthorizationContext,
    FileAuthorizationService,
)
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.streaming_service import GovernedFileStreamingService
from app.modules.file_workspace.streaming_service import INTERNAL_TRANSFER_META
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.job.domain.job_status import JobStatus
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
    load_fixture,
    multimodal_container,
)
from backend.tests.test_file_authorization import _BusinessAccess
from backend.tests.test_file_commit_streaming import NOW, _Storage
from backend.tests.test_file_version_delivery import (
    _Authorization as _DeliveryAuthorization,
)
from backend.tests.test_file_version_delivery import (
    _ConnectorRegistry,
    _ResponseLostSender,
)


FEATURES = {
    "workspace_enabled": True,
    "file_mcp_enabled": True,
    "runtime_file_edit_enabled": True,
    "default_file_delivery_enabled": True,
}


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
        )


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
            version_id=str(result["version_id"]),
            size_bytes=int(result["size_bytes"]),
            sha256=str(result["sha256"]),
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
        )
        materialized = coordinator.process_mcp_control_result(
            _mcp_wire_result(transfer),
            transfer_context,
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
                "connector_registry": _ConnectorRegistry(),
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
    file_repository, _storage = _enable_in_process_attachment_import(runtime)
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
    text_payload["text"] = {"content": "比较刚才三个文件，只回复一次"}
    triggered = runtime.dingtalk_stream_message_service.handle_callback(
        payload=text_payload,
        correlation_id="claim-staged-files",
    )

    assert triggered.status == "received"
    assert runtime.agent_repository.count_rows("agent_job") == 1
    job = runtime.agent_repository.get_job(triggered.job_id)
    assert job.input_message == "比较刚才三个文件，只回复一次"
    assert job.status == JobStatus.WAITING_INPUT
    claimed = runtime.agent_repository.list_attachments(job.id)
    assert [item.file_name for item in claimed] == [
        "input-1.txt",
        "input-2.txt",
        "input-3.txt",
    ]
    assert all(item.claimed_at for item in claimed)

    queued = list(runtime.message_bus.attachments)
    runtime.message_bus.attachments.clear()
    outcomes = [
        runtime.attachment_service.process(item.attachment_id, item.correlation_id)
        for item in queued
    ]
    assert outcomes == ["waiting", "waiting", "released"]
    assert runtime.agent_repository.get_job(job.id).status == JobStatus.PENDING
    manifest = file_repository.get_job_snapshot(job.id)
    items = runtime.database.execute(
        """
        select display_name, auto_materialize
          from agent_job_file_snapshot_item
         where snapshot_id = ? order by ordinal
        """,
        (manifest["id"],),
    )
    assert [row["display_name"] for row in items] == [
        "input-1.txt",
        "input-2.txt",
        "input-3.txt",
    ]
    assert all(bool(row["auto_materialize"]) for row in items)

    text_payload["msgId"] = "later-unrelated-text"
    text_payload["text"] = {"content": "继续说明结论"}
    later = runtime.dingtalk_stream_message_service.handle_callback(
        payload=text_payload,
        correlation_id="later-unrelated-text",
    )
    assert runtime.agent_repository.count_rows("agent_job") == 2
    assert runtime.agent_repository.list_attachments(later.job_id) == []


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
    private_text["text"] = {"content": "处理刚才的私聊文件"}
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
