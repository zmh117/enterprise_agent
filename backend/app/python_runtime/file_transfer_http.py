from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.python_runtime.file_transfer import (
    FileTransferBoundaryError,
    FileTransferPort,
    FileUploadReceipt,
)


_MAX_RECEIPT_BYTES = 64 * 1024
_IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")


def _identifier(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or value[0] not in _IDENTIFIER_CHARS
        or any(character not in _IDENTIFIER_CHARS for character in value)
    ):
        raise FileTransferBoundaryError(
            "file_transfer_control_invalid",
            f"{field} must be an opaque identifier",
        )
    return value


def _service_origin(mcp_server_url: str) -> tuple[str, str]:
    parsed = urlsplit(mcp_server_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path != "/mcp"
        or parsed.query
        or parsed.fragment
    ):
        raise FileTransferBoundaryError(
            "file_transfer_endpoint_invalid",
            "File Service endpoint is outside the fixed deployment boundary",
        )
    return parsed.scheme, parsed.netloc


class HttpFileTransferPort(FileTransferPort):
    def __init__(
        self,
        mcp_server_url: str,
        *,
        timeout_seconds: float,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        self._scheme, self._netloc = _service_origin(mcp_server_url)
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def _url(self, path: str) -> str:
        return urlunsplit((self._scheme, self._netloc, path, "", ""))

    def download(
        self,
        *,
        transfer_id: str,
        job_id: str,
        principal_token: str,
    ) -> Iterable[bytes]:
        transfer = quote(_identifier(transfer_id, "transfer_id"), safe="")
        headers = {
            "Authorization": f"Bearer {principal_token}",
            "X-Job-Id": _identifier(job_id, "job_id"),
        }
        try:
            with self._client_factory(
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "GET",
                    self._url(f"/internal/v1/file-transfers/{transfer}/content"),
                    headers=headers,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise FileTransferBoundaryError(
                            "file_service_unavailable",
                            f"File Service transfer failed with status {response.status_code}",
                        )
                    media_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if media_type != "application/octet-stream":
                        raise FileTransferBoundaryError(
                            "file_transfer_content_type_invalid",
                            "File Service returned an unexpected transfer content type",
                        )
                    yield from response.iter_bytes(chunk_size=64 * 1024)
        except httpx.HTTPError as exc:
            raise FileTransferBoundaryError(
                "file_service_unavailable",
                "File Service transfer failed",
            ) from exc

    def upload(
        self,
        *,
        commit_id: str,
        job_id: str,
        principal_token: str,
        content: Iterable[bytes],
    ) -> FileUploadReceipt:
        commit = quote(_identifier(commit_id, "commit_id"), safe="")
        headers = {
            "Authorization": f"Bearer {principal_token}",
            "Content-Type": "application/octet-stream",
            "X-Job-Id": _identifier(job_id, "job_id"),
        }
        try:
            with self._client_factory(
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.put(
                    self._url(f"/internal/v1/file-commits/{commit}/content"),
                    headers=headers,
                    content=content,
                )
        except httpx.HTTPError as exc:
            raise FileTransferBoundaryError(
                "file_service_unavailable",
                "File Service transfer failed",
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            error_code = ""
            try:
                denied = response.json()
                candidate = denied.get("error_code") if isinstance(denied, dict) else None
                if isinstance(candidate, str) and candidate.startswith("file_"):
                    _identifier(candidate, "error_code")
                    error_code = candidate
            except (ValueError, json.JSONDecodeError):
                error_code = ""
            raise FileTransferBoundaryError(
                error_code or "file_service_unavailable",
                f"File Service transfer failed with status {response.status_code}",
            )
        if len(response.content) > _MAX_RECEIPT_BYTES:
            raise FileTransferBoundaryError(
                "file_transfer_receipt_invalid",
                "File Service upload receipt exceeded the safe limit",
            )
        try:
            value: Any = json.loads(response.content.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FileTransferBoundaryError(
                "file_transfer_receipt_invalid",
                "File Service upload receipt was invalid",
            ) from exc
        if not isinstance(value, dict):
            raise FileTransferBoundaryError(
                "file_transfer_receipt_invalid",
                "File Service upload receipt was invalid",
            )
        file_id = value.get("file_id")
        version_id = value.get("version_id")
        size_bytes = value.get("size_bytes")
        sha256 = value.get("sha256")
        status = value.get("status")
        delivery_id = value.get("delivery_id")
        delivery_status = value.get("delivery_status")
        if (
            not isinstance(file_id, str)
            or not isinstance(version_id, str)
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or status not in {"COMMITTED", "CONFLICT"}
            or not isinstance(delivery_id, str)
            or delivery_status
            not in {
                "NOT_REQUESTED",
                "PENDING",
                "RUNNING",
                "RETRY_WAIT",
                "SUCCEEDED",
                "FAILED",
                "DEAD",
                "SKIPPED",
            }
            or bool(delivery_id) == (delivery_status == "NOT_REQUESTED")
        ):
            raise FileTransferBoundaryError(
                "file_transfer_receipt_invalid",
                "File Service upload receipt was invalid",
            )
        _identifier(file_id, "file_id")
        _identifier(version_id, "version_id")
        if delivery_id:
            _identifier(delivery_id, "delivery_id")
        return FileUploadReceipt(
            file_id=file_id,
            version_id=version_id,
            size_bytes=size_bytes,
            sha256=sha256,
            status=status,
            delivery_id=delivery_id,
            delivery_status=delivery_status,
        )
