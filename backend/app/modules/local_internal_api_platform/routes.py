from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest

from app.shared.config import Settings

from .envelope import LocalPlatformError, envelope, tool_not_configured
from .loki_gateway import LokiGateway


def register_routes(
    app: FastAPI,
    *,
    settings: Settings,
    loki_gateway: LokiGateway,
) -> None:
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
        return envelope(summary, request, source="local-er-placeholder")

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
        return envelope(summary, request, source="local-business-flow-placeholder")

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
        raise tool_not_configured("database")

    @app.post("/tools/redis/get")
    async def redis_get() -> None:
        raise tool_not_configured("redis")

    @app.post("/tools/redis/scan")
    async def redis_scan() -> None:
        raise tool_not_configured("redis")
