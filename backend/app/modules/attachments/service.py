from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.attachments.domain import (
    AttachmentImporter,
    MediaDownloader,
)
from app.modules.audit.application.audit_service import AuditService
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V2
from app.modules.file_workspace.contracts import FILE_ERROR_CATALOG
from app.modules.file_workspace.manifest_service import JobFileManifestService
from app.modules.file_workspace.text_format_policy import get_text_format_policy
from app.modules.job.application.file_context import (
    ResolverDecision,
    evaluate_file_gate,
    file_dependency_from_payload,
    system_notice_markdown,
)
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.shared.config import AttachmentSettings
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


TERMINAL_ATTACHMENT_STATUSES = {"READY", "REJECTED", "FAILED", "stored_not_interpreted"}


class AttachmentProcessingService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        publisher: MessagePublisher,
        audit_service: AuditService,
        credential_cipher: AttachmentCredentialCipher,
        downloader: MediaDownloader,
        settings: AttachmentSettings,
        importer: AttachmentImporter,
        delivery_service: ResultDeliveryService | None = None,
        file_manifest_service: JobFileManifestService | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.audit_service = audit_service
        self.credential_cipher = credential_cipher
        self.downloader = downloader
        self.importer = importer
        self.settings = settings
        self.delivery_service = delivery_service
        self.file_manifest_service = file_manifest_service

    def process(self, attachment_id: str, correlation_id: str) -> str:
        attachment = self.repository.get_attachment(attachment_id)
        if attachment.status in TERMINAL_ATTACHMENT_STATUSES:
            return self._release_attachment_if_ready(attachment_id, correlation_id)
        context = self.repository.attachment_session_context(attachment_id)
        secret = self.repository.get_attachment_secret(attachment_id)
        if _expired(secret.get("source_credential_expires_at")):
            self.repository.update_attachment(
                attachment_id,
                status="FAILED",
                failure_code="source_credential_expired",
                clear_credential=True,
            )
            return self._release_attachment_if_ready(attachment_id, correlation_id)
        try:
            credential = self.credential_cipher.decrypt(
                str(secret.get("source_credential_ciphertext") or "")
            )
            self.repository.update_attachment(attachment_id, status="DOWNLOADING")
            data = self.downloader.download(
                download_code=credential,
                max_bytes=self.settings.max_file_bytes,
                connector_id=str(context["source_connector_id"]),
                robot_code=str(context["bot_identity"]),
            )
            suffix = Path(attachment.file_name).suffix.lower()
            policy = get_text_format_policy()
            text_definition = next(
                (item for item in policy.formats if item.extension == suffix),
                None,
            )
            document_definition = next(
                (
                    item
                    for item in DOCLING_LAYOUT_OCR_V2.source_formats
                    if suffix in item.extensions
                ),
                None,
            )
            if not context.get("task_workspace_id"):
                raise NonRetryableExecutionError(
                    "Attachment has no task workspace",
                    safe_message="当前业务应用未启用任务工作区",
                    error_code="file_workspace_unavailable",
                )
            task_text = text_definition is not None
            governed_document = document_definition is not None
            if task_text:
                fallback_mime = {
                    ".txt": "text/plain",
                    ".log": "application/octet-stream",
                    ".md": "text/markdown",
                }[suffix]
                detected_mime = attachment.declared_mime or fallback_mime
            elif governed_document:
                # File Service owns source validation for Docling inputs. The MVP
                # extractor must not reject PDF before that boundary, and DingTalk
                # often omits Content-Type, so empty/generic declarations map to
                # the profile canonical type.
                assert document_definition is not None
                declared = (attachment.declared_mime or "").split(";", 1)[0].strip().lower()
                if declared in document_definition.accepted_media_types or declared in {
                    "",
                    "application/octet-stream",
                    "binary/octet-stream",
                }:
                    detected_mime = document_definition.canonical_media_type
                else:
                    detected_mime = (
                        attachment.declared_mime or document_definition.canonical_media_type
                    )
            else:
                raise NonRetryableExecutionError(
                    "Attachment format is unsupported by the current file contract",
                    safe_message="当前任务工作区不支持此文件格式",
                    error_code="file_type_unsupported",
                )
            digest = hashlib.sha256(data).hexdigest()
            imported = self.importer.import_content(
                attachment_id=attachment.id,
                data=data,
                content_type=detected_mime,
            )
            if imported.size_bytes != len(data) or imported.sha256 != digest:
                raise RetryableExecutionError(
                    "File Service receipt does not match downloaded bytes",
                    safe_message="附件导入回执不匹配",
                    error_code="file_service_receipt_mismatch",
                )
            self.repository.update_attachment(
                attachment_id,
                status="READY",
                detected_mime=detected_mime,
                size_bytes=imported.size_bytes,
                sha256=digest,
                clear_credential=True,
            )
            self.audit_service.record(
                "attachment.processed",
                status="SUCCEEDED",
                summary="Attachment reached a safe terminal state",
                job_id=attachment.job_id or None,
                payload={
                    "attachment_id": attachment_id,
                    "status": self.repository.get_attachment(attachment_id).status,
                },
            )
        except RetryableExecutionError:
            retries = self.repository.increment_attachment_retry(attachment_id)
            if retries <= 3:
                self.repository.update_attachment(attachment_id, status="PENDING")
                self.publisher.publish_attachment_retry(attachment_id, correlation_id, 30)
                return "retry"
            self.repository.update_attachment(
                attachment_id,
                status="FAILED",
                failure_code="attachment_retry_exhausted",
                clear_credential=True,
            )
            self.publisher.publish_attachment_dead_letter(
                attachment_id, correlation_id, "attachment_retry_exhausted"
            )
        except Exception as exc:
            error_code = str(getattr(exc, "error_code", "") or "")[:128]
            if not error_code:
                error_code = (
                    "attachment_processing_rejected"
                    if isinstance(exc, NonRetryableExecutionError)
                    else "attachment_processing_failed"
                )
            self.repository.update_attachment(
                attachment_id,
                status="REJECTED" if isinstance(exc, NonRetryableExecutionError) else "FAILED",
                failure_code=error_code,
                clear_credential=True,
            )
            self.publisher.publish_attachment_dead_letter(
                attachment_id, correlation_id, error_code
            )
            self.audit_service.record(
                "attachment.rejected",
                status="FAILED",
                summary="Attachment processing failed safely",
                job_id=attachment.job_id or None,
                payload={"attachment_id": attachment_id, "failure_code": error_code},
            )
        return self._release_attachment_if_ready(attachment_id, correlation_id)

    def _release_attachment_if_ready(self, attachment_id: str, correlation_id: str) -> str:
        attachment = self.repository.get_attachment(attachment_id)
        if not attachment.job_id:
            if attachment.status == "REJECTED":
                self._notify_staged_attachment_rejection(attachment, correlation_id)
            return "staged"
        return self._release_if_ready(attachment.job_id, correlation_id)

    def _notify_staged_attachment_rejection(
        self,
        attachment: Any,
        correlation_id: str,
    ) -> None:
        if self.delivery_service is None:
            return
        context = self.repository.attachment_session_context(attachment.id)
        session = self.repository.get_session(str(context["session_id"]))
        definition = FILE_ERROR_CATALOG.get(str(attachment.failure_code or ""))
        reason = (
            definition.safe_message if definition else "文件不符合当前任务工作区策略"
        )
        display_name = " ".join(
            Path(str(attachment.file_name or "该文件")).name.replace("`", "'").split()
        )[:255]
        self.delivery_service.enqueue_system_notice(
            idempotency_key=f"attachment-rejected:{attachment.id}",
            session_id=session.id,
            reply_route=session.reply_route or {"type": "none"},
            title="文件未进入工作区",
            markdown=(
                f"文件 `{display_name or '该文件'}` 未进入工作区：{reason}。"
                "请修正后重新发送。"
            ),
            reason_code=str(attachment.failure_code or "attachment_processing_rejected"),
            correlation_id=correlation_id,
            application_publication_id=session.application_publication_id,
            principal_user_id=session.requester_id,
            notice_kind="attachment_rejected",
            task_workspace_id=str(context.get("task_workspace_id") or ""),
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _release_if_ready(self, job_id: str, correlation_id: str) -> str:
        attachments = self.repository.list_attachments(job_id)
        if not attachments or any(
            item.status not in TERMINAL_ATTACHMENT_STATUSES for item in attachments
        ):
            return "waiting"
        job = self.repository.get_job(job_id)
        if job.status != JobStatus.WAITING_INPUT:
            return job.status.value.lower()
        gate = self._evaluate_stored_file_gate(job, attachments)
        if gate is not None and gate.action == "wait_source":
            return "waiting"
        if gate is not None and gate.action == "system_notice":
            return self._end_waiting_job_with_notice(job, gate, correlation_id)
        if self.file_manifest_service is not None:
            try:
                self.file_manifest_service.finalize(job_id)
            except NonRetryableExecutionError as exc:
                self.repository.transition_job(
                    job_id=job_id,
                    target=JobStatus.FAILED,
                    error_message=exc.safe_message,
                )
                if self.delivery_service is not None:
                    self.delivery_service.enqueue_job_failure(
                        job_id=job_id,
                        reason=exc.safe_message,
                        error_code=exc.error_code,
                        correlation_id=correlation_id,
                    )
                return "failed"
        usable = bool((job.input_message or "").strip()) or any(
            item.readability_status in {"AVAILABLE", "PARTIAL"}
            or (item.readability_status == "NOT_REQUIRED" and item.status == "READY")
            for item in attachments
        )
        if usable:
            self.repository.transition_job(job_id=job_id, target=JobStatus.PENDING)
            return "released"
        message = "当前MVP无法理解仅图片消息，或附件没有可用文本；请补充文字或上传支持的文档"
        self.repository.transition_job(
            job_id=job_id,
            target=JobStatus.FAILED,
            error_message=message,
        )
        if self.delivery_service is not None:
            self.delivery_service.enqueue_job_failure(
                job_id=job_id,
                reason=message,
                error_code="attachment_input_unusable",
                correlation_id=correlation_id,
            )
        return "failed"

    def _evaluate_stored_file_gate(self, job: AgentJob, attachments: list[Any]) -> Any:
        stored = (job.business_application_route_decision or {}).get("file_turn_dependencies")
        if not isinstance(stored, list) or not stored:
            return None
        by_ordinal = {item.ordinal: item for item in attachments}
        dependencies = []
        for item in stored:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            attachment_id = str(payload.get("attachment_id") or "")
            if attachment_id.startswith("current:"):
                try:
                    ordinal = int(attachment_id.split(":", 1)[1])
                except ValueError:
                    ordinal = 0
                match = by_ordinal.get(ordinal)
                if match is not None:
                    payload["attachment_id"] = match.id
            refreshed = self.repository.refresh_file_turn_dependency_row(payload)
            dependencies.append(file_dependency_from_payload(refreshed))
        return evaluate_file_gate(ResolverDecision(dependencies=tuple(dependencies)))

    def _end_waiting_job_with_notice(
        self,
        job: AgentJob,
        gate: Any,
        correlation_id: str,
    ) -> str:
        names = tuple(item.display_name for item in gate.dependencies if item.display_name)
        title, markdown = system_notice_markdown(
            notice_kind=gate.notice_kind or "pending",
            display_names=names,
        )
        self.repository.transition_job(
            job_id=job.id,
            target=JobStatus.FAILED,
            error_message=title,
        )
        self.repository.abandon_pending_dispatch(job.id, reason_code=gate.reason_code)
        if self.delivery_service is not None:
            self.delivery_service.enqueue_system_notice(
                idempotency_key=f"file-release-notice:{job.id}",
                session_id=job.session_id,
                reply_route=job.reply_route or {"type": "none"},
                title=title,
                markdown=markdown,
                reason_code=gate.reason_code,
                correlation_id=correlation_id,
                application_publication_id=job.business_application_publication_id,
                principal_user_id=job.requester_id,
                agent_publication_id=job.agent_publication_id,
                notice_kind=gate.notice_kind,
                task_workspace_id=job.task_workspace_id,
            )
        version_ids = tuple(item.version_id for item in gate.dependencies if item.version_id)
        if (
            job.task_workspace_id
            and job.input_message_id
            and gate.reason_code == "file_readable_content_not_ready"
            and version_ids
        ):
            self.repository.record_file_readiness_blocked_turn(
                session_id=job.session_id,
                workspace_id=job.task_workspace_id,
                user_message_id=job.input_message_id,
                reason_code=gate.reason_code,
                version_ids=version_ids,
                expires_at=(datetime.now(UTC) + timedelta(hours=24)).isoformat(),
            )
        self.audit_service.record(
            "file.turn.admission.blocked",
            status="SUCCEEDED",
            summary="Waiting job ended with a file admission system notice",
            job_id=job.id,
            payload={
                "session_id": job.session_id,
                "reason_code": gate.reason_code,
                "version_ids": [
                    item.version_id for item in gate.dependencies if item.version_id
                ],
            },
        )
        return "system_notice"

    def reconcile_file_readiness_notices(self) -> dict[str, int]:
        expired = self.repository.expire_file_readiness_blocked_turns()
        notified = 0
        if self.delivery_service is None:
            return {"expired": expired, "notified": 0}
        for turn in self.repository.list_ready_file_readiness_blocked_turns():
            version_ids = tuple(self.repository.list_blocked_turn_version_ids(str(turn["id"])))
            names = self.repository.display_names_for_versions(version_ids)
            title, markdown = system_notice_markdown(notice_kind="ready", display_names=names)
            session = self.repository.get_session(str(turn["session_id"]))
            self.delivery_service.enqueue_system_notice(
                idempotency_key=f"file-ready-notice:{turn['id']}",
                session_id=str(turn["session_id"]),
                reply_route=session.reply_route or {"type": "none"},
                title=title,
                markdown=markdown,
                reason_code="file_readable_content_ready",
                correlation_id=f"file-ready:{turn['id']}",
                notice_kind="ready",
                user_message_id=str(turn["user_message_id"]),
                task_workspace_id=str(turn["workspace_id"]),
            )
            self.repository.mark_file_readiness_blocked_turn_notified(str(turn["id"]))
            notified += 1
        return {"expired": expired, "notified": notified}

    def release_if_ready(self, job_id: str, correlation_id: str) -> str:
        """Retry-safe public release hook driven by persistent attachment state."""
        return self._release_if_ready(job_id, correlation_id)

    def report_orphan_objects(self) -> list[str]:
        if self.storage is None:
            return []
        referenced = {
            str(row["object_key"])
            for row in self.repository.database.execute(
                "select object_key from message_attachment where object_key <> ''"
            )
        }
        return [key for key in self.storage.list_keys() if key not in referenced]

    def cleanup_expired(self) -> list[str]:
        if self.storage is None:
            return []
        deleted: list[str] = []
        for attachment in self.repository.list_expired_attachments(datetime.now(UTC).isoformat()):
            try:
                self.storage.delete(key=attachment.object_key)
            except Exception:
                continue
            self.repository.mark_attachment_deleted(attachment.id)
            deleted.append(attachment.id)
            self.audit_service.record(
                "attachment.deleted",
                status="SUCCEEDED",
                summary="Expired attachment object deleted",
                job_id=attachment.job_id or None,
                payload={"attachment_id": attachment.id},
            )
        return deleted


def _expired(value: object) -> bool:
    if not value:
        return False
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp <= datetime.now(UTC)
