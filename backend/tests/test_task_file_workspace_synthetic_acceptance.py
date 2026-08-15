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
    runtime.attachment_service.downloader = FakeDownloader(
        {"fixture-file-code": source}
    )
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
    queued = runtime.message_bus.attachments.popleft()
    processing = runtime.attachment_service.process(
        queued.attachment_id,
        queued.correlation_id,
    )
    attachment_after_processing = runtime.agent_repository.get_attachment(
        queued.attachment_id
    )
    assert processing == "released", attachment_after_processing.failure_code
    job = runtime.agent_repository.get_job(ingress.job_id)
    assert job.task_workspace_id
    manifest = file_repository.get_job_snapshot(job.id)
    assert manifest is not None
    item = runtime.database.execute_one(
        "select * from agent_job_file_snapshot_item where snapshot_id = ?",
        (manifest["id"],),
    )
    assert item is not None
    assert {"EDIT", "COMMIT"}.issubset(
        set(json.loads(str(item["allowed_actions_json"])))
    )
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
        assert file_repository.get_file(file_id)["current_version_id"] == committed[
            "version_id"
        ]
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
