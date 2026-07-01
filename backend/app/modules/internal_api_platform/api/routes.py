from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest

from ..application.platform_service import PlatformService
from ..domain.errors import PlatformError, PolicyViolation, ResolutionError
from ..domain.results import ToolResponse
from ..domain.topology import ResourceKind


def _user_id(request: FastAPIRequest) -> str:
    return request.headers.get("x-agent-user-id", "").strip()


def _require(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PolicyViolation(f"Field '{key}' is required")
    return value.strip()


def _optional(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PolicyViolation(f"Field '{key}' must be a non-empty string when provided")
    return value.strip()


def _envelope(request: FastAPIRequest, started: float, result: ToolResponse) -> dict[str, Any]:
    result.metadata.setdefault("request_id", request.headers.get("x-correlation-id", "-"))
    result.metadata["duration_ms"] = int((time.monotonic() - started) * 1000)
    return {
        "summary": result.summary,
        "raw": result.raw,
        "truncated": result.truncated,
        "metadata": result.metadata,
    }


def register_routes(app: FastAPI, *, service: PlatformService) -> None:
    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "mode": "internal-api-platform"}

    @app.post("/tools/context/er")
    async def er_context(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        result = service.er_context(user_id=_user_id(request), query=str(payload.get("query", "")))
        return _envelope(request, started, result)

    @app.post("/tools/context/business-flow")
    async def business_flow_context(
        request: FastAPIRequest, payload: dict[str, Any]
    ) -> dict[str, Any]:
        started = time.monotonic()
        result = service.business_flow_context(
            user_id=_user_id(request), query=str(payload.get("query", ""))
        )
        return _envelope(request, started, result)

    @app.post("/tools/resolve")
    async def resolve(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = service.describe_target(
                user_id=_user_id(request),
                environment=_require(payload, "environment"),
                base=_require(payload, "base"),
                workshop=_optional(payload, "workshop"),
                kind=_resource_kind(payload.get("kind", "database")),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/database/query")
    async def database_query(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = service.query_database(
                user_id=_user_id(request),
                environment=_require(payload, "environment"),
                base=_require(payload, "base"),
                workshop=_optional(payload, "workshop"),
                sql=_require(payload, "sql"),
                limit=_int_or_none(payload.get("limit")),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/redis/get")
    async def redis_get(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = service.redis_get(
                user_id=_user_id(request),
                environment=_require(payload, "environment"),
                base=_require(payload, "base"),
                workshop=_optional(payload, "workshop"),
                key=_require(payload, "key"),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/redis/scan")
    async def redis_scan(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = service.redis_scan(
                user_id=_user_id(request),
                environment=_require(payload, "environment"),
                base=_require(payload, "base"),
                workshop=_optional(payload, "workshop"),
                pattern=_require(payload, "pattern"),
                limit=_int_or_none(payload.get("limit")),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/loki/query")
    async def loki_query(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        selector = payload.get("selector")
        if not isinstance(selector, dict):
            selector = {}
        try:
            result = service.query_loki(
                user_id=_user_id(request),
                environment=_require(payload, "environment"),
                base=_require(payload, "base"),
                workshop=_optional(payload, "workshop"),
                selector={str(k): str(v) for k, v in selector.items()},
                query=str(payload.get("query", "")),
                minutes=_int_or_none(payload.get("minutes")) or 15,
                limit=_int_or_none(payload.get("limit")) or 100,
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)


def _resource_kind(value: Any) -> ResourceKind:
    try:
        return ResourceKind(str(value))
    except ValueError as exc:
        raise ResolutionError(f"Unknown resource kind: {value}") from exc


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyViolation("Numeric field must be an integer") from exc
