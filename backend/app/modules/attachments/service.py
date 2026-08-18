from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.attachments.domain import (
    AttachmentExtractor,
    AttachmentImporter,
    MediaDownloader,
    ObjectStorage,
)
from app.modules.attachments.extraction import SafeAttachmentExtractor
from app.modules.audit.application.audit_service import AuditService
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.document_processing.profile import DOCLING_TEXT_V1
from app.modules.file_workspace.manifest_service import JobFileManifestService
from app.modules.file_workspace.text_format_policy import get_text_format_policy
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
        storage: ObjectStorage | None,
        extractor: AttachmentExtractor,
        settings: AttachmentSettings,
        importer: AttachmentImporter | None = None,
        delivery_service: ResultDeliveryService | None = None,
        file_manifest_service: JobFileManifestService | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.audit_service = audit_service
        self.credential_cipher = credential_cipher
        self.downloader = downloader
        self.storage = storage
        self.importer = importer
        self.extractor = extractor
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
            policy = get_text_format_policy(context.get("file_format_policy_version"))
            text_definition = next(
                (item for item in policy.formats if item.extension == suffix),
                None,
            )
            document_definition = next(
                (item for item in DOCLING_TEXT_V1.source_formats if suffix in item.extensions),
                None,
            )
            workspace_import = self.importer is not None and bool(
                context.get("task_workspace_id")
            )
            task_text = workspace_import and text_definition is not None
            governed_document = workspace_import and document_definition is not None
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
                detected_mime = self.extractor.inspect(
                    file_name=attachment.file_name,
                    data=data,
                )
            if detected_mime.startswith("image/"):
                if not isinstance(self.extractor, SafeAttachmentExtractor):
                    raise NonRetryableExecutionError(
                        "Image normalizer unavailable", safe_message="图片校验暂时不可用"
                    )
                data, detected_mime = self.extractor.normalize_image(data=data)
            digest = hashlib.sha256(data).hexdigest()
            object_bucket: str | None = None
            object_key: str | None = None
            document_readability_pending = False
            if self.importer is not None:
                assert self.importer is not None
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
                stored_size = imported.size_bytes
                document_readability_pending = imported.readability_status == "PENDING"
            else:
                if self.storage is None:
                    raise RetryableExecutionError(
                        "Attachment storage boundary is unavailable",
                        safe_message="附件导入服务暂时不可用",
                        error_code="file_service_unavailable",
                    )
                extension = Path(attachment.file_name).suffix.lower().lstrip(".") or "bin"
                legacy_object_key = f"attachments/{attachment.id}/{digest}.{extension}"
                stored = self.storage.put(
                    key=legacy_object_key,
                    data=data,
                    content_type=detected_mime,
                    sha256=digest,
                )
                stored_size = stored.size_bytes
                object_bucket = stored.bucket
                object_key = stored.key
            if task_text:
                self.repository.update_attachment(
                    attachment_id,
                    status="READY",
                    detected_mime=detected_mime,
                    size_bytes=stored_size,
                    sha256=digest,
                    object_bucket=object_bucket,
                    object_key=object_key,
                    clear_credential=True,
                )
            elif document_readability_pending:
                # Governed document processing owns extraction for this source.
                # The source download is terminal, while Job release remains gated
                # by the separately persisted readability state.
                self.repository.update_attachment(
                    attachment_id,
                    status="READY",
                    detected_mime=detected_mime,
                    size_bytes=stored_size,
                    sha256=digest,
                    object_bucket=object_bucket,
                    object_key=object_key,
                    clear_credential=True,
                )
            elif detected_mime.startswith("image/"):
                self.repository.update_attachment(
                    attachment_id,
                    status="stored_not_interpreted",
                    detected_mime=detected_mime,
                    size_bytes=stored_size,
                    sha256=digest,
                    object_bucket=object_bucket,
                    object_key=object_key,
                    clear_credential=True,
                )
            else:
                self.repository.update_attachment(
                    attachment_id,
                    status="EXTRACTING",
                    detected_mime=detected_mime,
                    size_bytes=stored_size,
                    sha256=digest,
                    object_bucket=object_bucket,
                    object_key=object_key,
                    clear_credential=True,
                )
                content = self.extractor.extract(file_name=attachment.file_name, data=data)
                self.repository.save_attachment_content(
                    attachment_id=attachment_id,
                    plain_text=content.text,
                    segments=content.segments,
                    parser_version=content.parser_version,
                    truncated=content.truncated,
                )
                self.repository.update_attachment(attachment_id, status="READY")
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
            code = getattr(exc, "safe_message", str(exc))[:100]
            self.repository.update_attachment(
                attachment_id,
                status="REJECTED" if isinstance(exc, NonRetryableExecutionError) else "FAILED",
                failure_code=code,
                clear_credential=True,
            )
            self.publisher.publish_attachment_dead_letter(attachment_id, correlation_id, code)
            self.audit_service.record(
                "attachment.rejected",
                status="FAILED",
                summary="Attachment processing failed safely",
                job_id=attachment.job_id or None,
                payload={"attachment_id": attachment_id, "failure_code": code},
            )
        return self._release_attachment_if_ready(attachment_id, correlation_id)

    def _release_attachment_if_ready(self, attachment_id: str, correlation_id: str) -> str:
        attachment = self.repository.get_attachment(attachment_id)
        if not attachment.job_id:
            return "staged"
        return self._release_if_ready(attachment.job_id, correlation_id)

    @operation_unit_of_work(lambda service: service.repository.database)
    def _release_if_ready(self, job_id: str, correlation_id: str) -> str:
        attachments = self.repository.list_attachments(job_id)
        if (
            not attachments
            or any(item.status not in TERMINAL_ATTACHMENT_STATUSES for item in attachments)
            or any(item.readability_status == "PENDING" for item in attachments)
        ):
            return "waiting"
        job = self.repository.get_job(job_id)
        if job.status != JobStatus.WAITING_INPUT:
            return job.status.value.lower()
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
