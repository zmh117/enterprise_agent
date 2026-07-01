from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest

from app.shared.config import LokiSettings, Settings, load_settings


SELECTOR_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.:/-]+$")
ALLOWED_SELECTOR_LABELS = {"cluster", "container", "region", "service", "service_name"}
MAX_QUERY_CHARS = 300
RETRYABLE_UPSTREAM_STATUSES = {429, 502, 503, 504}


@dataclass(frozen=True)
class LokiQuery:
    selector: dict[str, str]
    query: str
    minutes: int
    limit: int
    logql: str


def create_app(
    settings: Settings | None = None,
    *,
    urlopen_func: Callable[..., Any] = urlopen,
) -> FastAPI:
    settings = settings or load_settings()
    loki_gateway = LokiGateway(settings.loki, urlopen_func=urlopen_func)
    app = FastAPI(title="Local Internal API Platform", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "local-internal-api-platform",
            "loki": {
                "base_url_configured": bool(settings.loki.base_url),
                "base_url": settings.loki.base_url,
                "max_minutes": settings.loki.max_minutes,
                "max_lines": settings.loki.max_lines,
                "max_response_chars": settings.loki.max_response_chars,
                "tenant_configured": bool(settings.loki.tenant_id),
            },
        }

    @app.post("/tools/context/er")
    async def er_context(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "source": "local-placeholder-er-context",
            "project_code": str(payload.get("project_code", "default")),
            "query": str(payload.get("query", "")),
            "message": "Local ER context is not connected; placeholder context returned.",
            "tables": [],
            "fields": [],
            "relationships": [],
        }
        return _envelope(summary, request, source="local-er-placeholder")

    @app.post("/tools/context/business-flow")
    async def business_flow_context(
        request: FastAPIRequest, payload: dict[str, Any]
    ) -> dict[str, Any]:
        summary = {
            "source": "local-placeholder-business-flow-context",
            "project_code": str(payload.get("project_code", "default")),
            "query": str(payload.get("query", "")),
            "message": "Local business-flow context is not connected; placeholder context returned.",
            "nodes": [],
            "edges": [],
        }
        return _envelope(summary, request, source="local-business-flow-placeholder")

    @app.post("/tools/loki/query")
    async def loki_query(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = loki_gateway.query(payload)
        except LocalPlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        result.metadata["request_id"] = request.headers.get("x-correlation-id", "-")
        result.metadata["duration_ms"] = int((time.monotonic() - started) * 1000)
        return {
            "summary": result.summary,
            "raw": result.raw,
            "truncated": result.truncated,
            "metadata": result.metadata,
        }

    @app.post("/tools/database/query")
    async def database_query() -> None:
        raise _tool_not_configured("database")

    @app.post("/tools/redis/get")
    async def redis_get() -> None:
        raise _tool_not_configured("redis")

    @app.post("/tools/redis/scan")
    async def redis_scan() -> None:
        raise _tool_not_configured("redis")

    return app


@dataclass
class LocalToolResult:
    summary: dict[str, Any]
    raw: dict[str, Any]
    metadata: dict[str, Any]
    truncated: bool


class LocalPlatformError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = {"error": {"code": code, "message": message}}


class LokiGateway:
    def __init__(
        self,
        settings: LokiSettings,
        *,
        urlopen_func: Callable[..., Any] = urlopen,
    ) -> None:
        self.settings = settings
        self.urlopen_func = urlopen_func

    def validate(self, payload: dict[str, Any]) -> LokiQuery:
        selector = _selector_from_payload(payload)
        query = str(payload.get("query", "")).strip()
        if len(query) > MAX_QUERY_CHARS:
            raise LocalPlatformError(400, "invalid_loki_query", "query is too long")
        try:
            minutes = int(payload.get("minutes", 15))
            limit = int(payload.get("limit", min(100, self.settings.max_lines)))
        except (TypeError, ValueError) as exc:
            raise LocalPlatformError(
                400, "invalid_loki_query", "minutes and limit must be integers"
            ) from exc
        if minutes < 1:
            raise LocalPlatformError(400, "invalid_loki_query", "minutes must be greater than zero")
        if minutes > self.settings.max_minutes:
            raise LocalPlatformError(400, "invalid_loki_query", "minutes exceeds local Loki limit")
        if limit < 1:
            raise LocalPlatformError(400, "invalid_loki_query", "limit must be greater than zero")
        if limit > self.settings.max_lines:
            raise LocalPlatformError(400, "invalid_loki_query", "limit exceeds local Loki limit")
        logql = build_logql(selector, query)
        return LokiQuery(selector=selector, query=query, minutes=minutes, limit=limit, logql=logql)

    def query(self, payload: dict[str, Any]) -> LocalToolResult:
        loki_query = self.validate(payload)
        body = self._query_loki(loki_query)
        return summarize_loki_response(body, loki_query, self.settings.max_response_chars)

    def _query_loki(self, loki_query: LokiQuery) -> dict[str, Any]:
        end_ns = time.time_ns()
        start_ns = end_ns - loki_query.minutes * 60 * 1_000_000_000
        query_params = urllib.parse.urlencode(
            {
                "query": loki_query.logql,
                "start": str(start_ns),
                "end": str(end_ns),
                "limit": str(loki_query.limit),
                "direction": "backward",
            }
        )
        url = f"{self.settings.base_url.rstrip('/')}/loki/api/v1/query_range?{query_params}"
        headers = {"accept": "application/json"}
        if self.settings.tenant_id:
            headers["X-Scope-OrgID"] = self.settings.tenant_id
        request = Request(url, headers=headers, method="GET")
        try:
            with self.urlopen_func(request, timeout=10) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise LocalPlatformError(
                503,
                "loki_unavailable",
                f"Loki request failed: {_safe_error_text(str(exc))}",
            ) from exc
        except json.JSONDecodeError as exc:
            raise LocalPlatformError(
                503, "loki_invalid_response", "Loki returned invalid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise LocalPlatformError(503, "loki_invalid_response", "Loki returned invalid JSON")
        if parsed.get("status") not in {None, "success"}:
            raise LocalPlatformError(
                503,
                "loki_error",
                _safe_error_text(str(parsed.get("error") or "Loki query failed")),
            )
        return parsed

    def _raise_http_error(self, exc: urllib.error.HTTPError) -> None:
        message = _read_loki_error(exc)
        if exc.code in RETRYABLE_UPSTREAM_STATUSES:
            raise LocalPlatformError(
                503,
                "loki_unavailable",
                f"Loki transient error ({exc.code}): {message}",
            ) from exc
        raise LocalPlatformError(
            400,
            "loki_rejected_query",
            f"Loki rejected query ({exc.code}): {message}",
        ) from exc


def build_logql(selector: dict[str, str], query: str) -> str:
    labels = ",".join(
        f'{label}="{_escape_logql_string(value)}"' for label, value in sorted(selector.items())
    )
    selector_text = f"{{{labels}}}"
    if not query:
        return selector_text
    return f'{selector_text} |= "{_escape_logql_string(query)}"'


def _selector_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    raw_selector = payload.get("selector")
    if raw_selector is None:
        service = str(payload.get("service", "")).strip()
        raw_selector = {"service": service} if service else {}
    if not isinstance(raw_selector, dict):
        raise LocalPlatformError(400, "invalid_loki_query", "selector must be an object")

    selector: dict[str, str] = {}
    for raw_label, raw_value in raw_selector.items():
        label = str(raw_label).strip()
        if label not in ALLOWED_SELECTOR_LABELS:
            raise LocalPlatformError(
                400,
                "invalid_loki_query",
                f"selector label is not allowed: {label}",
            )
        if not isinstance(raw_value, str):
            raise LocalPlatformError(400, "invalid_loki_query", "selector values must be strings")
        value = raw_value.strip()
        if not value:
            raise LocalPlatformError(400, "invalid_loki_query", "selector value is required")
        if not SELECTOR_VALUE_PATTERN.fullmatch(value):
            raise LocalPlatformError(
                400,
                "invalid_loki_query",
                "selector contains unsafe characters",
            )
        selector[label] = value

    if not selector:
        raise LocalPlatformError(400, "invalid_loki_query", "selector is required")
    return selector


def summarize_loki_response(
    body: dict[str, Any],
    loki_query: LokiQuery,
    max_response_chars: int,
) -> LocalToolResult:
    streams = []
    highlights: list[str] = []
    total_lines = 0
    total_chars = 0
    truncated = False
    for item in _loki_result_items(body):
        stream = item.get("stream") if isinstance(item, dict) else {}
        values = item.get("values") if isinstance(item, dict) else []
        labels = stream if isinstance(stream, dict) else {}
        stream_line_count = 0
        if isinstance(values, list):
            for value in values:
                line = _line_from_loki_value(value)
                if line is None:
                    continue
                total_lines += 1
                stream_line_count += 1
                redacted = _redact_text(line)
                if total_chars + len(redacted) <= max_response_chars:
                    highlights.append(redacted)
                    total_chars += len(redacted)
                else:
                    truncated = True
        streams.append({"labels": labels, "line_count": stream_line_count})
    summary = {
        "selector": loki_query.selector,
        "service": loki_query.selector.get("service", ""),
        "query": loki_query.query,
        "logql": loki_query.logql,
        "minutes": loki_query.minutes,
        "line_count": total_lines,
        "highlights": highlights,
        "streams": streams,
        "truncated": truncated,
    }
    raw = {
        "result_type": _nested_value(body, ["data", "resultType"]),
        "result_count": len(_loki_result_items(body)),
    }
    return LocalToolResult(
        summary=summary,
        raw=raw,
        metadata={"source": "local-loki", "duration_ms": 0, "request_id": "-"},
        truncated=truncated,
    )


def _loki_result_items(body: dict[str, Any]) -> list[Any]:
    result = _nested_value(body, ["data", "result"])
    return result if isinstance(result, list) else []


def _nested_value(value: dict[str, Any], keys: list[str]) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _line_from_loki_value(value: Any) -> str | None:
    if isinstance(value, list) and len(value) >= 2 and isinstance(value[1], str):
        return value[1]
    return None


def _envelope(summary: dict[str, Any], request: FastAPIRequest, source: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "raw": summary,
        "truncated": False,
        "metadata": {
            "request_id": request.headers.get("x-correlation-id", "-"),
            "source": source,
            "duration_ms": 1,
        },
    }


def _tool_not_configured(tool_name: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "tool_not_configured",
                "message": f"{tool_name} tool is not configured in local internal platform",
            }
        },
    )


def _escape_logql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _read_loki_error(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        return str(exc.reason or f"HTTP {exc.code}")
    if not raw:
        return str(exc.reason or f"HTTP {exc.code}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _safe_error_text(raw)
    if isinstance(parsed, dict):
        return _safe_error_text(str(parsed.get("error") or parsed.get("message") or raw))
    return _safe_error_text(raw)


def _safe_error_text(text: str, max_chars: int = 300) -> str:
    redacted = _redact_text(text)
    compact = " ".join(redacted.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _redact_text(text: str) -> str:
    patterns = (
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(password\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(secret\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
    )
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted
