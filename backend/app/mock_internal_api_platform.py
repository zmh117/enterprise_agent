from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request


def create_app() -> Any:
    app = FastAPI(title="Mock Internal API Platform", version="0.1.0")

    def scenario(request: Request, payload: dict[str, Any]) -> str:
        return str(request.headers.get("x-mock-scenario") or payload.get("mock_scenario") or "")

    def envelope(summary: dict[str, Any], request: Request, source: str) -> dict[str, Any]:
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

    def maybe_fail(request: Request, payload: dict[str, Any]) -> None:
        mode = scenario(request, payload)
        if mode == "policy_denied":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": {
                        "code": "policy_denied",
                        "message": "mock policy denied",
                    }
                },
            )
        if mode == "timeout":
            time.sleep(2)
        if mode == "error_503":
            raise HTTPException(status_code=503, detail={"message": "mock upstream overloaded"})

    @app.post("/tools/context/er")
    async def er_context(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        maybe_fail(request, payload)
        summary = {
            "tables": ["ws_a_order", "ws_a_material", "ws_a_inventory"],
            "fields": ["status", "material_id", "inventory_qty"],
            "relationships": ["ws_a_order.material_id -> ws_a_material.id"],
        }
        return envelope(summary, request, "mock-er-context")

    @app.post("/tools/context/business-flow")
    async def business_flow_context(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        maybe_fail(request, payload)
        summary = {
            "nodes": ["order_submit", "inventory_check", "material_pick"],
            "edges": ["order_submit -> inventory_check -> material_pick"],
        }
        return envelope(summary, request, "mock-business-flow-context")

    @app.post("/tools/loki/query")
    async def loki_query(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        maybe_fail(request, payload)
        summary = {
            "service": payload.get("service", "unknown"),
            "line_count": 1,
            "highlights": ["MaterialNotEnoughException"],
        }
        return envelope(summary, request, "mock-loki")

    @app.post("/tools/database/query")
    async def database_query(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        maybe_fail(request, payload)
        if scenario(request, payload) == "large":
            rows = [{"index": index, "value": "x" * 200} for index in range(100)]
        else:
            rows = [{"order_no": "MO20260627001", "status": "WAITING_MATERIAL"}]
        summary = {
            "datasource": payload.get("datasource", "default"),
            "row_count": len(rows),
            "rows": rows,
        }
        return envelope(summary, request, "mock-database")

    @app.post("/tools/redis/get")
    async def redis_get(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        maybe_fail(request, payload)
        summary = {
            "datasource": payload.get("datasource", "default"),
            "key": payload.get("key", ""),
            "value_summary": "WAITING_MATERIAL",
        }
        return envelope(summary, request, "mock-redis")

    @app.post("/tools/redis/scan")
    async def redis_scan(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        maybe_fail(request, payload)
        summary = {
            "datasource": payload.get("datasource", "default"),
            "pattern": payload.get("pattern", ""),
            "keys": ["order:MO20260627001"],
        }
        return envelope(summary, request, "mock-redis")

    return app
