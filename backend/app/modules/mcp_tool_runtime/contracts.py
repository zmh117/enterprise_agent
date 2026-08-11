from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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
    tool_call_id: str = ""


class ReadOnlyToolExecutor(Protocol):
    """The fixed in-process provider boundary owned by ``tool-mcp``.

    It is deliberately not an HTTP client and has no token or configurable URL.
    """

    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult: ...

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult: ...

    def get_schema_directory(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str = "",
        workshop: str | None = None,
        placement: str | None = None,
        query: str = "",
        limit: int = 50,
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
        placement: str | None = None,
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
        placement: str | None = None,
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
        placement: str | None = None,
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

    def diagnose_loki_labels(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str = "",
        workshop: str | None = None,
        minutes: int = 15,
        limit: int = 100,
    ) -> ToolResult: ...

    def diagnose_loki_label_values(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str = "",
        label: str,
        workshop: str | None = None,
        minutes: int = 15,
        limit: int = 100,
    ) -> ToolResult: ...

    def diagnose_loki_probe(
        self,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str = "",
        workshop: str | None = None,
    ) -> ToolResult: ...


class FakeReadOnlyToolExecutor:
    """Deterministic in-process executor for tests that do not start ``tool-mcp``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _result(self, name: str, **values: Any) -> ToolResult:
        self.calls.append((name, values))
        summary = {"source": "fake-tool-mcp", **values}
        return ToolResult(summary=summary, raw={})

    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return self._result("get_er_context", query=query, project_code=context.project_code)

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return self._result(
            "get_business_flow_context", query=query, project_code=context.project_code
        )

    def __getattr__(self, name: str) -> Any:
        def invoke(*args: Any, **kwargs: Any) -> ToolResult:
            del args
            kwargs.pop("context", None)
            return self._result(name, **kwargs)

        return invoke
