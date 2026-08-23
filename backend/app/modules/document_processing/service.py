from __future__ import annotations

import base64
import hashlib
import hmac
import io
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
    PictureItemStatus,
    ProcessingRunStatus,
    RepresentationKind,
    normalize_representation_kind,
)
from app.modules.document_processing.layout_ocr import validate_layout_representation
from app.modules.document_processing.layout_ocr import validate_picture_result
from app.modules.document_processing.provider import DocumentProcessorFailure
from app.modules.document_processing.profile import (
    DOCLING_LAYOUT_OCR_V2,
    DocumentProcessingProfileCode,
    require_document_processing_profile,
)
from app.modules.document_processing.repository import DocumentProcessingRepository
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.quota import WorkspaceQuotaService
from app.modules.file_workspace.storage import InternalStoredObject
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


SOURCE_GRANT_TTL = timedelta(minutes=5)
REPRESENTATION_TRANSFER_TTL = timedelta(minutes=10)
PICTURE_TRANSFER_TTL = timedelta(minutes=10)


class DocumentObjectStoragePort(Protocol):
    @staticmethod
    def new_object_key(*, kind: str, canonical_extension: str) -> str: ...

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        kind: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        canonical_extension: str,
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
        self.workspace_quota = WorkspaceQuotaService(file_repository.database)
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
        profile_code: str = DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V2.value,
    ) -> dict[str, Any]:
        profile = require_document_processing_profile(profile_code)
        requested_at = datetime.now(UTC)
        run_deadline_at: str | None = None
        if profile.layout_ocr_options is not None:
            limits = dict(profile.layout_ocr_options["limits"])
            run_deadline_at = (
                requested_at + timedelta(seconds=int(limits["run_deadline_seconds"]))
            ).isoformat()
        with self.repository.database.unit_of_work():
            run, created = self.repository.create_or_get_run(
                tenant_id=tenant_id,
                source_file_id=source_file_id,
                source_version_id=source_version_id,
                processor_version=self.processor_version,
                processor_build_digest=self.processor_build_digest,
                profile_code=profile.code.value,
                profile_hash=profile.profile_hash,
                required_output_kinds=profile.output_kinds,
                run_deadline_at=run_deadline_at,
                actor_id=actor_id,
            )
            if created:
                payload = self.repository.safe_message_payload(
                    run_id=str(run["id"]),
                    source_version_id=source_version_id,
                    profile_hash=profile.profile_hash,
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
            "source_file_id": str(claimed["source_file_id"]),
            "source_version_id": str(claimed["source_version_id"]),
            "profile_code": str(claimed["profile_code"]),
            "profile_hash": str(claimed["profile_hash"]),
            "required_output_kinds": [
                kind.value for kind in self.repository.required_output_kinds(claimed)
            ],
            "run_deadline_at": str(claimed["run_deadline_at"] or ""),
            "stage_code": str(claimed["stage_code"]),
            "assembly_status": str(claimed["assembly_status"]),
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
        if not 1 <= delay_seconds <= DOCLING_LAYOUT_OCR_V2.processing_timeout_seconds:
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
        run = self.repository.get_run(run_id)
        if representation_kind not in self.repository.required_output_kinds(run):
            self._deny("document_representation_kind_invalid", "当前Profile不需要此派生表示")
        self._validate_output_metadata(
            representation_kind,
            run=run,
            size_bytes=expected_size_bytes,
            content_sha256=expected_sha256,
        )
        issued_at = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        staging_object_key = self.storage.new_object_key(
            kind="staging",
            canonical_extension=(
                ".md" if representation_kind is RepresentationKind.MARKDOWN else ".json"
            ),
        )
        expires_at = (issued_at + REPRESENTATION_TRANSFER_TTL).isoformat()
        workspace_id = self._workspace_for_run(run)
        operation_id = f"representation:{run_id}:{representation_kind.value}"
        self.workspace_quota.reserve(
            workspace_id=workspace_id,
            operation_type="FILE_PROCESSING",
            operation_id=operation_id,
            logical_file_slots=0,
            billable_bytes=expected_size_bytes,
            expires_at=expires_at,
            now=issued_at.isoformat(),
        )
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

    def prepare_parent_artifact_transfer(
        self,
        *,
        run_id: str,
        expected_size_bytes: int,
        expected_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        profile = require_document_processing_profile(
            run["profile_code"], profile_hash=run["profile_hash"]
        )
        if expected_size_bytes < 1 or expected_size_bytes > profile.max_markdown_bytes:
            self._deny("document_parent_artifact_size_exceeded", "父Markdown大小无效")
        self._validate_digest(expected_sha256)
        issued_at = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        expires_at = (issued_at + PICTURE_TRANSFER_TTL).isoformat()
        workspace_id = self._workspace_for_run(run)
        operation_id = f"parent:{run_id}"
        self.workspace_quota.reserve(
            workspace_id=workspace_id,
            operation_type="FILE_PROCESSING",
            operation_id=operation_id,
            logical_file_slots=0,
            billable_bytes=expected_size_bytes,
            expires_at=expires_at,
            now=issued_at.isoformat(),
        )
        transfer, created = self.repository.create_or_get_parent_artifact_transfer(
            run_id=run_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expected_size_bytes=expected_size_bytes,
            expected_sha256=expected_sha256,
            staging_object_key=self.storage.new_object_key(
                kind="staging",
                canonical_extension=".md",
            ),
            expires_at=expires_at,
        )
        if not created:
            return {
                "transfer_id": str(transfer["id"]),
                "status": str(transfer["status"]),
                "upload_required": False,
            }
        return {
            "transfer_id": str(transfer["id"]),
            "status": str(transfer["status"]),
            "upload_required": True,
            "upload_token": token,
            "expires_at": str(transfer["expires_at"]),
        }

    def upload_parent_artifact(
        self,
        *,
        transfer_id: str,
        upload_token: str,
        stream: BinaryIO,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        transfer = self.repository.get_parent_artifact_transfer(transfer_id)
        self._verify_transfer_token(transfer, upload_token=upload_token, now=now)
        body = self._bounded_stream(
            stream,
            maximum=int(transfer["expected_size_bytes"]),
            size_error_code="document_parent_artifact_size_exceeded",
        )
        try:
            text = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise NonRetryableExecutionError(
                "Parent Markdown is not UTF-8",
                safe_message="父Markdown编码无效",
                error_code="document_parent_artifact_encoding_invalid",
            ) from exc
        if not text.strip():
            self._deny("document_parent_artifact_empty", "父Markdown不能为空")
        self._verify_expected_body(transfer, body)
        stored = self.storage.put_stream(
            io.BytesIO(body),
            kind="staging",
            content_type="text/markdown",
            content_sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            canonical_extension=".md",
            internal_object_key=str(transfer["staging_object_key"]),
        )
        result = self.repository.finalize_parent_artifact_transfer(
            transfer_id=transfer_id,
            received_size_bytes=stored.size_bytes,
            received_sha256=stored.content_sha256,
        )
        run = self.repository.get_run(str(transfer["processing_run_id"]))
        self.workspace_quota.finalize_operation(
            workspace_id=self._workspace_for_run(run),
            operation_type="FILE_PROCESSING",
            operation_id=f"parent:{run['id']}",
            committed=True,
            now=(now or datetime.now(UTC)).isoformat(),
        )
        return result

    def open_parent_artifact(self, *, run_id: str) -> BinaryIO:
        transfer = self.repository.parent_artifact_for_run(run_id)
        if str(transfer["status"]) != "FINALIZED":
            self._deny("document_parent_artifact_unavailable", "父Markdown暂存内容不可用")
        return self.storage.open_stream(internal_object_key=str(transfer["staging_object_key"]))

    def prepare_picture_asset_transfer(
        self,
        *,
        run_id: str,
        normalized_sha256: str,
        media_type: str,
        original_width_pixels: int,
        original_height_pixels: int,
        width_pixels: int,
        height_pixels: int,
        normalization_transform: dict[str, Any],
        size_bytes: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_media_type = media_type.split(";", 1)[0].strip().lower()
        canonical_extension = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(normalized_media_type)
        if canonical_extension is None:
            self._deny("document_picture_media_type_invalid", "内嵌图片媒体类型无效")
        assert canonical_extension is not None
        run = self.repository.get_run(run_id)
        profile = require_document_processing_profile(
            run["profile_code"], profile_hash=run["profile_hash"]
        )
        if profile.layout_ocr_options is None:
            self._deny("document_picture_profile_invalid", "当前Profile不处理内嵌图片")
        limits = profile.layout_ocr_options["limits"]
        if (
            width_pixels < 1
            or height_pixels < 1
            or original_width_pixels < 1
            or original_height_pixels < 1
            or width_pixels * height_pixels > int(limits["max_picture_pixels"])
            or size_bytes < 1
            or size_bytes > int(limits["max_picture_compressed_bytes"])
        ):
            self._deny("document_picture_limit_exceeded", "内嵌图片超过安全上限")
        expected_transform = {
            "version",
            "pixel_basis",
            "office_display_transform_applied",
            "source_origin",
            "target_origin",
            "exif_orientation",
            "original_size",
            "normalized_size",
        }
        if (
            not isinstance(normalization_transform, dict)
            or set(normalization_transform) != expected_transform
            or normalization_transform.get("version") != "embedded-media-exif-orientation/v1"
            or normalization_transform.get("pixel_basis") != "RAW_EMBEDDED_MEDIA_AFTER_EXIF"
            or normalization_transform.get("office_display_transform_applied") is not False
            or normalization_transform.get("source_origin") != "TOPLEFT"
            or normalization_transform.get("target_origin") != "TOPLEFT"
            or normalization_transform.get("exif_orientation") not in range(1, 9)
            or normalization_transform.get("original_size")
            != [original_width_pixels, original_height_pixels]
            or normalization_transform.get("normalized_size") != [width_pixels, height_pixels]
        ):
            self._deny("document_picture_transform_invalid", "内嵌图片变换无效")
        self._validate_digest(normalized_sha256)
        issued_at = now or datetime.now(UTC)
        expires_at = (issued_at + PICTURE_TRANSFER_TTL).isoformat()
        workspace_id = self._workspace_for_run(run)
        operation_id = f"picture:{run_id}:{normalized_sha256}"
        self.workspace_quota.reserve(
            workspace_id=workspace_id,
            operation_type="DERIVATIVE_WRITE",
            operation_id=operation_id,
            logical_file_slots=0,
            billable_bytes=size_bytes,
            expires_at=expires_at,
            now=issued_at.isoformat(),
        )
        object_key = self.storage.new_object_key(
            kind="staging",
            canonical_extension=canonical_extension,
        )
        asset, _ = self.repository.create_or_get_picture_asset(
            run_id=run_id,
            normalized_sha256=normalized_sha256,
            media_type=normalized_media_type,
            original_width_pixels=original_width_pixels,
            original_height_pixels=original_height_pixels,
            width_pixels=width_pixels,
            height_pixels=height_pixels,
            normalization_transform_json=json.dumps(
                normalization_transform, sort_keys=True, separators=(",", ":")
            ),
            size_bytes=size_bytes,
            object_key=object_key,
        )
        token = secrets.token_urlsafe(32)
        transfer, created = self.repository.create_or_get_picture_asset_transfer(
            picture_asset_id=str(asset["id"]),
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            staging_object_key=str(asset["object_key"]),
            expires_at=expires_at,
        )
        result = {
            "picture_asset_id": str(asset["id"]),
            "transfer_id": str(transfer["id"]),
            "status": str(transfer["status"]),
            "upload_required": created,
        }
        if created:
            result.update({"upload_token": token, "expires_at": str(transfer["expires_at"])})
        return result

    def upload_picture_asset(
        self,
        *,
        transfer_id: str,
        upload_token: str,
        stream: BinaryIO,
        media_type: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        transfer = self.repository.get_picture_asset_transfer(transfer_id)
        self._verify_transfer_token(transfer, upload_token=upload_token, now=now)
        if media_type.split(";", 1)[0].strip().lower() != str(transfer["expected_media_type"]):
            self._deny("document_picture_media_type_invalid", "内嵌图片媒体类型无效")
        body = self._bounded_stream(
            stream,
            maximum=int(transfer["expected_size_bytes"]),
            size_error_code="document_picture_size_exceeded",
        )
        self._verify_expected_body(transfer, body)
        stored = self.storage.put_stream(
            io.BytesIO(body),
            kind="staging",
            content_type=str(transfer["expected_media_type"]),
            content_sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            canonical_extension={
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }[str(transfer["expected_media_type"])],
            internal_object_key=str(transfer["staging_object_key"]),
        )
        result = self.repository.finalize_picture_asset_transfer(
            transfer_id=transfer_id,
            received_size_bytes=stored.size_bytes,
            received_sha256=stored.content_sha256,
        )
        asset = self.repository.get_picture_asset(str(transfer["picture_asset_id"]))
        run = self.repository.get_run(str(transfer["processing_run_id"]))
        self.workspace_quota.finalize_operation(
            workspace_id=self._workspace_for_run(run),
            operation_type="DERIVATIVE_WRITE",
            operation_id=f"picture:{run['id']}:{asset['normalized_sha256']}",
            committed=True,
            now=(now or datetime.now(UTC)).isoformat(),
        )
        return result

    def register_picture_occurrence(self, **values: Any) -> dict[str, Any]:
        bbox = values.pop("parent_bbox", None)
        selection_status = str(values.pop("selection_status", "SELECTED"))
        if selection_status not in {"SELECTED", "SKIPPED_LIMIT"}:
            self._deny("document_picture_selection_invalid", "内嵌图片选择状态无效")
        row, _ = self.repository.create_or_get_picture_occurrence(
            **values,
            parent_bbox_json=(
                json.dumps(bbox, sort_keys=True, separators=(",", ":")) if bbox is not None else ""
            ),
            selection_status=selection_status,
        )
        return row

    def register_picture_item(self, **values: Any) -> dict[str, Any]:
        row, _ = self.repository.create_or_get_picture_item(**values)
        return row

    def claim_picture_item(
        self,
        *,
        picture_item_id: str,
        claim_token: str,
        claim_expires_at: str,
    ) -> tuple[dict[str, Any], bool]:
        return self.repository.claim_picture_item(
            picture_item_id=picture_item_id,
            claim_token=claim_token,
            claim_expires_at=claim_expires_at,
        )

    def picture_item_context(self, *, picture_item_id: str, claimed: bool) -> dict[str, Any]:
        item = self.repository.get_picture_item(picture_item_id)
        asset = self.repository.get_picture_asset(str(item["picture_asset_id"]))
        run = self.repository.get_run(str(item["processing_run_id"]))
        return {
            "picture_item_id": str(item["id"]),
            "run_id": str(run["id"]),
            "profile_hash": str(run["profile_hash"]),
            "run_deadline_at": str(run["run_deadline_at"] or ""),
            "status": str(item["status"]),
            "attempt": int(item["attempt"]),
            "claimed": claimed,
            "external_task_id": str(item["external_task_id"] or ""),
            "media_type": str(asset["media_type"]),
            "size_bytes": int(asset["size_bytes"]),
            "content_sha256": str(asset["normalized_sha256"]),
            "original_width_pixels": int(asset["original_width_pixels"]),
            "original_height_pixels": int(asset["original_height_pixels"]),
            "width_pixels": int(asset["width_pixels"]),
            "height_pixels": int(asset["height_pixels"]),
            "normalization_transform": json.loads(str(asset["normalization_transform_json"])),
        }

    def open_picture_asset(self, *, picture_item_id: str) -> BinaryIO:
        item = self.repository.get_picture_item(picture_item_id)
        asset = self.repository.get_picture_asset(str(item["picture_asset_id"]))
        if str(asset["status"]) != "AVAILABLE":
            self._deny("document_picture_asset_unavailable", "内嵌图片内容不可用")
        return self.storage.open_stream(internal_object_key=str(asset["object_key"]))

    def mark_picture_submitted(
        self,
        *,
        picture_item_id: str,
        external_task_id: str,
    ) -> dict[str, Any]:
        return self.repository.mark_picture_item_submitted(
            picture_item_id=picture_item_id,
            external_task_id=external_task_id,
        )

    def complete_picture_item(
        self,
        *,
        picture_item_id: str,
        status: str,
        result_size_bytes: int | None,
        result_sha256: str,
        error_code: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        try:
            terminal = PictureItemStatus(status)
        except ValueError as exc:
            raise NonRetryableExecutionError(
                "Picture item status is invalid",
                safe_message="图片处理完成状态无效",
                error_code="document_picture_terminal_invalid",
            ) from exc
        return self.repository.complete_picture_item(
            picture_item_id=picture_item_id,
            status=terminal,
            result_size_bytes=result_size_bytes,
            result_sha256=result_sha256,
            error_code=error_code,
            correlation_id=correlation_id,
        )

    def retry_picture_item(
        self,
        *,
        picture_item_id: str,
        error_code: str,
        delay_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not 1 <= delay_seconds <= 600:
            self._deny("document_picture_retry_delay_invalid", "图片处理重试延迟无效")
        if not error_code or not error_code.replace("_", "").isalnum():
            self._deny("document_picture_error_code_invalid", "图片处理错误分类无效")
        return self.repository.schedule_picture_item_retry(
            picture_item_id=picture_item_id,
            error_code=error_code,
            next_retry_at=(
                (now or datetime.now(UTC)) + timedelta(seconds=delay_seconds)
            ).isoformat(),
            clear_external_task=error_code == "docling_task_not_found",
        )

    def prepare_picture_result_transfer(
        self,
        *,
        picture_item_id: str,
        expected_size_bytes: int,
        expected_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        item = self.repository.get_picture_item(picture_item_id)
        run = self.repository.get_run(str(item["processing_run_id"]))
        maximum = self._maximum_output_bytes(RepresentationKind.OCR_LAYOUT_JSON, run=run)
        if expected_size_bytes < 1 or expected_size_bytes > maximum:
            self._deny("document_picture_result_size_exceeded", "图片OCR结果大小无效")
        self._validate_digest(expected_sha256)
        token = secrets.token_urlsafe(32)
        issued_at = now or datetime.now(UTC)
        workspace_id = self._workspace_for_run(run)
        operation_id = f"picture-result:{picture_item_id}"
        expires_at = (issued_at + PICTURE_TRANSFER_TTL).isoformat()
        self.workspace_quota.reserve(
            workspace_id=workspace_id,
            operation_type="DERIVATIVE_WRITE",
            operation_id=operation_id,
            logical_file_slots=0,
            billable_bytes=expected_size_bytes,
            expires_at=expires_at,
            now=issued_at.isoformat(),
        )
        transfer, created = self.repository.create_or_get_picture_result_transfer(
            picture_item_id=picture_item_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expected_size_bytes=expected_size_bytes,
            expected_sha256=expected_sha256,
            staging_object_key=self.storage.new_object_key(
                kind="staging",
                canonical_extension=".json",
            ),
            expires_at=expires_at,
        )
        result = {
            "transfer_id": str(transfer["id"]),
            "status": str(transfer["status"]),
            "upload_required": created,
        }
        if created:
            result.update({"upload_token": token, "expires_at": str(transfer["expires_at"])})
        return result

    def upload_picture_result(
        self,
        *,
        transfer_id: str,
        upload_token: str,
        stream: BinaryIO,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        transfer = self.repository.get_picture_result_transfer(transfer_id)
        self._verify_transfer_token(transfer, upload_token=upload_token, now=now)
        body = self._bounded_stream(
            stream,
            maximum=int(transfer["expected_size_bytes"]),
            size_error_code="document_picture_result_size_exceeded",
        )
        self._verify_expected_body(transfer, body)
        item = self.repository.get_picture_item(str(transfer["picture_item_id"]))
        asset = self.repository.get_picture_asset(str(item["picture_asset_id"]))
        run = self.repository.get_run(str(item["processing_run_id"]))
        profile = require_document_processing_profile(
            run["profile_code"], profile_hash=run["profile_hash"]
        )
        try:
            result = validate_picture_result(body, profile=profile)
        except DocumentProcessorFailure as exc:
            self._deny(exc.error_code, "图片OCR布局结果无效")
        if str(result["picture_sha256"]) != str(asset["normalized_sha256"]):
            self._deny("document_picture_result_identity_mismatch", "图片OCR结果身份不匹配")
        stored = self.storage.put_stream(
            io.BytesIO(body),
            kind="staging",
            content_type="application/json",
            content_sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            canonical_extension=".json",
            internal_object_key=str(transfer["staging_object_key"]),
        )
        result_row = self.repository.finalize_picture_result_transfer(
            transfer_id=transfer_id,
            received_size_bytes=stored.size_bytes,
            received_sha256=stored.content_sha256,
        )
        self.workspace_quota.finalize_operation(
            workspace_id=self._workspace_for_run(run),
            operation_type="DERIVATIVE_WRITE",
            operation_id=f"picture-result:{item['id']}",
            committed=True,
            now=(now or datetime.now(UTC)).isoformat(),
        )
        return result_row

    def open_picture_result(self, *, picture_item_id: str) -> BinaryIO:
        transfer = self.repository.database.execute_one(
            """
            select * from document_picture_result_transfer
             where picture_item_id = ?
            """,
            (picture_item_id,),
        )
        if transfer is None or str(transfer["status"]) != "FINALIZED":
            self._deny("document_picture_result_unavailable", "图片OCR结果不可用")
        return self.storage.open_stream(internal_object_key=str(transfer["staging_object_key"]))

    def complete_parent_parse(self, *, run_id: str, correlation_id: str) -> dict[str, Any]:
        return self.repository.complete_parent_parse(run_id=run_id, correlation_id=correlation_id)

    def claim_assembly(self, *, run_id: str, claim_token: str) -> tuple[dict[str, Any], bool]:
        return self.repository.claim_assembly(run_id=run_id, claim_token=claim_token)

    def assembly_context(self, *, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        occurrences = self.repository.database.execute(
            """
            select o.*, a.normalized_sha256, i.id as picture_item_id,
                   case when o.selection_status = 'SKIPPED_LIMIT'
                        then 'SKIPPED_LIMIT' else i.status end as picture_status,
                   case when o.selection_status = 'SKIPPED_LIMIT'
                        then 'picture_soft_limit' else i.error_code end as picture_error_code
              from document_picture_occurrence o
              join document_picture_asset a on a.id = o.picture_asset_id
              join document_picture_processing_item i
                on i.processing_run_id = o.processing_run_id
               and i.picture_asset_id = o.picture_asset_id
             where o.processing_run_id = ?
             order by o.occurrence_index
            """,
            (run_id,),
        )
        items: list[dict[str, Any]] = []
        for row in occurrences:
            if str(row["source_format"]) == "DOCX":
                anchor: dict[str, Any] = {
                    "source_format": "DOCX",
                    "picture_ref": str(row["picture_ref"]),
                    "parent_ref": str(row["parent_ref"]),
                    "parent_label": str(row["parent_label"]),
                    "parent_ordinal": int(row["parent_ordinal"]),
                }
            else:
                anchor = {
                    "source_format": "PPTX",
                    "slide_no": int(row["slide_no"]),
                    "shape_ref": str(row["picture_ref"]),
                    "slide_bbox": json.loads(str(row["parent_bbox_json"])),
                }
            items.append(
                {
                    "occurrence_index": int(row["occurrence_index"]),
                    "picture_item_id": str(row["picture_item_id"]),
                    "picture_ref": str(row["picture_ref"]),
                    "picture_sha256": str(row["normalized_sha256"]),
                    "parent_anchor": anchor,
                    "status": str(row["picture_status"]),
                    "error_code": str(row["picture_error_code"] or ""),
                }
            )
        return {
            "run_id": str(run["id"]),
            "source_file_id": str(run["source_file_id"]),
            "source_version_id": str(run["source_version_id"]),
            "profile_code": str(run["profile_code"]),
            "profile_hash": str(run["profile_hash"]),
            "run_deadline_at": str(run["run_deadline_at"] or ""),
            "assembly_status": str(run["assembly_status"]),
            "occurrences": items,
        }

    def finish_assembly(self, *, run_id: str, succeeded: bool) -> dict[str, Any]:
        return self.repository.finish_assembly(run_id=run_id, succeeded=succeeded)

    def retry_assembly(self, *, run_id: str) -> dict[str, Any]:
        return self.repository.retry_assembly(run_id=run_id)

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
        run = self.repository.get_run(str(transfer["processing_run_id"]))
        expected_media_type = REPRESENTATION_MEDIA_TYPES[kind]
        if media_type.split(";", 1)[0].strip().lower() != expected_media_type:
            self._deny("document_representation_media_type_invalid", "派生表示媒体类型无效")
        maximum = self._maximum_output_bytes(kind, run=run)
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
            self._validate_output_content(kind, staged, run=run)
            staged.seek(0)
            stored = self.storage.put_stream(
                staged,
                kind="staging",
                content_type=expected_media_type,
                content_sha256=content_sha256,
                size_bytes=size,
                canonical_extension=(".md" if kind is RepresentationKind.MARKDOWN else ".json"),
                internal_object_key=str(transfer["staging_object_key"]),
            )
        staged_transfer = self.repository.mark_transfer_staged(
            transfer_id,
            received_size_bytes=stored.size_bytes,
            received_sha256=stored.content_sha256,
        )
        run = self.repository.get_run(str(staged_transfer["processing_run_id"]))
        self.workspace_quota.finalize_operation(
            workspace_id=self._workspace_for_run(run),
            operation_type="FILE_PROCESSING",
            operation_id=f"representation:{run['id']}:{kind.value}",
            committed=True,
            now=(now or datetime.now(UTC)).isoformat(),
        )
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
        run = self.repository.get_run(run_id)
        for kind in self.repository.required_output_kinds(run):
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
            self.repository.enqueue_terminal_picture_cleanup(
                run_id=run_id,
                due_at=datetime.now(UTC).isoformat(),
            )
            self.file_repository.refresh_workspace_catalog_for_version(
                version_id=str(run["source_version_id"]),
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
                    str(item["kind"]): int(item["size_bytes"]) for item in representations
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
            self.file_repository.refresh_workspace_catalog_for_version(
                version_id=str(run["source_version_id"]),
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
            self.file_repository.refresh_workspace_catalog_for_version(
                version_id=str(run["source_version_id"]),
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

    def cleanup_picture_artifacts(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, int]:
        reference_time = now or datetime.now(UTC)
        claimed = self.repository.claim_picture_cleanup(limit=limit)
        deleted = retried = dead = 0
        for cleanup in claimed:
            try:
                self.storage.delete(internal_object_key=str(cleanup["internal_object_key"]))
                self.repository.complete_picture_cleanup(cleanup_id=str(cleanup["id"]))
                deleted += 1
            except Exception as exc:
                attempts = int(cleanup["attempt"])
                result = self.repository.retry_picture_cleanup(
                    cleanup_id=str(cleanup["id"]),
                    error_code=f"cleanup_{type(exc).__name__.lower()}"[:128],
                    next_attempt_at=(
                        reference_time + timedelta(seconds=min(3600, (2**attempts) * 15))
                    ).isoformat(),
                )
                if str(result["status"]) == "DEAD":
                    dead += 1
                else:
                    retried += 1
        return {
            "claimed": len(claimed),
            "deleted": deleted,
            "retried": retried,
            "dead": dead,
        }

    def reconcile_attachment_readability(self, *, limit: int = 100) -> dict[str, Any]:
        return self.repository.reconcile_attachment_readability(limit=limit)

    def _workspace_for_run(self, run: dict[str, Any]) -> str:
        rows = self.file_repository.database.execute(
            """
            select distinct workspace.id
              from task_workspace workspace
              join task_workspace_file member on member.workspace_id = workspace.id
             where member.file_id = ? and member.status = 'ACTIVE'
               and workspace.tenant_id = ?
             order by workspace.id
            """,
            (str(run["source_file_id"]), str(run["tenant_id"])),
        )
        if len(rows) != 1:
            self._deny(
                "document_workspace_binding_invalid",
                "文档处理的工作区绑定无效",
            )
        return str(rows[0]["id"])

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
            "business_application_publication_id": context["business_application_publication_id"],
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
    def _maximum_output_bytes(kind: RepresentationKind, *, run: dict[str, Any]) -> int:
        profile = require_document_processing_profile(
            run["profile_code"], profile_hash=run["profile_hash"]
        )
        if kind is RepresentationKind.MARKDOWN:
            return profile.max_markdown_bytes
        if kind is RepresentationKind.DOCLING_JSON:
            return profile.max_docling_json_bytes
        if profile.layout_ocr_options is None:
            GovernedDocumentProcessingService._deny(
                "document_representation_kind_invalid", "当前Profile不需要此派生表示"
            )
        return int(profile.layout_ocr_options["limits"]["max_ocr_layout_json_bytes"])

    @classmethod
    def _validate_output_metadata(
        cls,
        kind: RepresentationKind,
        *,
        run: dict[str, Any],
        size_bytes: int,
        content_sha256: str,
    ) -> None:
        if size_bytes < 1 or size_bytes > cls._maximum_output_bytes(kind, run=run):
            cls._deny("document_representation_size_exceeded", "派生表示大小无效")
        if len(content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in content_sha256
        ):
            cls._deny("document_representation_digest_invalid", "派生表示摘要无效")

    def _validate_output_content(
        self,
        kind: RepresentationKind,
        stream: BinaryIO,
        *,
        run: dict[str, Any],
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
                self._deny("document_representation_empty", "Markdown 表示不能为空")
            return
        if kind is RepresentationKind.OCR_LAYOUT_JSON:
            profile = require_document_processing_profile(
                run["profile_code"], profile_hash=run["profile_hash"]
            )
            try:
                layout = validate_layout_representation(text.encode("utf-8"), profile=profile)
            except DocumentProcessorFailure as exc:
                raise NonRetryableExecutionError(
                    "OCR layout representation is invalid",
                    safe_message="布局OCR表示无效",
                    error_code=exc.error_code,
                ) from exc
            if layout["source"] != {
                "file_id": str(run["source_file_id"]),
                "version_id": str(run["source_version_id"]),
            } or layout["processing"]["run_id"] != str(run["id"]):
                self._deny("document_layout_identity_mismatch", "布局OCR表示身份不匹配")
            expected_occurrences = self.assembly_context(run_id=str(run["id"]))["occurrences"]
            if len(layout["pictures"]) != len(expected_occurrences):
                self._deny("document_layout_occurrence_mismatch", "布局OCR图片出现位置不完整")
            for actual, expected in zip(layout["pictures"], expected_occurrences, strict=True):
                if (
                    actual["occurrence_index"] != expected["occurrence_index"]
                    or actual["picture_ref"] != expected["picture_ref"]
                    or actual["picture_sha256"] != expected["picture_sha256"]
                    or actual["parent_anchor"] != expected["parent_anchor"]
                    or actual["status"] != expected["status"]
                    or actual["error_code"] != expected["error_code"]
                ):
                    self._deny(
                        "document_layout_occurrence_mismatch",
                        "布局OCR图片出现位置不匹配",
                    )
                if actual["status"] in {"AVAILABLE", "NO_TEXT"}:
                    result_stream = self.open_picture_result(
                        picture_item_id=str(expected["picture_item_id"])
                    )
                    try:
                        result = validate_picture_result(result_stream.read(), profile=profile)
                    finally:
                        result_stream.close()
                    expected_layout = {
                        "coordinate_space": result["coordinate_space"],
                        "image": result["image"],
                        "blocks": result["blocks"],
                        "relations": result["relations"],
                    }
                    if actual["layout"] != expected_layout:
                        self._deny(
                            "document_layout_picture_result_mismatch",
                            "布局OCR逐图结果不匹配",
                        )
                elif actual["layout"] is not None:
                    self._deny(
                        "document_layout_picture_result_mismatch",
                        "布局OCR逐图结果不匹配",
                    )
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
            self._deny("document_representation_json_invalid", "Docling JSON 必须是对象")

    @classmethod
    def _validate_digest(cls, value: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            cls._deny("document_content_digest_invalid", "内容摘要无效")

    @classmethod
    def _verify_transfer_token(
        cls,
        transfer: dict[str, Any],
        *,
        upload_token: str,
        now: datetime | None,
    ) -> None:
        if not hmac.compare_digest(
            str(transfer["token_hash"]),
            hashlib.sha256(upload_token.encode()).hexdigest(),
        ):
            raise PermissionDenied("Transfer token mismatch", safe_message="上传授权无效")
        if datetime.fromisoformat(str(transfer["expires_at"])) < (now or datetime.now(UTC)):
            cls._deny("document_transfer_expired", "上传授权已过期")

    @classmethod
    def _bounded_stream(
        cls,
        stream: BinaryIO,
        *,
        maximum: int,
        size_error_code: str,
    ) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                cls._deny(size_error_code, "上传内容超过大小上限")
            chunks.append(chunk)
        return b"".join(chunks)

    @classmethod
    def _verify_expected_body(cls, transfer: dict[str, Any], body: bytes) -> None:
        if len(body) != int(transfer["expected_size_bytes"]) or hashlib.sha256(
            body
        ).hexdigest() != str(transfer["expected_sha256"]):
            cls._deny("document_transfer_digest_mismatch", "上传内容大小或摘要不一致")

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
