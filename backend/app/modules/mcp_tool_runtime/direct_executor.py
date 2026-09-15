from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.mcp_tool_runtime.domain.loki_policy import (
    build_effective_selector,
)
from app.modules.mcp_tool_runtime.domain.redis_pagination import scan_complete, valid_scan_position
from app.modules.mcp_tool_runtime.domain.redis_policy import (
    assert_read_command,
    enforce_key_namespace,
    enforce_scan_pattern,
)
from app.modules.mcp_tool_runtime.domain.sql.analyzer import analyze_readonly_query
from app.modules.mcp_tool_runtime.domain.topology import DatabaseEngine
from app.modules.mcp_tool_runtime.infrastructure.db.drivers import (
    MysqlExecutor,
    OracleExecutor,
    SqlServerExecutor,
)
from app.modules.mcp_tool_runtime.infrastructure.db.executor import QueryExecutor
from app.modules.mcp_tool_runtime.infrastructure.db.schema_directory import (
    MySqlSchemaInspector,
    OracleSchemaInspector,
    SchemaInspectorFactory,
    SqlServerSchemaInspector,
)
from app.modules.mcp_tool_runtime.infrastructure.loki_gateway import HttpLokiClient
from app.modules.mcp_tool_runtime.infrastructure.redis_gateway import RealRedisGateway, RedisGateway
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError
from app.shared.loki_contract import assert_loki_label

from .contracts import ResourceAccessGrant, ToolRequestContext, ToolResult
from .pagination import ToolPaginationCursorCodec
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
        self.executors: dict[DatabaseEngine, QueryExecutor] = {
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
        self.redis: RedisGateway = RealRedisGateway()

    def list_available_tool_resources(
        self,
        context: ToolRequestContext,
        *,
        grants: tuple[ResourceAccessGrant, ...],
        resource_kind: str = "",
        query: str = "",
        limit: int = 50,
        cursor: str = "",
    ) -> ToolResult:
        selected_kind = str(resource_kind or "").strip().lower()
        normalized_query = str(query or "").strip().casefold()
        if len(normalized_query) > 128:
            raise ToolPolicyError(
                "Resource directory query is too large",
                safe_message="资源目录查询条件过长",
                error_code="mcp_resource_directory_input_invalid",
            )
        page_limit = int(limit or 50)
        if not 1 <= page_limit <= 50:
            raise ToolPolicyError(
                "Resource directory limit is invalid",
                safe_message="资源目录每页数量必须在 1 到 50 之间",
                error_code="mcp_resource_directory_input_invalid",
            )
        addresses = self.resolver.list_published_addresses(resource_kind=selected_kind)
        visible: list[tuple[Any, tuple[str, ...]]] = []
        for address in addresses:
            usable_tools = tuple(
                sorted(
                    {
                        grant.tool_identifier
                        for grant in grants
                        if self._grant_matches(grant, address)
                    }
                )
            )
            if usable_tools:
                visible.append((address, usable_tools))
        ambiguity_counts: dict[tuple[str, str, str, str, str], int] = {}
        target_counts: dict[tuple[str, str, str, str], int] = {}
        for address, _ in visible:
            ambiguity_counts[address.resolution_key] = (
                ambiguity_counts.get(address.resolution_key, 0) + 1
            )
            target = address.resolution_key[:-1]
            target_counts[target] = target_counts.get(target, 0) + 1
        items = [
            {
                "resource_code": address.resource_code,
                "resource_kind": address.resource_kind,
                "environment": address.environment,
                "base": address.base or None,
                "workshop": address.workshop or None,
                "placement": address.placement or None,
                "resource_revision_id": address.resource_revision_id,
                "resource_revision": address.resource_revision,
                "resolution_status": (
                    "AMBIGUOUS"
                    if ambiguity_counts[address.resolution_key] > 1
                    or (not address.placement and target_counts[address.resolution_key[:-1]] > 1)
                    else "AVAILABLE"
                ),
                "usable_tools": list(usable_tools),
                "_sort_key": list(address.sort_key),
                "_content_hash": address.resource_content_hash,
            }
            for address, usable_tools in visible
            if not normalized_query
            or normalized_query
            in " ".join(
                (
                    address.resource_code,
                    address.resource_kind,
                    address.environment,
                    address.base,
                    address.workshop,
                    address.placement,
                )
            ).casefold()
        ]
        state_fingerprint = ToolPaginationCursorCodec.fingerprint(
            [
                {
                    "sort_key": item["_sort_key"],
                    "content_hash": item["_content_hash"],
                    "usable_tools": item["usable_tools"],
                    "resolution_status": item["resolution_status"],
                }
                for item in items
            ]
        )
        request = {"resource_kind": selected_kind, "query": normalized_query}
        after: tuple[str, ...] = ()
        if cursor:
            position = ToolPaginationCursorCodec.decode(
                cursor,
                context=context,
                purpose="resource-directory",
                request=request,
                state_fingerprint=state_fingerprint,
            )
            if (
                not isinstance(position, list)
                or len(position) != 7
                or any(not isinstance(value, str) for value in position)
            ):
                raise ToolPaginationCursorCodec._invalid(
                    "Resource directory cursor position is invalid"
                )
            after = tuple(position)
        remaining = [item for item in items if tuple(item["_sort_key"]) > after]
        has_more = len(remaining) > page_limit
        page = remaining[:page_limit]
        next_cursor = ""
        if has_more and page:
            next_cursor = ToolPaginationCursorCodec.encode(
                context=context,
                purpose="resource-directory",
                request=request,
                state_fingerprint=state_fingerprint,
                position=page[-1]["_sort_key"],
            )
        returned = [
            {key: value for key, value in item.items() if not key.startswith("_")} for item in page
        ]
        return ToolResult(
            summary={
                "resources": returned,
                "resource_count": len(returned),
                "has_more": has_more,
                "next_cursor": next_cursor,
                "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "diagnostic_action": (
                    "use_available_targets_only"
                    if returned
                    else "stop_and_report_no_authorized_resources"
                ),
            },
            raw={"resource_count": len(returned)},
            metadata={
                "source": "tool-mcp-authorized-resource-directory",
                "returned_resources": [
                    {
                        "resource_code": item["resource_code"],
                        "resource_revision_id": item["resource_revision_id"],
                    }
                    for item in returned
                ],
            },
            truncated=has_more,
        )

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
        cursor: str = "",
    ) -> ToolResult:
        resource = self._resolve("database", environment, base, workshop, placement)
        page_limit = int(limit or 50)
        if not 1 <= page_limit <= 50:
            raise ToolPolicyError(
                "Schema directory limit is invalid",
                safe_message="Schema 目录每页数量必须在 1 到 50 之间",
                error_code="mcp_schema_directory_input_invalid",
            )
        request = {
            "environment": environment,
            "base": base,
            "workshop": workshop or "",
            "placement": placement or "",
            "query": str(query or "").strip(),
        }
        state_fingerprint = ToolPaginationCursorCodec.fingerprint(
            {
                "resource_revision_id": resource.resource_revision_id,
                "resource_content_hash": resource.resource_content_hash,
            }
        )
        after_table = ""
        if cursor:
            position = ToolPaginationCursorCodec.decode(
                cursor,
                context=context,
                purpose="schema-directory",
                request=request,
                state_fingerprint=state_fingerprint,
            )
            if not isinstance(position, str) or not position:
                raise ToolPolicyError(
                    "Schema directory cursor position is invalid",
                    safe_message="分页游标无效，请从第一页重新查询",
                    error_code="mcp_pagination_cursor_invalid",
                )
            after_table = position
        directory = self.schema_inspectors.for_engine(resource.binding.engine).read(
            resource.binding,
            table_prefix=resource.table_prefix or None,
            query=query,
            table_limit=page_limit,
            column_limit=80,
            after_table=after_table,
        )
        next_cursor = ""
        if directory.has_more_tables and directory.tables:
            next_cursor = ToolPaginationCursorCodec.encode(
                context=context,
                purpose="schema-directory",
                request=request,
                state_fingerprint=state_fingerprint,
                position=directory.tables[-1].name,
            )
        summary = {
            "environment": resource.binding.environment.code,
            "base": base or None,
            "workshop": workshop or None,
            "engine": resource.binding.engine.value,
            **directory.to_summary(),
            "next_cursor": next_cursor,
            "diagnostic_action": (
                "use_listed_tables_and_columns_only"
                if directory.tables
                else "stop_and_report_insufficient_evidence"
            ),
        }
        return self._result(
            resource,
            summary,
            truncated=directory.has_more_tables or directory.columns_truncated,
        )

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
        resource = self._resolve("database", environment or "", base or "", workshop, placement)
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
            table_prefix=resource.table_prefix or None,
            allowed_database=allowed_database,
            allowed_schema=allowed_schema,
            oracle_compat=database.oracle_compat,
        )
        directory = self.schema_inspectors.for_engine(binding.engine).read(
            binding,
            table_prefix=resource.table_prefix or None,
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
        enforce_key_namespace(
            key,
            key_prefixes=resource.redis_namespace_prefixes,
        )
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
        cursor: str = "",
    ) -> ToolResult:
        del datasource
        assert_read_command("scan")
        bounded = max(1, min(int(limit), self.limits.redis_scan_limit))
        resource = self._resolve("redis", environment or "", base or "", workshop, placement)
        normalized = enforce_scan_pattern(
            pattern,
            key_prefixes=resource.redis_namespace_prefixes,
            scan_limit=self.limits.redis_scan_limit,
            limit=bounded,
        )
        request = {
            "environment": environment or "",
            "base": base or "",
            "workshop": workshop or "",
            "placement": placement or "",
            "pattern": normalized,
            "limit": bounded,
        }
        state_fingerprint = ToolPaginationCursorCodec.fingerprint(
            {
                "resource_revision_id": resource.resource_revision_id,
                "resource_content_hash": resource.resource_content_hash,
            }
        )
        provider_cursor: object = 0
        if cursor:
            provider_cursor = ToolPaginationCursorCodec.decode(
                cursor,
                context=context,
                purpose="redis-scan",
                request=request,
                state_fingerprint=state_fingerprint,
            )
            if not self._valid_redis_provider_cursor(provider_cursor):
                raise ToolPolicyError(
                    "Redis pagination cursor position is invalid",
                    safe_message="分页游标无效，请从第一页重新查询",
                    error_code="mcp_pagination_cursor_invalid",
                )
        response = self.redis.scan(
            resource.binding,
            normalized,
            bounded,
            provider_cursor,
        )
        response_metadata = getattr(response, "metadata", {})
        next_provider_cursor = (
            response_metadata.get("next_provider_cursor", 0)
            if isinstance(response_metadata, dict)
            else 0
        )
        has_more = not self._redis_provider_cursor_complete(next_provider_cursor)
        next_cursor = ""
        if has_more:
            if not self._valid_redis_provider_cursor(next_provider_cursor):
                raise ToolPolicyError(
                    "Redis provider returned an invalid pagination cursor",
                    safe_message="Redis 返回了无效分页状态",
                    error_code="mcp_redis_cursor_invalid",
                )
            next_cursor = ToolPaginationCursorCodec.encode(
                context=context,
                purpose="redis-scan",
                request=request,
                state_fingerprint=state_fingerprint,
                position=next_provider_cursor,
            )
        return self._result(
            resource,
            {
                **response.summary,
                "has_more": has_more,
                "next_cursor": next_cursor,
            },
            raw=response.raw,
            truncated=has_more or response.truncated,
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
        effective = build_effective_selector(
            selector,
            mandatory_conditions=resource.loki_selector_conditions,
            require_mandatory=True,
        )
        response = self._loki(resource).query(
            resource.binding,
            selector=effective,
            query=query,
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(
            resource, response.summary, raw=response.raw, truncated=response.truncated
        )

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
        effective = build_effective_selector(
            {}, mandatory_conditions=resource.loki_selector_conditions, require_mandatory=True
        )
        response = self._loki(resource).labels(
            resource.binding,
            selector=effective,
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(
            resource, response.summary, raw=response.raw, truncated=response.truncated
        )

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
        assert_loki_label(label)
        resource = self._resolve("loki", environment, base, workshop, None)
        effective = build_effective_selector(
            {}, mandatory_conditions=resource.loki_selector_conditions, require_mandatory=True
        )
        response = self._loki(resource).label_values(
            resource.binding,
            label=label,
            selector=effective,
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(
            resource, response.summary, raw=response.raw, truncated=response.truncated
        )

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
        effective = build_effective_selector(
            selector,
            mandatory_conditions=resource.loki_selector_conditions,
            require_mandatory=True,
        )
        response = self._loki(resource).probe(
            resource.binding,
            selector=effective,
            query=query,
            minutes=int(minutes),
            limit=int(limit),
        )
        return self._result(
            resource, response.summary, raw=response.raw, truncated=response.truncated
        )

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

    @staticmethod
    def _grant_matches(grant: ResourceAccessGrant, address: Any) -> bool:
        if grant.resource_kind != address.resource_kind:
            return False
        if grant.unrestricted:
            return True
        if grant.environment != address.environment:
            return False
        if grant.base and grant.base != address.base:
            return False
        if grant.workshop and grant.workshop != address.workshop:
            return False
        return True

    @staticmethod
    def _valid_redis_provider_cursor(value: object) -> bool:
        return valid_scan_position(value)

    @staticmethod
    def _redis_provider_cursor_complete(value: object) -> bool:
        return scan_complete(value)

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
                "scope_target": {
                    "environment": resource.scope_target[0],
                    "base": resource.scope_target[1] or None,
                    "workshop": resource.scope_target[2] or None,
                },
                "scope_kind": (
                    "table_prefix"
                    if resource.table_prefix
                    else "redis_namespace"
                    if resource.redis_namespace_prefixes
                    else "loki_selector"
                    if resource.loki_selector_conditions
                    else "unpartitioned"
                ),
            },
            truncated=truncated,
        )
