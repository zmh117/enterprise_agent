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
    source_version_id: str
    profile_hash: str
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
            "source_version_id",
            "profile_hash",
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
                source_version_id=str(value["source_version_id"]),
                profile_hash=str(value["profile_hash"]),
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
    def _invalid_response(cause: Exception | None = None) -> None:
        error = RetryableExecutionError(
            "File Service document processing response is invalid",
            safe_message="文档处理文件服务响应无效",
            error_code="file_service_response_invalid",
        )
        if cause is None:
            raise error
        raise error from cause
