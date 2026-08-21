from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, Protocol

from app.modules.audit.application.audit_service import AuditService
from app.modules.document_processing.domain import (
    REPRESENTATION_MEDIA_TYPES,
    ProcessingRunStatus,
    RepresentationKind,
    normalize_representation_kind,
)
from app.modules.document_processing.profile import DOCLING_TEXT_V1
from app.modules.document_processing.repository import DocumentProcessingRepository
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.storage import InternalStoredObject
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


SOURCE_GRANT_TTL = timedelta(minutes=5)
REPRESENTATION_TRANSFER_TTL = timedelta(minutes=10)


class DocumentObjectStoragePort(Protocol):
    @staticmethod
    def new_object_key(*, kind: str) -> str: ...

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        kind: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        internal_object_key: str | None = None,
    ) -> InternalStoredObject: ...

    def open_stream(self, *, internal_object_key: str) -> BinaryIO: ...

    def delete(self, *, internal_object_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SourceStreamGrantSigner:
    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) < 32:
            raise ValueError("Document source grant signing key must be at least 32 bytes")

    def issue(
        self,
        *,
        run: dict[str, Any],
        service_principal_id: str,
        now: datetime,
    ) -> str:
        payload = {
            "v": 1,
            "purpose": "document-processing-source-read",
            "principal": service_principal_id,
            "tenant_id": str(run["tenant_id"]),
            "run_id": str(run["id"]),
            "source_file_id": str(run["source_file_id"]),
            "source_version_id": str(run["source_version_id"]),
            "exp": int((now + SOURCE_GRANT_TTL).timestamp()),
        }
        body = _b64url(_canonical_json(payload))
        signature = _b64url(hmac.new(self.key, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def verify(
        self,
        token: str,
        *,
        service_principal_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        try:
            body, supplied_signature = token.split(".", 1)
            expected_signature = _b64url(
                hmac.new(self.key, body.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise ValueError("signature mismatch")
            payload = json.loads(_b64url_decode(body))
        except Exception as exc:
            raise PermissionDenied(
                "Invalid document source stream grant",
                safe_message="文档原件读取授权无效",
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("purpose") != "document-processing-source-read"
            or payload.get("principal") != service_principal_id
            or int(payload.get("exp") or 0) < int(now.timestamp())
        ):
            raise PermissionDenied(
                "Expired or mismatched document source stream grant",
                safe_message="文档原件读取授权已过期或不匹配",
            )
        return payload


class GovernedDocumentProcessingService:
    def __init__(
        self,
        repository: DocumentProcessingRepository,
        file_repository: FileWorkspaceRepository,
        storage: DocumentObjectStoragePort,
        source_grant_signer: SourceStreamGrantSigner,
        audit_service: AuditService,
        *,
        processor_version: str,
        processor_build_digest: str,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.storage = storage
        self.source_grant_signer = source_grant_signer
        self.audit_service = audit_service
        self.processor_version = processor_version
        self.processor_build_digest = processor_build_digest

    def request_processing(
        self,
        *,
        tenant_id: str,
        source_file_id: str,
        source_version_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.repository.database.unit_of_work():
            run, created = self.repository.create_or_get_run(
                tenant_id=tenant_id,
                source_file_id=source_file_id,
                source_version_id=source_version_id,
                processor_version=self.processor_version,
                processor_build_digest=self.processor_build_digest,
                profile_hash=DOCLING_TEXT_V1.profile_hash,
                actor_id=actor_id,
            )
            if created:
                payload = self.repository.safe_message_payload(
                    run_id=str(run["id"]),
                    source_version_id=source_version_id,
                    profile_hash=DOCLING_TEXT_V1.profile_hash,
                    attempt=0,
                    correlation_id=correlation_id,
                )
                self.repository.validate_safe_message_payload(payload)
                self.file_repository.add_domain_outbox(
                    event_type="file.processing.requested",
                    aggregate_type="file_processing_run",
                    aggregate_id=str(run["id"]),
                    payload=payload,
                )
        result = self.repository.get_run(str(run["id"]))
        self._audit_run(
            "file.document.processing.requested",
            run=result,
            status="CREATED" if created else "REPLAYED",
            summary="Governed document processing request recorded",
            actor_id=actor_id,
            extra={"created": created},
        )
        return result

    def claim(
        self,
        *,
        message: dict[str, Any],
        service_principal_id: str,
    ) -> dict[str, Any]:
        if service_principal_id != "file-processing-worker":
            raise PermissionDenied(
                "Document processing claim principal denied",
                safe_message="文档处理运行身份无权领取任务",
            )
        payload = self.repository.validate_safe_message_payload(message)
        run = self.repository.get_run(str(payload["run_id"]))
        if str(run["source_version_id"]) != str(payload["source_version_id"]) or str(
            run["profile_hash"]
        ) != str(payload["profile_hash"]):
            self._deny("document_processing_message_mismatch", "文档处理消息身份不匹配")
        if int(payload["attempt"]) > int(run["attempt"]):
            self._deny("document_processing_attempt_invalid", "文档处理消息尝试号无效")
        claimed, started = self.repository.claim_run(str(run["id"]))
        status = ProcessingRunStatus(str(claimed["status"]))
        if status is ProcessingRunStatus.RETRY_WAIT:
            self._deny("document_processing_retry_not_due", "文档处理重试尚未到期")
        source = self.repository.get_source_version_for_run(str(claimed["id"]))
        if started:
            self._audit_run(
                "file.document.processing.transition",
                run=claimed,
                status="RUNNING",
                summary="Document processing run claimed",
                actor_id=service_principal_id,
            )
        return {
            "run_id": str(claimed["id"]),
            "tenant_id": str(claimed["tenant_id"]),
            "source_version_id": str(claimed["source_version_id"]),
            "profile_hash": str(claimed["profile_hash"]),
            "status": status.value,
            "attempt": int(claimed["attempt"]),
            "claimed": started,
            "external_task_id": str(claimed["external_task_id"] or ""),
            "display_name": str(source["display_name"]),
            "media_type": str(source["media_type"]),
            "format_code": str(source["format_code"]),
            "size_bytes": int(source["size_bytes"]),
            "content_sha256": str(source["content_sha256"]),
        }

    def mark_submitted(self, *, run_id: str, external_task_id: str) -> dict[str, Any]:
        run = self.repository.mark_submitted(run_id, external_task_id=external_task_id)
        self._audit_run(
            "file.document.processing.transition",
            run=run,
            status="SUBMITTED",
            summary="Document processing run submitted to governed processor",
            actor_id="file-processing-worker",
        )
        return run

    def schedule_retry(
        self,
        *,
        run_id: str,
        error_code: str,
        delay_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not 1 <= delay_seconds <= DOCLING_TEXT_V1.processing_timeout_seconds:
            self._deny("document_processing_retry_delay_invalid", "文档处理重试延迟无效")
        if not error_code or not error_code.replace("_", "").isalnum():
            self._deny("document_processing_error_code_invalid", "文档处理错误分类无效")
        next_retry = (now or datetime.now(UTC)) + timedelta(seconds=delay_seconds)
        run = self.repository.schedule_retry(
            run_id,
            error_code=error_code[:128],
            next_retry_at=next_retry.isoformat(),
            clear_external_task=error_code == "docling_task_not_found",
        )
        self._audit_run(
            "file.document.processing.retry_scheduled",
            run=run,
            status="RETRY_WAIT",
            summary="Document processing retry scheduled",
            actor_id="file-processing-worker",
            extra={"delay_seconds": delay_seconds},
        )
        return run

    def prepare_source_stream(
        self,
        *,
        run_id: str,
        tenant_id: str,
        service_principal_id: str,
        now: datetime | None = None,
    ) -> dict[str, str]:
        run = self.repository.get_run(run_id)
        if str(run["tenant_id"]) != tenant_id:
            self._audit_run(
                "file.document.source_stream.denied",
                run=run,
                status="DENIED",
                summary="Cross-tenant document source stream denied",
                actor_id=service_principal_id,
                extra={"reason_code": "document_source_tenant_mismatch"},
            )
            raise PermissionDenied(
                "Cross-tenant document source stream denied",
                safe_message="不能跨租户读取文档原件",
            )
        if str(run["status"]) not in {"RUNNING", "SUBMITTED"}:
            self._audit_run(
                "file.document.source_stream.denied",
                run=run,
                status="DENIED",
                summary="Document source stream denied for processing state",
                actor_id=service_principal_id,
                extra={"reason_code": "document_processing_state_conflict"},
            )
            self._deny("document_processing_state_conflict", "当前处理任务不能读取原件")
        issued_at = now or datetime.now(UTC)
        result = {
            "run_id": run_id,
            "source_version_id": str(run["source_version_id"]),
            "grant": self.source_grant_signer.issue(
                run=run,
                service_principal_id=service_principal_id,
                now=issued_at,
            ),
            "expires_at": (issued_at + SOURCE_GRANT_TTL).isoformat(),
        }
        self._audit_run(
            "file.document.source_grant.issued",
            run=run,
            status="SUCCEEDED",
            summary="Short-lived document source stream grant issued",
            actor_id=service_principal_id,
            extra={
                "purpose": "document-processing-source-read",
                "expires_at": result["expires_at"],
            },
        )
        return result

    def open_source_stream(
        self,
        *,
        grant: str,
        service_principal_id: str,
        now: datetime | None = None,
    ) -> BinaryIO:
        try:
            payload = self.source_grant_signer.verify(
                grant,
                service_principal_id=service_principal_id,
                now=now or datetime.now(UTC),
            )
        except PermissionDenied:
            self.audit_service.record(
                "file.document.source_stream.denied",
                status="DENIED",
                summary="Document source stream grant rejected",
                actor_id=service_principal_id,
                payload={
                    "purpose": "document-processing-source-read",
                    "reason_code": "document_source_grant_invalid",
                },
            )
            raise
        run = self.repository.get_run(str(payload["run_id"]))
        expected = {
            "tenant_id": str(run["tenant_id"]),
            "source_file_id": str(run["source_file_id"]),
            "source_version_id": str(run["source_version_id"]),
        }
        if any(str(payload.get(key) or "") != value for key, value in expected.items()):
            self._audit_run(
                "file.document.source_stream.denied",
                run=run,
                status="DENIED",
                summary="Document source stream identity mismatch",
                actor_id=service_principal_id,
                extra={"reason_code": "document_source_identity_mismatch"},
            )
            raise PermissionDenied(
                "Document source stream identity mismatch",
                safe_message="文档原件读取授权不匹配",
            )
        source = self.repository.get_source_version_for_run(str(run["id"]))
        if str(source["status"]) != "AVAILABLE":
            self._audit_run(
                "file.document.source_stream.denied",
                run=run,
                status="DENIED",
                summary="Unavailable document source stream denied",
                actor_id=service_principal_id,
                extra={"reason_code": "document_source_unavailable"},
            )
            self._deny("document_source_unavailable", "待处理文件内容不可用")
        stream = self.storage.open_stream(internal_object_key=str(source["object_key"]))
        self._audit_run(
            "file.document.source_stream.opened",
            run=run,
            status="SUCCEEDED",
            summary="Document source stream opened for governed processing",
            actor_id=service_principal_id,
            extra={"purpose": "document-processing-source-read"},
        )
        return stream

    def prepare_representation_transfer(
        self,
        *,
        run_id: str,
        kind: str | RepresentationKind,
        expected_size_bytes: int,
        expected_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        representation_kind = normalize_representation_kind(kind)
        self._validate_output_metadata(
            representation_kind,
            size_bytes=expected_size_bytes,
            content_sha256=expected_sha256,
        )
        issued_at = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        staging_object_key = self.storage.new_object_key(kind="staging")
        expires_at = (issued_at + REPRESENTATION_TRANSFER_TTL).isoformat()
        transfer, created = self.repository.create_or_get_transfer(
            run_id=run_id,
            kind=representation_kind,
            token_hash=token_hash,
            expected_size_bytes=expected_size_bytes,
            expected_sha256=expected_sha256,
            staging_object_key=staging_object_key,
            expires_at=expires_at,
        )
        if not created:
            if str(transfer["status"]) == "OPEN":
                transfer = self.repository.rotate_open_transfer(
                    str(transfer["id"]),
                    token_hash=token_hash,
                    staging_object_key=staging_object_key,
                    expires_at=expires_at,
                )
            else:
                return {
                    "transfer_id": str(transfer["id"]),
                    "kind": representation_kind.value,
                    "status": str(transfer["status"]),
                    "upload_required": False,
                }
        return {
            "transfer_id": str(transfer["id"]),
            "kind": representation_kind.value,
            "status": str(transfer["status"]),
            "upload_required": True,
            "upload_token": token,
            "expires_at": expires_at,
        }

    def upload_representation(
        self,
        *,
        transfer_id: str,
        upload_token: str,
        stream: BinaryIO,
        media_type: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        transfer = self.repository.get_transfer(transfer_id)
        if not hmac.compare_digest(
            str(transfer["token_hash"]),
            hashlib.sha256(upload_token.encode("utf-8")).hexdigest(),
        ):
            raise PermissionDenied(
                "Representation upload token mismatch",
                safe_message="派生表示上传授权无效",
            )
        if datetime.fromisoformat(str(transfer["expires_at"])) < (now or datetime.now(UTC)):
            self._deny("document_representation_transfer_expired", "派生表示上传授权已过期")
        kind = RepresentationKind(str(transfer["kind"]))
        expected_media_type = REPRESENTATION_MEDIA_TYPES[kind]
        if media_type.split(";", 1)[0].strip().lower() != expected_media_type:
            self._deny("document_representation_media_type_invalid", "派生表示媒体类型无效")
        maximum = self._maximum_output_bytes(kind)
        digest = hashlib.sha256()
        size = 0
        with tempfile.TemporaryFile(mode="w+b") as staged:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    self._deny("document_representation_size_exceeded", "派生表示超过大小上限")
                digest.update(chunk)
                staged.write(chunk)
            content_sha256 = digest.hexdigest()
            if size != int(transfer["expected_size_bytes"]) or content_sha256 != str(
                transfer["expected_sha256"]
            ):
                self._deny("document_representation_digest_mismatch", "派生表示大小或摘要不一致")
            staged.seek(0)
            self._validate_output_content(kind, staged)
            staged.seek(0)
            stored = self.storage.put_stream(
                staged,
                kind="staging",
                content_type=expected_media_type,
                content_sha256=content_sha256,
                size_bytes=size,
                internal_object_key=str(transfer["staging_object_key"]),
            )
        staged_transfer = self.repository.mark_transfer_staged(
            transfer_id,
            received_size_bytes=stored.size_bytes,
            received_sha256=stored.content_sha256,
        )
        run = self.repository.get_run(str(staged_transfer["processing_run_id"]))
        self._audit_run(
            "file.document.representation.staged",
            run=run,
            status="STAGED",
            summary="Governed document representation staged",
            actor_id="file-processing-worker",
            extra={"kind": kind.value, "output_size_bytes": stored.size_bytes},
        )
        return staged_transfer

    def finalize(
        self,
        *,
        run_id: str,
        partial: bool,
        page_count: int | None,
        processing_time_ms: int | None,
    ) -> list[dict[str, Any]]:
        outputs: dict[RepresentationKind, dict[str, Any]] = {}
        for kind in (RepresentationKind.MARKDOWN, RepresentationKind.DOCLING_JSON):
            transfer = self.repository.database.execute_one(
                """
                select * from file_representation_transfer
                 where processing_run_id = ? and kind = ?
                """,
                (run_id, kind.value),
            )
            if transfer is None or str(transfer["status"]) not in {"STAGED", "FINALIZED"}:
                self._deny("document_representation_incomplete", "文档派生表示尚未完整")
            outputs[kind] = {
                "transfer_id": str(transfer["id"]),
                "representation_id": f"file_representation_{uuid.uuid4().hex}",
                "media_type": REPRESENTATION_MEDIA_TYPES[kind],
                "size_bytes": int(transfer["received_size_bytes"]),
                "content_sha256": str(transfer["received_sha256"]),
                "object_key": str(transfer["staging_object_key"]),
            }
        with self.repository.database.unit_of_work():
            representations = self.repository.finalize_representations(
                run_id=run_id,
                terminal_status=(
                    ProcessingRunStatus.PARTIAL if partial else ProcessingRunStatus.SUCCEEDED
                ),
                outputs=outputs,
                page_count=page_count,
                processing_time_ms=processing_time_ms,
            )
            self._record_completion(self.repository.get_run(run_id))
        completed = self.repository.get_run(run_id)
        self._audit_run(
            "file.document.processing.completed",
            run=completed,
            status=str(completed["status"]),
            summary="Governed document processing completed",
            actor_id="file-processing-worker",
            extra={
                "representation_sizes": {
                    str(item["kind"]): int(item["size_bytes"])
                    for item in representations
                }
            },
        )
        return representations

    def complete_without_text(
        self,
        *,
        run_id: str,
        page_count: int | None,
        processing_time_ms: int | None,
    ) -> dict[str, Any]:
        with self.repository.database.unit_of_work():
            run = self.repository.transition_run(
                run_id,
                target=ProcessingRunStatus.NO_TEXT,
                error_code="no_text",
                page_count=page_count,
                processing_time_ms=processing_time_ms,
            )
            self._record_completion(run)
        self._audit_run(
            "file.document.processing.completed",
            run=run,
            status="NO_TEXT",
            summary="Governed document processing completed without readable text",
            actor_id="file-processing-worker",
        )
        return run

    def fail(
        self,
        *,
        run_id: str,
        error_code: str,
        processing_time_ms: int | None = None,
    ) -> dict[str, Any]:
        if not error_code or len(error_code) > 128 or not error_code.replace("_", "").isalnum():
            self._deny("document_processing_error_code_invalid", "文档处理错误分类无效")
        with self.repository.database.unit_of_work():
            run = self.repository.transition_run(
                run_id,
                target=ProcessingRunStatus.FAILED,
                error_code=error_code,
                processing_time_ms=processing_time_ms,
            )
            self._record_completion(run)
        self._audit_run(
            "file.document.processing.completed",
            run=run,
            status="FAILED",
            summary="Governed document processing failed",
            actor_id="file-processing-worker",
        )
        return run

    def cleanup_expired_transfers(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, int]:
        expired = self.repository.expire_open_transfers(
            now=(now or datetime.now(UTC)).isoformat(), limit=limit
        )
        deleted = failed = 0
        for transfer in expired:
            try:
                self.storage.delete(internal_object_key=str(transfer["staging_object_key"]))
                deleted += 1
            except Exception:
                failed += 1
        return {"expired": len(expired), "deleted": deleted, "failed": failed}

    def reconcile_attachment_readability(self, *, limit: int = 100) -> dict[str, Any]:
        return self.repository.reconcile_attachment_readability(limit=limit)

    def _record_completion(self, run: dict[str, Any]) -> None:
        payload = self.repository.safe_message_payload(
            run_id=str(run["id"]),
            source_version_id=str(run["source_version_id"]),
            profile_hash=str(run["profile_hash"]),
            attempt=int(run["attempt"]),
            correlation_id=str(run["id"]),
        )
        payload["status"] = str(run["status"])
        error_code = str(run.get("error_code") or "")
        if error_code:
            payload["error_code"] = error_code[:128]
        self.file_repository.add_domain_outbox(
            event_type="file.processing.completed",
            aggregate_type="file_processing_run",
            aggregate_id=str(run["id"]),
            payload=payload,
        )

    def _audit_run(
        self,
        event_type: str,
        *,
        run: dict[str, Any],
        status: str,
        summary: str,
        actor_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        context = self.repository.processing_context(str(run["id"]))
        payload: dict[str, Any] = {
            "run_id": str(run["id"]),
            "source_version_id": str(run["source_version_id"]),
            "tenant_id": str(run["tenant_id"]),
            "profile_code": str(run["profile_code"]),
            "profile_hash": str(run["profile_hash"]),
            "processor_version": str(run["processor_version"]),
            "processor_build_digest": str(run["processor_build_digest"]),
            "source_size_bytes": int(run["source_size_bytes"]),
            "processing_status": str(run["status"]),
            "attempt": int(run["attempt"]),
            "error_code": str(run.get("error_code") or "")[:128],
            "page_count": run.get("page_count"),
            "processing_time_ms": run.get("processing_time_ms"),
            "business_application_id": context["business_application_id"],
            "business_application_code": context["business_application_code"],
            "business_application_publication_id": context[
                "business_application_publication_id"
            ],
        }
        if extra:
            payload.update(extra)
        self.audit_service.record(
            event_type,
            status=status,
            summary=summary,
            job_id=str(context["job_id"] or "") or None,
            actor_id=actor_id,
            payload=payload,
        )

    @staticmethod
    def _maximum_output_bytes(kind: RepresentationKind) -> int:
        if kind is RepresentationKind.MARKDOWN:
            return DOCLING_TEXT_V1.max_markdown_bytes
        return DOCLING_TEXT_V1.max_docling_json_bytes

    @classmethod
    def _validate_output_metadata(
        cls,
        kind: RepresentationKind,
        *,
        size_bytes: int,
        content_sha256: str,
    ) -> None:
        if size_bytes < 1 or size_bytes > cls._maximum_output_bytes(kind):
            cls._deny("document_representation_size_exceeded", "派生表示大小无效")
        if len(content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in content_sha256
        ):
            cls._deny("document_representation_digest_invalid", "派生表示摘要无效")

    @classmethod
    def _validate_output_content(
        cls,
        kind: RepresentationKind,
        stream: BinaryIO,
    ) -> None:
        try:
            text = stream.read().decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise NonRetryableExecutionError(
                "Document representation is not UTF-8",
                safe_message="派生表示不是有效 UTF-8",
                error_code="document_representation_encoding_invalid",
            ) from exc
        if kind is RepresentationKind.MARKDOWN:
            if not text.strip():
                cls._deny("document_representation_empty", "Markdown 表示不能为空")
            return
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NonRetryableExecutionError(
                "Docling JSON representation is invalid",
                safe_message="Docling JSON 表示无效",
                error_code="document_representation_json_invalid",
            ) from exc
        if not isinstance(value, dict):
            cls._deny("document_representation_json_invalid", "Docling JSON 必须是对象")

    @staticmethod
    def _deny(code: str, safe_message: str) -> None:
        raise NonRetryableExecutionError(
            "Governed document processing request denied",
            safe_message=safe_message,
            error_code=code,
        )


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
