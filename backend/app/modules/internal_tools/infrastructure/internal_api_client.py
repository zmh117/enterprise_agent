from __future__ import annotations

import json
import re
import socket
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.request import Request, urlopen

from app.modules.audit.application.summaries import mask_sensitive
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
    ToolPolicyError,
)


TRANSIENT_HTTP_STATUSES = {429, 502, 503, 504}
NON_RETRYABLE_HTTP_STATUSES = {400, 401, 403, 404}


@dataclass(frozen=True)
class ToolResult:
    summary: dict[str, Any]
    raw: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False


@dataclass(frozen=True)
class ToolRequestContext:
    job_id: str
    user_id: str
    project_code: str
    correlation_id: str = "-"


class InternalApiClient(Protocol):
    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult: ...

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult: ...

    def get_schema_directory(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str,
        workshop: str | None = None,
        query: str = "",
        limit: int = 50,
    ) -> ToolResult: ...

    def query_loki(
        self,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult: ...

    def query_database(
        self,
        datasource: str,
        sql: str,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult: ...

    def query_redis_get(
        self,
        datasource: str,
        key: str,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult: ...

    def query_redis_scan(
        self,
        datasource: str,
        pattern: str,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult: ...


def _addressing_payload(
    environment: str | None, base: str | None, workshop: str | None
) -> dict[str, str]:
    """Structured addressing fields to send to a topology-aware platform.

    project_code stays an Agent-side coarse permission; addressing is independent.
    """

    payload: dict[str, str] = {}
    if environment:
        payload["environment"] = environment
    if base:
        payload["base"] = base
    if workshop:
        payload["workshop"] = workshop
    return payload


class FakeInternalApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        self.calls.append(
            ("get_er_context", {"query": query, "project_code": context.project_code})
        )
        summary = {
            "tables": ["ws_a_order", "ws_a_material", "ws_a_inventory"],
            "fields": ["status", "material_id", "inventory_qty"],
            "relationships": ["ws_a_order.material_id -> ws_a_material.id"],
            "addressing": {
                "environments": [
                    {
                        "code": "sanjiu",
                        "display_name": "三九",
                        "aliases": [],
                        "bases": [
                            {
                                "code": "guanlan",
                                "display_name": "观澜基地",
                                "aliases": ["观澜"],
                                "engine": "mysql",
                                "partitioned": True,
                                "workshops": [
                                    {"code": "GL001", "display_name": "", "aliases": []},
                                    {"code": "GL002", "display_name": "", "aliases": []},
                                ],
                            }
                        ],
                    }
                ]
            },
        }
        return ToolResult(summary=summary, raw=summary)

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        self.calls.append(
            ("get_business_flow_context", {"query": query, "project_code": context.project_code})
        )
        summary = {
            "nodes": ["order_submit", "inventory_check", "material_pick"],
            "edges": ["order_submit -> inventory_check -> material_pick"],
        }
        return ToolResult(summary=summary, raw=summary)

    def get_schema_directory(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str,
        workshop: str | None = None,
        query: str = "",
        limit: int = 50,
    ) -> ToolResult:
        call = {"query": query, "limit": limit}
        call.update(_addressing_payload(environment, base, workshop))
        self.calls.append(("get_schema_directory", call))
        prefix = f"{workshop}_EBR_" if workshop else ""
        summary = {
            "environment": environment,
            "base": base,
            "workshop": workshop,
            "engine": "mysql",
            "tables": [
                {
                    "name": f"{prefix}order",
                    "columns": [
                        {"name": "order_no", "data_type": "varchar", "nullable": False},
                        {"name": "status", "data_type": "varchar", "nullable": True},
                    ],
                }
            ],
            "table_count": 1,
            "diagnostic_action": "use_listed_tables_and_columns_only",
        }
        return ToolResult(
            summary=summary,
            raw={"table_count": 1},
            metadata={"source": "fake-schema-directory"},
        )

    def query_loki(
        self,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        call = {"selector": selector, "query": query, "minutes": minutes}
        call.update(_addressing_payload(environment, base, workshop))
        self.calls.append(("query_loki", call))
        summary = {
            "selector": selector,
            "line_count": 1,
            "highlights": ["MaterialNotEnoughException"],
        }
        return ToolResult(summary=summary, raw=summary)

    def query_database(
        self,
        datasource: str,
        sql: str,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        call = {"datasource": datasource, "sql": sql, "limit": limit}
        call.update(_addressing_payload(environment, base, workshop))
        self.calls.append(("query_database", call))
        summary = {
            "datasource": datasource,
            "row_count": 1,
            "rows": [{"order_no": "MO20260627001", "status": "WAITING_MATERIAL"}],
        }
        return ToolResult(summary=summary, raw=summary)

    def query_redis_get(
        self,
        datasource: str,
        key: str,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        call = {"datasource": datasource, "key": key}
        call.update(_addressing_payload(environment, base, workshop))
        self.calls.append(("query_redis_get", call))
        summary = {"datasource": datasource, "key": key, "value_summary": "WAITING_MATERIAL"}
        return ToolResult(summary=summary, raw=summary)

    def query_redis_scan(
        self,
        datasource: str,
        pattern: str,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        call = {"datasource": datasource, "pattern": pattern}
        call.update(_addressing_payload(environment, base, workshop))
        self.calls.append(("query_redis_scan", call))
        summary = {"datasource": datasource, "pattern": pattern, "keys": ["order:MO20260627001"]}
        return ToolResult(summary=summary, raw=summary)


class HttpInternalApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str = "",
        timeout_seconds: int = 10,
        max_response_chars: int = 4000,
        urlopen_func: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout_seconds = timeout_seconds
        self.max_response_chars = max_response_chars
        self.urlopen_func = urlopen_func

    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return self._post(
            "/tools/context/er",
            {"query": query, "project_code": context.project_code},
            context,
        )

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return self._post(
            "/tools/context/business-flow",
            {"query": query, "project_code": context.project_code},
            context,
        )

    def get_schema_directory(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str,
        workshop: str | None = None,
        query: str = "",
        limit: int = 50,
    ) -> ToolResult:
        payload: dict[str, Any] = {"query": query, "limit": limit}
        payload.update(_addressing_payload(environment, base, workshop))
        return self._post("/tools/schema/directory", payload, context)

    def query_loki(
        self,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        payload: dict[str, Any] = {
            "selector": selector,
            "query": query,
            "minutes": minutes,
            "limit": limit,
        }
        payload.update(_addressing_payload(environment, base, workshop))
        return self._post("/tools/loki/query", payload, context)

    def query_database(
        self,
        datasource: str,
        sql: str,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        payload: dict[str, Any] = {"datasource": datasource, "sql": sql, "limit": limit}
        payload.update(_addressing_payload(environment, base, workshop))
        return self._post("/tools/database/query", payload, context)

    def query_redis_get(
        self,
        datasource: str,
        key: str,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        payload: dict[str, Any] = {"datasource": datasource, "key": key}
        payload.update(_addressing_payload(environment, base, workshop))
        return self._post("/tools/redis/get", payload, context)

    def query_redis_scan(
        self,
        datasource: str,
        pattern: str,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str | None = None,
        base: str | None = None,
        workshop: str | None = None,
    ) -> ToolResult:
        payload: dict[str, Any] = {"datasource": datasource, "pattern": pattern, "limit": limit}
        payload.update(_addressing_payload(environment, base, workshop))
        return self._post("/tools/redis/scan", payload, context)

    def _post(self, path: str, payload: dict[str, Any], context: ToolRequestContext) -> ToolResult:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(context),
            method="POST",
        )
        try:
            with self.urlopen_func(request, timeout=self.timeout_seconds) as response:
                body = self._read_json_response(response.read())
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            message = _safe_error_text(str(exc), self.max_response_chars)
            raise RetryableExecutionError(
                f"Internal API Platform request failed: {message}",
                safe_message=f"Internal API Platform request failed: {message}",
            ) from exc
        except json.JSONDecodeError as exc:
            raise RetryableExecutionError(
                "Internal API Platform returned invalid JSON",
                safe_message="Internal API Platform returned invalid JSON",
            ) from exc
        summary = body.get("summary", body)
        raw = body.get("raw", body)
        metadata = body.get("metadata", {})
        return ToolResult(
            summary=summary if isinstance(summary, dict) else {"value": summary},
            raw=raw if isinstance(raw, dict) else {"value": raw},
            metadata=metadata if isinstance(metadata, dict) else {},
            truncated=bool(body.get("truncated", False)),
        )

    def _headers(self, context: ToolRequestContext) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "X-Agent-Job-Id": context.job_id,
            "X-Agent-User-Id": context.user_id,
            "X-Agent-Project-Code": context.project_code,
            "X-Correlation-Id": context.correlation_id,
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _read_json_response(self, body: bytes) -> dict[str, Any]:
        text = body.decode("utf-8")
        if len(text) > self.max_response_chars * 20:
            text = text[: self.max_response_chars * 20]
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"summary": {"value": parsed}}

    def _raise_http_error(self, exc: urllib.error.HTTPError) -> None:
        body = _read_error_body(exc, self.max_response_chars)
        message = _error_message_from_body(body) or exc.reason or f"HTTP {exc.code}"
        message = _safe_error_text(str(message), self.max_response_chars)
        if exc.code in TRANSIENT_HTTP_STATUSES:
            raise RetryableExecutionError(
                f"Internal API Platform transient error ({exc.code}): {message}",
                safe_message=f"Internal API Platform transient error ({exc.code}): {message}",
            ) from exc
        if _is_policy_denial(body):
            raise ToolPolicyError(
                f"Internal API Platform policy denied: {message}",
                safe_message=f"Internal API Platform policy denied: {message}",
            ) from exc
        if exc.code in NON_RETRYABLE_HTTP_STATUSES:
            raise NonRetryableExecutionError(
                f"Internal API Platform rejected request ({exc.code}): {message}",
                safe_message=f"Internal API Platform rejected request ({exc.code}): {message}",
            ) from exc
        raise RetryableExecutionError(
            f"Internal API Platform HTTP error ({exc.code}): {message}",
            safe_message=f"Internal API Platform HTTP error ({exc.code}): {message}",
        ) from exc


def _read_error_body(exc: urllib.error.HTTPError, max_chars: int) -> dict[str, Any]:
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        return {}
    if not raw:
        return {}
    raw = raw[: max_chars * 20]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"message": raw}
    return parsed if isinstance(parsed, dict) else {"message": parsed}


def _error_message_from_body(body: dict[str, Any]) -> str:
    body = _unwrap_detail(body)
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or error.get("type")
        action = error.get("diagnostic_action")
        if action:
            return f"{message or ''} diagnostic_action={action}".strip()
        return str(message or "")
    if error:
        return str(error)
    for key in ("message", "detail", "safe_message"):
        if body.get(key):
            return str(body[key])
    return ""


def _is_policy_denial(body: dict[str, Any]) -> bool:
    body = _unwrap_detail(body)
    candidates: list[Any] = [body.get("code"), body.get("type"), body.get("error_code")]
    error = body.get("error")
    if isinstance(error, dict):
        candidates.extend([error.get("code"), error.get("type")])
    return any(str(value).lower() == "policy_denied" for value in candidates if value)


def _unwrap_detail(body: dict[str, Any]) -> dict[str, Any]:
    detail = body.get("detail")
    return detail if isinstance(detail, dict) else body


def _safe_error_text(text: str, max_chars: int) -> str:
    masked = mask_sensitive({"message": text})["message"]
    redacted = str(masked)
    patterns = (
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(internal_api_auth_token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
    )
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    compact = " ".join(redacted.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
