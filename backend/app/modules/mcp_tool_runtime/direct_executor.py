from __future__ import annotations

from typing import Any

from app.modules.mcp_tool_runtime.domain.loki_policy import (
    assert_loki_label_allowed,
    build_effective_selector,
)
from app.modules.mcp_tool_runtime.domain.redis_policy import (
    assert_read_command,
    enforce_scan_pattern,
)
from app.modules.mcp_tool_runtime.domain.sql.analyzer import analyze_readonly_query
from app.modules.mcp_tool_runtime.domain.topology import DatabaseEngine
from app.modules.mcp_tool_runtime.infrastructure.db.drivers import (
    MysqlExecutor,
    OracleExecutor,
    SqlServerExecutor,
)
from app.modules.mcp_tool_runtime.infrastructure.db.schema_directory import (
    MySqlSchemaInspector,
    OracleSchemaInspector,
    SchemaInspectorFactory,
    SqlServerSchemaInspector,
)
from app.modules.mcp_tool_runtime.infrastructure.loki_gateway import HttpLokiClient
from app.modules.mcp_tool_runtime.infrastructure.redis_gateway import RealRedisGateway
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError

from .contracts import ToolRequestContext, ToolResult
from .resource_resolver import DirectResourceResolver, ResolvedToolResource


class DirectReadOnlyToolExecutor:
    """Direct provider executor used in-process by the standard MCP server."""

    def __init__(
        self,
        resolver: DirectResourceResolver,
        *,
        limits: ExecutionSettings,
    ) -> None:
        self.resolver = resolver
        self.limits = limits
        max_bytes = max(4096, limits.max_tool_response_chars * 8)
        self.executors = {
            DatabaseEngine.MYSQL: MysqlExecutor(max_response_bytes=max_bytes),
            DatabaseEngine.SQLSERVER: SqlServerExecutor(max_response_bytes=max_bytes),
            DatabaseEngine.ORACLE: OracleExecutor(max_response_bytes=max_bytes),
        }
        self.schema_inspectors = SchemaInspectorFactory(
            {
                DatabaseEngine.MYSQL: MySqlSchemaInspector(),
                DatabaseEngine.SQLSERVER: SqlServerSchemaInspector(),
                DatabaseEngine.ORACLE: OracleSchemaInspector(),
            }
        )
        self.redis = RealRedisGateway()

    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        del context
        summary = {
            "query": query,
            "addressing": self.resolver.directory(),
            "tables": [],
            "fields": [],
            "relationships": [],
            "note": "Use the Resource address and get_schema_directory before querying data.",
        }
        return ToolResult(summary=summary, raw={"resource_count": len(summary["addressing"]["resources"] )})

    def get_business_flow_context(
        self, query: str, context: ToolRequestContext
    ) -> ToolResult:
        del context
        summary = {
            "query": query,
            "addressing": self.resolver.directory(),
            "nodes": [],
            "edges": [],
            "note": "Business-flow graph is not connected; use available read-only evidence.",
        }
        return ToolResult(summary=summary, raw={"resource_count": len(summary["addressing"]["resources"] )})

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
    ) -> ToolResult:
        del context
        resource = self._resolve(
            "database", environment, base, workshop, placement
        )
        directory = self.schema_inspectors.for_engine(resource.binding.engine).read(
            resource.binding,
            table_prefix=None,
            query=query,
            table_limit=max(1, min(int(limit), 100)),
            column_limit=80,
        )
        summary = {
            "environment": resource.binding.environment.code,
            "base": base or None,
            "workshop": workshop or None,
            "engine": resource.binding.engine.value,
            **directory.to_summary(),
            "diagnostic_action": (
                "use_listed_tables_and_columns_only"
                if directory.tables
                else "stop_and_report_insufficient_evidence"
            ),
        }
        return self._result(resource, summary, truncated=directory.truncated)

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
    ) -> ToolResult:
        del datasource, context
        resource = self._resolve(
            "database", environment or "", base or "", workshop, placement
        )
        binding = resource.binding
        database = binding.database
        assert database is not None
        allowed_database: str | None = None
        allowed_schema: str | None = None
        if binding.engine is DatabaseEngine.MYSQL:
            allowed_database = database.database or None
        elif binding.engine is DatabaseEngine.SQLSERVER:
            allowed_database = database.database or None
            allowed_schema = database.schema or "dbo"
        elif binding.engine is DatabaseEngine.ORACLE:
            allowed_schema = database.schema or database.user or None
        maximum = max(1, min(int(limit or 100), 100))
        analyzed = analyze_readonly_query(
            sql,
            engine=binding.engine,
            max_rows=maximum,
            table_prefix=None,
            allowed_database=allowed_database,
            allowed_schema=allowed_schema,
            oracle_compat=database.oracle_compat,
        )
        directory = self.schema_inspectors.for_engine(binding.engine).read(
            binding,
            table_prefix=None,
            query="",
            table_limit=500,
            column_limit=200,
        )
        if not directory.tables:
            raise ToolPolicyError(
                "Schema directory is empty for the resolved MCP Resource",
                safe_message="数据库结构目录为空，不能安全执行查询",
                error_code="mcp_schema_directory_empty",
            )
        known = {name.lower() for name in directory.table_names()}
        unknown = [name for name in analyzed.tables if name.lower() not in known]
        if unknown:
            raise ToolPolicyError(
                f"SQL references tables outside the schema directory: {unknown}",
                safe_message="SQL 引用了结构目录之外的表",
                error_code="mcp_database_table_denied",
            )
        executor = self.executors[binding.engine]
        executed = executor.execute(
            binding,
            analyzed.sql,
            timeout_seconds=min(30, max(1, self.limits.timeout_seconds)),
            max_rows=maximum,
        )
        return self._result(
            resource,
            {
                "engine": binding.engine.value,
                "tables": analyzed.tables,
                "row_count": len(executed.rows),
                "columns": executed.columns,
                "rows": executed.rows,
            },
            raw={"row_count": len(executed.rows)},
            truncated=executed.truncated,
        )

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
    ) -> ToolResult:
        del datasource, context
        assert_read_command("get")
        if not key or len(key) > 512:
            raise ToolPolicyError(
                "Redis key is invalid",
                safe_message="Redis Key 无效",
                error_code="mcp_redis_key_invalid",
            )
        resource = self._resolve("redis", environment or "", base or "", workshop, placement)
        response = self.redis.get(resource.binding, key)
        return self._result(
            resource,
            response.summary,
            raw=response.raw,
            truncated=response.truncated,
        )

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
    ) -> ToolResult:
        del datasource, context
        assert_read_command("scan")
        bounded = max(1, min(int(limit), self.limits.redis_scan_limit))
        normalized = enforce_scan_pattern(
            pattern,
            scan_limit=self.limits.redis_scan_limit,
            limit=bounded,
        )
        resource = self._resolve("redis", environment or "", base or "", workshop, placement)
        response = self.redis.scan(resource.binding, normalized, bounded)
        return self._result(
            resource,
            response.summary,
            raw=response.raw,
            truncated=response.truncated,
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
        del context
        resource = self._resolve("loki", environment or "", base or "", workshop, None)
        effective = build_effective_selector(selector)
        response = self._loki(resource).query(
            resource.binding,
            selector=effective,
            query=query,
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(resource, response.summary, raw=response.raw, truncated=response.truncated)

    def diagnose_loki_labels(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str = "",
        workshop: str | None = None,
        minutes: int = 15,
        limit: int = 100,
    ) -> ToolResult:
        del context
        resource = self._resolve("loki", environment, base, workshop, None)
        response = self._loki(resource).labels(
            resource.binding,
            selector={},
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(resource, response.summary, raw=response.raw, truncated=response.truncated)

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
    ) -> ToolResult:
        del context
        assert_loki_label_allowed(label)
        resource = self._resolve("loki", environment, base, workshop, None)
        response = self._loki(resource).label_values(
            resource.binding,
            label=label,
            selector={},
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(resource, response.summary, raw=response.raw, truncated=response.truncated)

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
    ) -> ToolResult:
        del context
        resource = self._resolve("loki", environment, base, workshop, None)
        response = self._loki(resource).probe(
            resource.binding,
            selector=build_effective_selector(selector),
            query=query,
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(resource, response.summary, raw=response.raw, truncated=response.truncated)

    def _resolve(
        self,
        kind: str,
        environment: str,
        base: str,
        workshop: str | None,
        placement: str | None,
    ) -> ResolvedToolResource:
        return self.resolver.resolve(
            resource_kind=kind,
            environment=environment,
            base=base,
            workshop=workshop or "",
            placement=placement or "",
        )

    def _loki(self, resource: ResolvedToolResource) -> HttpLokiClient:
        connection = resource.binding.loki
        assert connection is not None
        return HttpLokiClient(
            max_minutes=min(self.limits.max_loki_minutes, connection.max_minutes),
            max_lines=min(self.limits.max_loki_lines, connection.max_lines),
            max_response_chars=self.limits.max_tool_response_chars,
        )

    @staticmethod
    def _result(
        resource: ResolvedToolResource,
        summary: dict[str, Any],
        *,
        raw: dict[str, Any] | None = None,
        truncated: bool = False,
    ) -> ToolResult:
        return ToolResult(
            summary=summary,
            raw=raw or {},
            metadata={
                "source": "tool-mcp-direct-resource",
                "resource_code": resource.resource_code,
                "resource_revision_id": resource.resource_revision_id,
                "resource_content_hash": resource.resource_content_hash,
                "placement": resource.placement or None,
            },
            truncated=truncated,
        )
