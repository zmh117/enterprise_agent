from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.modules.identity.application.service_principal import AccessTokenProvider
from app.modules.message_bus.application.message_publisher import FileProcessingTaskMessage
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


MAX_CONTROL_RESPONSE_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ClaimedDocumentRun:
    run_id: str
    tenant_id: str
    source_file_id: str
    source_version_id: str
    profile_code: str
    profile_hash: str
    required_output_kinds: tuple[str, ...]
    run_deadline_at: str
    stage_code: str
    assembly_status: str
    status: str
    attempt: int
    external_task_id: str
    display_name: str
    media_type: str
    format_code: str
    size_bytes: int
    content_sha256: str

    @property
    def terminal(self) -> bool:
        return self.status in {"SUCCEEDED", "PARTIAL", "NO_TEXT", "FAILED"}


@dataclass(frozen=True, slots=True)
class ClaimedPictureItem:
    picture_item_id: str
    run_id: str
    profile_hash: str
    run_deadline_at: str
    status: str
    attempt: int
    claimed: bool
    external_task_id: str
    media_type: str
    size_bytes: int
    content_sha256: str
    original_width_pixels: int
    original_height_pixels: int
    width_pixels: int
    height_pixels: int
    normalization_transform: dict[str, object]

    @property
    def terminal(self) -> bool:
        return self.status in {"AVAILABLE", "NO_TEXT", "SKIPPED_LIMIT", "FAILED"}


class DocumentProcessingFileServiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        token_provider: AccessTokenProvider,
        timeout_seconds: int,
        client: httpx.Client | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("File Service internal endpoint is invalid")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("File Service document processing timeout is invalid")
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.client = client or httpx.Client(timeout=float(timeout_seconds), follow_redirects=False)

    def claim(self, message: FileProcessingTaskMessage) -> ClaimedDocumentRun:
        value = self._json(
            "POST",
            self._run_path(message.run_id, "claim"),
            json=message.safe_payload(),
        )
        required = {
            "run_id",
            "tenant_id",
            "source_file_id",
            "source_version_id",
            "profile_code",
            "profile_hash",
            "required_output_kinds",
            "run_deadline_at",
            "stage_code",
            "assembly_status",
            "status",
            "attempt",
            "claimed",
            "external_task_id",
            "display_name",
            "media_type",
            "format_code",
            "size_bytes",
            "content_sha256",
        }
        if set(value) != required:
            self._invalid_response()
        try:
            claimed = ClaimedDocumentRun(
                run_id=str(value["run_id"]),
                tenant_id=str(value["tenant_id"]),
                source_file_id=str(value["source_file_id"]),
                source_version_id=str(value["source_version_id"]),
                profile_code=str(value["profile_code"]),
                profile_hash=str(value["profile_hash"]),
                required_output_kinds=tuple(str(item) for item in value["required_output_kinds"]),
                run_deadline_at=str(value["run_deadline_at"]),
                stage_code=str(value["stage_code"]),
                assembly_status=str(value["assembly_status"]),
                status=str(value["status"]),
                attempt=int(value["attempt"]),
                external_task_id=str(value["external_task_id"]),
                display_name=str(value["display_name"]),
                media_type=str(value["media_type"]),
                format_code=str(value["format_code"]),
                size_bytes=int(value["size_bytes"]),
                content_sha256=str(value["content_sha256"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._invalid_response(exc)
        if (
            claimed.run_id != message.run_id
            or claimed.source_version_id != message.source_version_id
            or claimed.profile_hash != message.profile_hash
            or claimed.required_output_kinds
            not in {
                ("MARKDOWN", "DOCLING_JSON"),
                ("MARKDOWN", "DOCLING_JSON", "OCR_LAYOUT_JSON"),
            }
            or claimed.size_bytes < 1
            or claimed.size_bytes > MAX_SOURCE_BYTES
            or len(claimed.content_sha256) != 64
        ):
            self._invalid_response()
        return claimed

    def download_source(self, run: ClaimedDocumentRun) -> bytes:
        grant = self._json(
            "POST",
            self._run_path(run.run_id, "source-grant"),
            json={"tenant_id": run.tenant_id},
        )
        if set(grant) != {"run_id", "source_version_id", "grant", "expires_at"}:
            self._invalid_response()
        if (
            str(grant["run_id"]) != run.run_id
            or str(grant["source_version_id"]) != run.source_version_id
        ):
            self._invalid_response()
        response = self._request(
            "GET",
            self._run_path(run.run_id, "source"),
            headers={"X-Document-Source-Grant": str(grant["grant"])},
        )
        data = response.content
        if (
            len(data) != run.size_bytes
            or len(data) > MAX_SOURCE_BYTES
            or hashlib.sha256(data).hexdigest() != run.content_sha256
        ):
            raise RetryableExecutionError(
                "File Service document source receipt mismatch",
                safe_message="文档原件读取回执不匹配",
                error_code="document_source_receipt_mismatch",
            )
        return data

    def mark_submitted(self, run_id: str, external_task_id: str) -> None:
        self._json(
            "POST",
            self._run_path(run_id, "submitted"),
            json={"external_task_id": external_task_id},
        )

    def upload_representation(
        self, *, run_id: str, kind: str, content: bytes, media_type: str
    ) -> None:
        digest = hashlib.sha256(content).hexdigest()
        prepared = self._json(
            "POST",
            self._run_path(run_id, f"representations/{quote(kind, safe='')}/prepare"),
            json={"expected_size_bytes": len(content), "expected_sha256": digest},
        )
        required = {"transfer_id", "kind", "status", "upload_required"}
        if not required.issubset(prepared):
            self._invalid_response()
        if not bool(prepared["upload_required"]):
            return
        if set(prepared) != required | {"upload_token", "expires_at"}:
            self._invalid_response()
        self._json(
            "PUT",
            (
                "/internal/v1/document-processing/transfers/"
                f"{quote(str(prepared['transfer_id']), safe='')}/content"
            ),
            content=content,
            headers={
                "Content-Type": media_type,
                "X-Representation-Upload-Token": str(prepared["upload_token"]),
            },
        )

    def upload_parent_artifact(self, *, run_id: str, content: bytes) -> None:
        digest = hashlib.sha256(content).hexdigest()
        prepared = self._json(
            "POST",
            self._run_path(run_id, "parent-artifact/prepare"),
            json={"expected_size_bytes": len(content), "expected_sha256": digest},
        )
        if not bool(prepared.get("upload_required")):
            return
        required = {"transfer_id", "status", "upload_required", "upload_token", "expires_at"}
        if set(prepared) != required:
            self._invalid_response()
        self._json(
            "PUT",
            (
                "/internal/v1/document-processing/parent-artifact-transfers/"
                f"{quote(str(prepared['transfer_id']), safe='')}/content"
            ),
            content=content,
            headers={
                "Content-Type": "text/markdown",
                "X-Parent-Artifact-Upload-Token": str(prepared["upload_token"]),
            },
        )

    def download_parent_artifact(self, *, run_id: str, maximum_bytes: int) -> bytes:
        return self._download_bounded(
            self._run_path(run_id, "parent-artifact"), maximum_bytes=maximum_bytes
        )

    def upload_picture_asset(
        self,
        *,
        run_id: str,
        content: bytes,
        media_type: str,
        original_width_pixels: int,
        original_height_pixels: int,
        width_pixels: int,
        height_pixels: int,
        normalization_transform: dict[str, object],
        content_sha256: str,
    ) -> str:
        if hashlib.sha256(content).hexdigest() != content_sha256:
            raise NonRetryableExecutionError(
                "Picture asset digest mismatch",
                safe_message="图片asset摘要不匹配",
                error_code="document_picture_digest_mismatch",
            )
        prepared = self._json(
            "POST",
            self._run_path(run_id, "picture-assets/prepare"),
            json={
                "normalized_sha256": content_sha256,
                "media_type": media_type,
                "original_width_pixels": original_width_pixels,
                "original_height_pixels": original_height_pixels,
                "width_pixels": width_pixels,
                "height_pixels": height_pixels,
                "normalization_transform": normalization_transform,
                "size_bytes": len(content),
            },
        )
        required = {"picture_asset_id", "transfer_id", "status", "upload_required"}
        if not required.issubset(prepared):
            self._invalid_response()
        if bool(prepared["upload_required"]):
            if set(prepared) != required | {"upload_token", "expires_at"}:
                self._invalid_response()
            self._json(
                "PUT",
                (
                    "/internal/v1/document-processing/picture-asset-transfers/"
                    f"{quote(str(prepared['transfer_id']), safe='')}/content"
                ),
                content=content,
                headers={
                    "Content-Type": media_type,
                    "X-Picture-Asset-Upload-Token": str(prepared["upload_token"]),
                },
            )
        return str(prepared["picture_asset_id"])

    def register_picture_occurrence(
        self,
        *,
        run_id: str,
        picture_asset_id: str,
        occurrence_index: int,
        source_format: str,
        picture_ref: str,
        parent_ref: str,
        parent_label: str,
        parent_ordinal: int,
        slide_no: int | None,
        parent_bbox: dict[str, object] | None,
        selection_status: str,
    ) -> str:
        value = self._json(
            "POST",
            self._run_path(run_id, "picture-occurrences"),
            json={
                "picture_asset_id": picture_asset_id,
                "occurrence_index": occurrence_index,
                "source_format": source_format,
                "picture_ref": picture_ref,
                "parent_ref": parent_ref,
                "parent_label": parent_label,
                "parent_ordinal": parent_ordinal,
                "slide_no": slide_no,
                "parent_bbox": parent_bbox,
                "selection_status": selection_status,
            },
        )
        if set(value) != {"occurrence_id", "occurrence_index"}:
            self._invalid_response()
        return str(value["occurrence_id"])

    def register_picture_item(
        self,
        *,
        run_id: str,
        picture_asset_id: str,
        occurrence_count: int,
        ocr_engine_code: str,
        model_revision: str,
        model_digest: str,
        correlation_id: str,
    ) -> str:
        value = self._json(
            "POST",
            self._run_path(run_id, "picture-items"),
            json={
                "picture_asset_id": picture_asset_id,
                "occurrence_count": occurrence_count,
                "ocr_engine_code": ocr_engine_code,
                "model_revision": model_revision,
                "model_digest": model_digest,
                "correlation_id": correlation_id,
            },
        )
        if set(value) != {"picture_item_id", "status"}:
            self._invalid_response()
        return str(value["picture_item_id"])

    def claim_picture_item(
        self,
        *,
        picture_item_id: str,
        claim_token: str,
        claim_expires_at: str,
        expected_run_id: str,
        expected_profile_hash: str,
    ) -> ClaimedPictureItem:
        value = self._json(
            "POST",
            self._picture_item_path(picture_item_id, "claim"),
            json={"claim_token": claim_token, "claim_expires_at": claim_expires_at},
        )
        required = {
            "picture_item_id",
            "run_id",
            "profile_hash",
            "run_deadline_at",
            "status",
            "attempt",
            "claimed",
            "external_task_id",
            "media_type",
            "size_bytes",
            "content_sha256",
            "original_width_pixels",
            "original_height_pixels",
            "width_pixels",
            "height_pixels",
            "normalization_transform",
        }
        if set(value) != required:
            self._invalid_response()
        try:
            item = ClaimedPictureItem(**value)
        except (TypeError, ValueError) as exc:
            self._invalid_response(exc)
        if (
            item.picture_item_id != picture_item_id
            or item.run_id != expected_run_id
            or item.profile_hash != expected_profile_hash
            or item.size_bytes < 1
            or len(item.content_sha256) != 64
        ):
            self._invalid_response()
        return item

    def download_picture_asset(self, item: ClaimedPictureItem) -> bytes:
        body = self._download_bounded(
            self._picture_item_path(item.picture_item_id, "asset"),
            maximum_bytes=item.size_bytes,
        )
        if (
            len(body) != item.size_bytes
            or hashlib.sha256(body).hexdigest() != item.content_sha256
        ):
            raise RetryableExecutionError(
                "Picture asset receipt mismatch",
                safe_message="图片asset读取回执不匹配",
                error_code="document_picture_receipt_mismatch",
            )
        return body

    def mark_picture_submitted(self, *, picture_item_id: str, external_task_id: str) -> None:
        self._json(
            "POST",
            self._picture_item_path(picture_item_id, "submitted"),
            json={"external_task_id": external_task_id},
        )

    def upload_picture_result(self, *, picture_item_id: str, content: bytes) -> None:
        digest = hashlib.sha256(content).hexdigest()
        prepared = self._json(
            "POST",
            self._picture_item_path(picture_item_id, "result/prepare"),
            json={"expected_size_bytes": len(content), "expected_sha256": digest},
        )
        if not bool(prepared.get("upload_required")):
            return
        required = {"transfer_id", "status", "upload_required", "upload_token", "expires_at"}
        if set(prepared) != required:
            self._invalid_response()
        self._json(
            "PUT",
            (
                "/internal/v1/document-processing/picture-result-transfers/"
                f"{quote(str(prepared['transfer_id']), safe='')}/content"
            ),
            content=content,
            headers={
                "Content-Type": "application/json",
                "X-Picture-Result-Upload-Token": str(prepared["upload_token"]),
            },
        )

    def download_picture_result(self, *, picture_item_id: str, maximum_bytes: int) -> bytes:
        return self._download_bounded(
            self._picture_item_path(picture_item_id, "result"), maximum_bytes=maximum_bytes
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
    ) -> None:
        self._json(
            "POST",
            self._picture_item_path(picture_item_id, "complete"),
            json={
                "status": status,
                "result_size_bytes": result_size_bytes,
                "result_sha256": result_sha256,
                "error_code": error_code,
                "correlation_id": correlation_id,
            },
        )

    def retry_picture_item(
        self,
        *,
        picture_item_id: str,
        error_code: str,
        delay_seconds: int,
    ) -> None:
        self._json(
            "POST",
            self._picture_item_path(picture_item_id, "retry"),
            json={"error_code": error_code, "delay_seconds": delay_seconds},
        )

    def complete_parent_parse(self, *, run_id: str, correlation_id: str) -> None:
        self._json(
            "POST",
            self._run_path(run_id, "parent-complete"),
            json={"correlation_id": correlation_id},
        )

    def claim_assembly(
        self,
        *,
        run_id: str,
        profile_hash: str,
        claim_token: str,
    ) -> dict[str, Any]:
        value = self._json(
            "POST",
            self._run_path(run_id, "assembly/claim"),
            json={"claim_token": claim_token},
        )
        if set(value) != {
            "run_id",
            "profile_hash",
            "assembly_status",
            "assembly_attempt",
            "claimed",
        } or str(value["run_id"]) != run_id or str(value["profile_hash"]) != profile_hash:
            self._invalid_response()
        return value

    def assembly_context(self, *, run_id: str, profile_hash: str) -> dict[str, Any]:
        value = self._json("GET", self._run_path(run_id, "assembly/context"))
        required = {
            "run_id",
            "source_file_id",
            "source_version_id",
            "profile_code",
            "profile_hash",
            "run_deadline_at",
            "assembly_status",
            "occurrences",
        }
        if (
            set(value) != required
            or str(value["run_id"]) != run_id
            or str(value["profile_hash"]) != profile_hash
            or not isinstance(value["occurrences"], list)
        ):
            self._invalid_response()
        return value

    def finish_assembly(self, *, run_id: str, succeeded: bool) -> None:
        self._json(
            "POST",
            self._run_path(run_id, "assembly/finish"),
            json={"succeeded": succeeded},
        )

    def retry_assembly(self, *, run_id: str) -> None:
        self._json("POST", self._run_path(run_id, "assembly/retry"), json={})

    def finalize(
        self,
        *,
        run_id: str,
        partial: bool,
        page_count: int | None,
        processing_time_ms: int | None,
    ) -> None:
        self._json(
            "POST",
            self._run_path(run_id, "finalize"),
            json={
                "partial": partial,
                "page_count": page_count,
                "processing_time_ms": processing_time_ms,
            },
        )

    def no_text(
        self, *, run_id: str, page_count: int | None, processing_time_ms: int | None
    ) -> None:
        self._json(
            "POST",
            self._run_path(run_id, "no-text"),
            json={"page_count": page_count, "processing_time_ms": processing_time_ms},
        )

    def retry(self, *, run_id: str, error_code: str, delay_seconds: int) -> None:
        self._json(
            "POST",
            self._run_path(run_id, "retry"),
            json={"error_code": error_code, "delay_seconds": delay_seconds},
        )

    def fail(self, *, run_id: str, error_code: str, processing_time_ms: int | None = None) -> None:
        self._json(
            "POST",
            self._run_path(run_id, "fail"),
            json={"error_code": error_code, "processing_time_ms": processing_time_ms},
        )

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._request(method, path, **kwargs)
        if len(response.content) > MAX_CONTROL_RESPONSE_BYTES:
            self._invalid_response()
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            self._invalid_response()
        try:
            value = response.json()
        except ValueError as exc:
            self._invalid_response(exc)
        if not isinstance(value, dict):
            self._invalid_response()
        return value

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._token()}"
        try:
            response = self.client.request(
                method, f"{self.base_url}{path}", headers=headers, **kwargs
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableExecutionError(
                "File Service document processing request failed",
                safe_message="文档处理文件服务暂时不可用",
                error_code="file_service_unavailable",
            ) from exc
        if response.status_code >= 500:
            raise RetryableExecutionError(
                "File Service document processing request failed",
                safe_message="文档处理文件服务暂时不可用",
                error_code="file_service_unavailable",
            )
        if response.status_code < 200 or response.status_code >= 300:
            error_code = "document_processing_request_denied"
            try:
                candidate = response.json().get("error_code")
                if isinstance(candidate, str) and candidate.replace("_", "").isalnum():
                    error_code = candidate[:128]
            except ValueError:
                pass
            raise NonRetryableExecutionError(
                "File Service rejected document processing request",
                safe_message="文档处理文件请求被拒绝",
                error_code=error_code,
            )
        return response

    def _token(self) -> str:
        token = self.token_provider.access_token()
        if not token or len(token.encode()) > 8192:
            raise NonRetryableExecutionError(
                "File Processing Worker Principal token is unavailable",
                safe_message="文档处理工作身份凭证不可用",
                error_code="file_processing_worker_principal_unavailable",
            )
        return token

    @staticmethod
    def _run_path(run_id: str, suffix: str) -> str:
        return f"/internal/v1/document-processing/runs/{quote(run_id, safe='')}/{suffix}"

    @staticmethod
    def _picture_item_path(picture_item_id: str, suffix: str) -> str:
        return (
            "/internal/v1/document-processing/picture-items/"
            f"{quote(picture_item_id, safe='')}/{suffix}"
        )

    def _download_bounded(self, path: str, *, maximum_bytes: int) -> bytes:
        response = self._request("GET", path)
        if len(response.content) > maximum_bytes:
            raise RetryableExecutionError(
                "File Service content exceeds receipt bound",
                safe_message="文件服务内容超过读取上限",
                error_code="file_service_response_invalid",
            )
        return response.content

    @staticmethod
    def _invalid_response(cause: Exception | None = None) -> None:
        error = RetryableExecutionError(
            "File Service document processing response is invalid",
            safe_message="文档处理文件服务响应无效",
            error_code="file_service_response_invalid",
        )
        if cause is None:
            raise error
        raise error from cause
