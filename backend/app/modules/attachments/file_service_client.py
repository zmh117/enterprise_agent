from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from app.modules.attachments.domain import AttachmentImportReceipt
from app.modules.identity.application.service_principal import AccessTokenProvider
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


class FileServiceAttachmentImporter:
    """Fixed-host internal client; the worker never receives an object location."""

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        token_provider: AccessTokenProvider,
        timeout_seconds: int = 30,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.hostname not in allowed_hosts
        ):
            raise ValueError("File Service internal endpoint is invalid")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("File Worker identity settings are invalid")
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.timeout_seconds = timeout_seconds

    def import_content(
        self,
        *,
        attachment_id: str,
        data: bytes,
        content_type: str,
    ) -> AttachmentImportReceipt:
        token = self._token()
        request = urllib.request.Request(
            (
                f"{self.base_url}/internal/v1/attachments/"
                f"{quote(attachment_id, safe='')}/content"
            ),
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read(64 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise NonRetryableExecutionError(
                    "File Service rejected attachment import",
                    safe_message="附件导入被拒绝",
                    error_code="file_attachment_import_denied",
                ) from exc
            raise RetryableExecutionError(
                "File Service attachment import failed",
                safe_message="附件导入服务暂时不可用",
                error_code="file_service_unavailable",
            ) from exc
        except (OSError, TimeoutError) as exc:
            raise RetryableExecutionError(
                "File Service attachment import failed",
                safe_message="附件导入服务暂时不可用",
                error_code="file_service_unavailable",
            ) from exc
        if len(payload) > 64 * 1024:
            raise RetryableExecutionError(
                "File Service response exceeded its bound",
                safe_message="附件导入服务响应无效",
                error_code="file_service_response_invalid",
            )
        try:
            value = json.loads(payload)
            receipt = AttachmentImportReceipt(
                attachment_id=str(value["attachment_id"]),
                size_bytes=int(value["size_bytes"]),
                sha256=str(value["sha256"]),
                file_id=str(value.get("file_id") or ""),
                version_id=str(value.get("version_id") or ""),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RetryableExecutionError(
                "File Service response is invalid",
                safe_message="附件导入服务响应无效",
                error_code="file_service_response_invalid",
            ) from exc
        if (
            receipt.attachment_id != attachment_id
            or receipt.size_bytes != len(data)
            or receipt.sha256 != hashlib.sha256(data).hexdigest()
        ):
            raise RetryableExecutionError(
                "File Service receipt does not match attachment",
                safe_message="附件导入回执不匹配",
                error_code="file_service_receipt_mismatch",
            )
        return receipt

    def run_maintenance(self) -> dict[str, int | str]:
        request = urllib.request.Request(
            f"{self.base_url}/internal/v1/file-maintenance/run",
            data=b"",
            method="POST",
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read(64 * 1024 + 1)
        except (urllib.error.HTTPError, OSError, TimeoutError) as exc:
            raise RetryableExecutionError(
                "File maintenance request failed",
                safe_message="文件清理服务暂时不可用",
                error_code="file_service_unavailable",
            ) from exc
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RetryableExecutionError(
                "File maintenance response is invalid",
                safe_message="文件清理服务响应无效",
                error_code="file_service_response_invalid",
            ) from exc
        if not isinstance(value, dict) or len(payload) > 64 * 1024:
            raise RetryableExecutionError(
                "File maintenance response is invalid",
                safe_message="文件清理服务响应无效",
                error_code="file_service_response_invalid",
            )
        return {
            str(key): item
            for key, item in value.items()
            if isinstance(item, (int, str)) and not isinstance(item, bool)
        }

    def _token(self) -> str:
        token = self.token_provider.access_token()
        if not token or len(token.encode()) > 8192:
            raise NonRetryableExecutionError(
                "File Worker Principal token is unavailable",
                safe_message="文件工作身份凭证不可用",
                error_code="file_worker_principal_unavailable",
            )
        return token
