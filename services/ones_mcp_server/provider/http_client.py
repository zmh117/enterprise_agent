from __future__ import annotations

import json
import re
import socket
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import AppError, RetryableExecutionError
from services.ones_mcp_server.errors import (
    OnesMcpError,
    OnesProviderUnauthorized,
    invalid_provider_response,
)
from services.ones_mcp_server.provider.target import ProviderTarget


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_QUERY_PART = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class OnesProviderHttpClient:
    """Bounded JSON transport for the single configured ONES Provider origin.

    Callers supply only code-owned paths and headers. MCP input never reaches the
    target URL, authentication headers, timeout, redirect, or response-size policy.
    """

    def __init__(
        self,
        target: ProviderTarget,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
        open_response: Any | None = None,
    ) -> None:
        if not 1 <= timeout_seconds <= 30 or not 1024 <= max_response_bytes <= 1024 * 1024:
            raise ValueError("ONES Provider bounds are invalid")
        self.target = target
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._open_response = open_response
        self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request_json("POST", path, payload, headers=headers, query=query)

    def get_json(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        headers: dict[str, str],
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request_json("GET", path, payload, headers=headers, query=query)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        headers: dict[str, str],
        query: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        if method not in {"GET", "POST"}:
            raise ValueError("ONES Provider method is not supported")
        if not path.startswith("/") or "://" in path or "?" in path or "#" in path:
            raise ValueError("ONES Provider path must be a fixed absolute path")
        if payload is None and method != "GET":
            raise ValueError("ONES Provider JSON payload is required")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("ONES Provider JSON payload must be an object")
        query_string = self._fixed_query_string(query)
        assert_external_io_allowed("ones_mcp.provider")
        request_headers = {"Accept": "application/json", **headers}
        request_data = None
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            request_data = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        request = Request(
            self.target.base_url + path + query_string,
            data=request_data,
            headers=request_headers,
            method=method,
        )
        try:
            if self._open_response is not None:
                response = self._open_response(request, float(self.timeout_seconds))
            else:
                response = self._opener.open(request, timeout=float(self.timeout_seconds))
            with response:
                if int(getattr(response, "status", 200)) != 200:
                    raise self.status_error(int(response.status))
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise self.status_error(int(exc.code)) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise RetryableExecutionError(
                "ONES Provider request failed",
                safe_message="ONES 查询暂时不可用",
                error_code="ones_provider_unavailable",
            ) from None
        if len(raw) > self.max_response_bytes:
            raise invalid_provider_response("ones_provider_response_too_large")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise invalid_provider_response("ones_provider_response_invalid") from None
        if not isinstance(parsed, dict):
            raise invalid_provider_response("ones_provider_response_invalid")
        McpAuditCoordinator.reject_auth_material(parsed)
        return parsed

    @staticmethod
    def _fixed_query_string(query: Mapping[str, str] | None) -> str:
        if query is None:
            return ""
        if not isinstance(query, Mapping) or not 1 <= len(query) <= 8:
            raise ValueError("ONES Provider query parameters are invalid")
        normalized: list[tuple[str, str]] = []
        for key, value in query.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, str)
                or _QUERY_PART.fullmatch(key) is None
                or _QUERY_PART.fullmatch(value) is None
            ):
                raise ValueError("ONES Provider query parameters are invalid")
            normalized.append((key, value))
        return "?" + urlencode(sorted(normalized))

    @staticmethod
    def status_error(status: int) -> AppError:
        if status == 401:
            return OnesProviderUnauthorized(
                "ONES Provider rejected its current Token",
                safe_message="ONES 登录状态已失效",
                error_code="ones_provider_unauthorized",
            )
        if status == 403:
            return OnesMcpError(
                "ONES Provider denied Team access",
                safe_message="当前 ONES 身份无权访问该 Team",
                error_code="ones_provider_forbidden",
            )
        if status == 429:
            return RetryableExecutionError(
                "ONES Provider rate limited the request",
                safe_message="ONES 查询过于频繁，请稍后重试",
                error_code="ones_provider_rate_limited",
            )
        if 300 <= status < 400:
            return OnesMcpError(
                "ONES Provider redirect was rejected",
                safe_message="ONES 返回了无效重定向",
                error_code="ones_provider_redirect_rejected",
            )
        if status >= 500:
            return RetryableExecutionError(
                "ONES Provider is unavailable",
                safe_message="ONES 查询暂时不可用",
                error_code="ones_provider_unavailable",
            )
        return OnesMcpError(
            "ONES Provider returned an unsupported status",
            safe_message="ONES 返回了无效响应",
            error_code="ones_provider_response_invalid",
        )
