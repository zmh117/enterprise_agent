from __future__ import annotations

import http.client
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
)


JSON_CONTENT_TYPES = frozenset({"application/json"})


@dataclass(frozen=True, slots=True)
class HttpJsonResponse:
    payload: Any
    status: int
    duration_ms: int
    response_size: int


ConnectionFactory = Callable[
    [str, str, int, float],
    http.client.HTTPConnection,
]


class RestrictedHttpJsonClient:
    """HTTP JSON client restricted to a published Connection Origin."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._connection_factory = connection_factory or _connection

    def request(
        self,
        *,
        connection: dict[str, Any],
        method: str,
        relative_path: str,
        query: dict[str, str | int | float | bool] | None = None,
        body: dict[str, Any] | None = None,
        authentication_header: tuple[str, str] | None = None,
    ) -> HttpJsonResponse:
        assert_external_io_allowed("governed_api.http_json")
        normalized_method = method.strip().upper()
        if normalized_method not in {"GET", "POST"}:
            raise _configuration_error("unsupported HTTP method")
        path = validate_relative_path(relative_path)
        if query:
            path = f"{path}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        encoded_body: bytes | None = None
        if body is not None:
            encoded_body = json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            headers["Content-Type"] = "application/json"
        if authentication_header is not None:
            header_name, header_value = authentication_header
            validate_authentication_header_name(header_name)
            headers[header_name] = header_value
        scheme = str(connection["origin_scheme"]).lower()
        host = str(connection["origin_host"])
        port = int(connection["origin_port"])
        connect_timeout = int(connection["connect_timeout_ms"]) / 1000
        read_timeout = int(connection["read_timeout_ms"]) / 1000
        maximum = int(connection["max_response_bytes"])
        started = time.monotonic()
        client = self._connection_factory(
            scheme,
            host,
            port,
            connect_timeout,
        )
        try:
            client.request(
                normalized_method,
                path,
                body=encoded_body,
                headers=headers,
            )
            response = client.getresponse()
            if getattr(client, "sock", None) is not None:
                client.sock.settimeout(read_timeout)
            status = int(response.status)
            if 300 <= status < 400:
                raise NonRetryableExecutionError(
                    "Cross-Origin or redirect response was rejected",
                    safe_message="外部 API 返回了不允许的重定向",
                    error_code="external_api_redirect_rejected",
                )
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise NonRetryableExecutionError(
                    "External API response exceeded configured limit",
                    safe_message="外部 API 响应超过大小限制",
                    error_code="external_api_response_too_large",
                )
            if status < 200 or status >= 300:
                raise _status_error(status)
            content_type = str(response.getheader("Content-Type") or "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type not in JSON_CONTENT_TYPES and not media_type.endswith("+json"):
                raise NonRetryableExecutionError(
                    "External API response is not JSON",
                    safe_message="外部 API 返回了非 JSON 响应",
                    error_code="external_api_content_type_invalid",
                )
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise NonRetryableExecutionError(
                    "External API response contains invalid JSON",
                    safe_message="外部 API 返回了无效 JSON",
                    error_code="external_api_json_invalid",
                ) from None
            return HttpJsonResponse(
                payload=payload,
                status=status,
                duration_ms=int((time.monotonic() - started) * 1000),
                response_size=len(raw),
            )
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise RetryableExecutionError(
                f"External API transport failed: {type(exc).__name__}",
                safe_message="外部 API 暂时不可用",
                error_code="external_api_unavailable",
            ) from None
        finally:
            client.close()


def validate_relative_path(value: str) -> str:
    path = str(value or "").strip()
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "://" in path
        or "@" in path
        or "\\" in path
        or "?" in path
        or "#" in path
        or "{" in path
        or "}" in path
        or "$" in path
    ):
        raise _configuration_error("Handler path must be a fixed relative path")
    segments = path.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise _configuration_error("Handler path traversal is forbidden")
    return path


def validate_authentication_header_name(value: str) -> str:
    name = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", name):
        raise _configuration_error("Authentication Header name is invalid")
    if name.lower() in {
        "host",
        "cookie",
        "content-length",
        "transfer-encoding",
        "connection",
    }:
        raise _configuration_error("Authentication Header name is forbidden")
    return name


def _connection(
    scheme: str,
    host: str,
    port: int,
    timeout: float,
) -> http.client.HTTPConnection:
    if scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout)
    if scheme == "http":
        return http.client.HTTPConnection(host, port, timeout=timeout)
    raise _configuration_error("Connection scheme is unsupported")


def _status_error(
    status: int,
) -> NonRetryableExecutionError | RetryableExecutionError:
    if status == 401:
        return NonRetryableExecutionError(
            "External API credential was rejected",
            safe_message="ONES 凭据已失效，请重新绑定",
            error_code="external_api_unauthorized",
            diagnostics={"http_status": status},
        )
    if status == 403:
        return NonRetryableExecutionError(
            "External API request is forbidden",
            safe_message="ONES 拒绝了当前操作",
            error_code="external_api_forbidden",
            diagnostics={"http_status": status},
        )
    if status == 429 or status >= 500:
        return RetryableExecutionError(
            f"External API returned retryable HTTP {status}",
            safe_message="外部 API 暂时不可用",
            error_code="external_api_retryable_status",
            diagnostics={"http_status": status},
        )
    return NonRetryableExecutionError(
        f"External API returned HTTP {status}",
        safe_message="外部 API 请求失败",
        error_code="external_api_request_rejected",
        diagnostics={"http_status": status},
    )


def _configuration_error(reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid governed API HTTP configuration: {reason}",
        safe_message="外部 API 配置无效",
        error_code="external_api_configuration_invalid",
    )
