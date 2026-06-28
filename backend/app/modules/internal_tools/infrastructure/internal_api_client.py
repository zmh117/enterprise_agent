from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ToolResult:
    summary: dict[str, Any]
    raw: dict[str, Any]


class InternalApiClient(Protocol):
    def get_er_context(self, query: str, project_code: str) -> ToolResult: ...

    def get_business_flow_context(self, query: str, project_code: str) -> ToolResult: ...

    def query_loki(self, service: str, query: str, minutes: int, limit: int) -> ToolResult: ...

    def query_database(self, datasource: str, sql: str, limit: int) -> ToolResult: ...

    def query_redis_get(self, datasource: str, key: str) -> ToolResult: ...

    def query_redis_scan(self, datasource: str, pattern: str, limit: int) -> ToolResult: ...


class FakeInternalApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_er_context(self, query: str, project_code: str) -> ToolResult:
        self.calls.append(("get_er_context", {"query": query, "project_code": project_code}))
        summary = {
            "tables": ["ws_a_order", "ws_a_material", "ws_a_inventory"],
            "fields": ["status", "material_id", "inventory_qty"],
            "relationships": ["ws_a_order.material_id -> ws_a_material.id"],
        }
        return ToolResult(summary=summary, raw=summary)

    def get_business_flow_context(self, query: str, project_code: str) -> ToolResult:
        self.calls.append(
            ("get_business_flow_context", {"query": query, "project_code": project_code})
        )
        summary = {
            "nodes": ["order_submit", "inventory_check", "material_pick"],
            "edges": ["order_submit -> inventory_check -> material_pick"],
        }
        return ToolResult(summary=summary, raw=summary)

    def query_loki(self, service: str, query: str, minutes: int, limit: int) -> ToolResult:
        self.calls.append(("query_loki", {"service": service, "query": query, "minutes": minutes}))
        summary = {
            "service": service,
            "line_count": 1,
            "highlights": ["MaterialNotEnoughException"],
        }
        return ToolResult(summary=summary, raw=summary)

    def query_database(self, datasource: str, sql: str, limit: int) -> ToolResult:
        self.calls.append(
            ("query_database", {"datasource": datasource, "sql": sql, "limit": limit})
        )
        summary = {
            "datasource": datasource,
            "row_count": 1,
            "rows": [{"order_no": "MO20260627001", "status": "WAITING_MATERIAL"}],
        }
        return ToolResult(summary=summary, raw=summary)

    def query_redis_get(self, datasource: str, key: str) -> ToolResult:
        self.calls.append(("query_redis_get", {"datasource": datasource, "key": key}))
        summary = {"datasource": datasource, "key": key, "value_summary": "WAITING_MATERIAL"}
        return ToolResult(summary=summary, raw=summary)

    def query_redis_scan(self, datasource: str, pattern: str, limit: int) -> ToolResult:
        self.calls.append(("query_redis_scan", {"datasource": datasource, "pattern": pattern}))
        summary = {"datasource": datasource, "pattern": pattern, "keys": ["order:MO20260627001"]}
        return ToolResult(summary=summary, raw=summary)


class HttpInternalApiClient:
    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_er_context(self, query: str, project_code: str) -> ToolResult:
        return self._post("/tools/context/er", {"query": query, "project_code": project_code})

    def get_business_flow_context(self, query: str, project_code: str) -> ToolResult:
        return self._post(
            "/tools/context/business-flow", {"query": query, "project_code": project_code}
        )

    def query_loki(self, service: str, query: str, minutes: int, limit: int) -> ToolResult:
        return self._post(
            "/tools/loki/query",
            {"service": service, "query": query, "minutes": minutes, "limit": limit},
        )

    def query_database(self, datasource: str, sql: str, limit: int) -> ToolResult:
        return self._post(
            "/tools/database/query", {"datasource": datasource, "sql": sql, "limit": limit}
        )

    def query_redis_get(self, datasource: str, key: str) -> ToolResult:
        return self._post("/tools/redis/get", {"datasource": datasource, "key": key})

    def query_redis_scan(self, datasource: str, pattern: str, limit: int) -> ToolResult:
        return self._post(
            "/tools/redis/scan",
            {"datasource": datasource, "pattern": pattern, "limit": limit},
        )

    def _post(self, path: str, payload: dict[str, Any]) -> ToolResult:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        return ToolResult(summary=body.get("summary", body), raw=body)
