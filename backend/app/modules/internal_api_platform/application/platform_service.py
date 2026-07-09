from __future__ import annotations

import logging
from typing import Any

from ..domain.access import AccessPolicy
from ..domain.addressing import ResourceBinding, TargetRef
from ..domain.errors import PlatformError, PolicyViolation
from ..domain.loki_policy import assert_loki_label_allowed, build_effective_selector
from ..domain.redis_policy import (
    assert_read_command,
    enforce_key_namespace,
    enforce_scan_pattern,
)
from ..domain.results import ToolResponse
from ..domain.schema_directory import SchemaDirectory
from ..domain.sql.analyzer import analyze_readonly_query
from ..domain.topology import DatabaseEngine, OracleCompat, ResourceKind
from ..infrastructure.db.executor import QueryExecutor
from ..infrastructure.db.schema_directory import SchemaInspectorFactory
from ..infrastructure.loki_gateway import LokiClient
from ..infrastructure.redis_gateway import RedisGateway
from ..infrastructure.registry import TopologyRegistry

_audit_logger = logging.getLogger("internal_api_platform.audit")


class PlatformService:
    def __init__(
        self,
        *,
        registry: TopologyRegistry,
        access_policy: AccessPolicy,
        executors: dict[DatabaseEngine, QueryExecutor],
        schema_inspector_factory: SchemaInspectorFactory | None = None,
        redis_gateway: RedisGateway,
        loki_client: LokiClient,
        max_rows: int = 100,
        query_timeout_seconds: int = 15,
        redis_scan_limit: int = 200,
        schema_table_limit: int = 50,
        schema_column_limit: int = 80,
        config_source: str = "unknown",
        config_revision: int = 0,
        config_hash: str = "",
        config_errors: list[str] | None = None,
        config_resource_count: int = 0,
    ) -> None:
        self._registry = registry
        self._access = access_policy
        self._executors = executors
        self._schema_inspectors = schema_inspector_factory or SchemaInspectorFactory()
        self._redis = redis_gateway
        self._loki = loki_client
        self._max_rows = max_rows
        self._query_timeout_seconds = query_timeout_seconds
        self._redis_scan_limit = redis_scan_limit
        self._schema_table_limit = schema_table_limit
        self._schema_column_limit = schema_column_limit
        self._config_source = config_source
        self._config_revision = config_revision
        self._config_hash = config_hash
        self._config_errors = config_errors or []
        self._config_resource_count = config_resource_count

    def config_status(self) -> dict[str, Any]:
        return {
            "source": self._config_source,
            "revision": self._config_revision,
            "config_hash": self._config_hash,
            "valid": not self._config_errors,
            "errors": self._config_errors,
            "resource_count": self._config_resource_count,
        }

    def _authorize_and_resolve(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        kind: ResourceKind,
    ) -> ResourceBinding:
        target = TargetRef(environment=environment, base=base, kind=kind, workshop=workshop)
        try:
            self._access.authorize(user_id=user_id, target=target)
        except PlatformError as exc:
            self._audit(user_id, target, "deny", exc.code)
            raise
        try:
            binding = self._registry.resolve(target)
        except PlatformError as exc:
            self._audit(user_id, target, "deny", exc.code)
            raise
        self._audit(user_id, target, "allow", "ok")
        return binding

    def topology_directory(self, *, user_id: str) -> dict[str, Any]:
        """Non-secret addressing directory filtered to what the caller may access.

        Lets the model map natural language (观澜 / GL001) to environment/base/workshop
        codes without ever exposing connection details.
        """

        environments: list[dict[str, Any]] = []
        for environment in self._registry.topology.environments.values():
            bases: list[dict[str, Any]] = []
            for base in environment.bases.values():
                if base.is_partitioned:
                    workshops = [
                        self._workshop_entry(ws)
                        for ws in base.workshops.values()
                        if self._can_access(user_id, environment.code, base.code, ws.code)
                    ]
                    if not workshops:
                        continue
                    bases.append(self._base_entry(base, workshops))
                else:
                    if not self._can_access(user_id, environment.code, base.code, None):
                        continue
                    bases.append(self._base_entry(base, []))
            if bases:
                environments.append(
                    {
                        "code": environment.code,
                        "display_name": environment.display_name,
                        "aliases": list(environment.aliases),
                        "bases": bases,
                    }
                )
        return {"environments": environments}

    def er_context(self, *, user_id: str, query: str) -> ToolResponse:
        return ToolResponse(
            summary={
                "source": "internal-platform-er",
                "query": query,
                "addressing": self.topology_directory(user_id=user_id),
                "tables": [],
                "fields": [],
                "relationships": [],
                "note": (
                    "Resolve environment/base/workshop from 'addressing' before calling "
                    "data tools. ER graph is not connected yet."
                ),
            },
            metadata={"source": "internal-api-platform"},
        )

    def business_flow_context(self, *, user_id: str, query: str) -> ToolResponse:
        return ToolResponse(
            summary={
                "source": "internal-platform-business-flow",
                "query": query,
                "addressing": self.topology_directory(user_id=user_id),
                "nodes": [],
                "edges": [],
                "note": (
                    "Resolve environment/base/workshop from 'addressing' before calling "
                    "data tools. Business-flow graph is not connected yet."
                ),
            },
            metadata={"source": "internal-api-platform"},
        )

    def _can_access(self, user_id: str, environment: str, base: str, workshop: str | None) -> bool:
        target = TargetRef(
            environment=environment,
            base=base,
            kind=ResourceKind.DATABASE,
            workshop=workshop,
        )
        return self._access.allows(user_id=user_id, target=target)

    @staticmethod
    def _base_entry(base: Any, workshops: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "code": base.code,
            "display_name": base.display_name,
            "aliases": list(base.aliases),
            "engine": base.engine.value,
            "partitioned": base.is_partitioned,
            "workshops": workshops,
        }

    @staticmethod
    def _workshop_entry(workshop: Any) -> dict[str, Any]:
        return {
            "code": workshop.code,
            "display_name": workshop.display_name,
            "aliases": list(workshop.aliases),
        }

    def describe_target(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        kind: ResourceKind,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id, environment=environment, base=base, workshop=workshop, kind=kind
        )
        return ToolResponse(
            summary={
                "environment": binding.environment.code,
                "base": binding.base.code,
                "workshop": binding.workshop.code if binding.workshop else None,
                "kind": binding.kind.value,
                "engine": binding.engine.value,
                "partitioned": binding.base.is_partitioned,
            },
            metadata={"source": "internal-api-platform"},
        )

    def query_database(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        sql: str,
        limit: int | None = None,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.DATABASE,
        )
        max_rows = self._effective_rows(limit)
        table_prefix = binding.workshop.table_prefix if binding.workshop else None
        oracle_compat = OracleCompat.MODERN
        if binding.database is not None:
            oracle_compat = getattr(binding.database, "oracle_compat", OracleCompat.MODERN)
        analyzed = analyze_readonly_query(
            sql,
            engine=binding.engine,
            max_rows=max_rows,
            table_prefix=table_prefix,
            oracle_compat=oracle_compat,
        )
        schema = self._schema_directory_for_binding(binding, query="")
        if schema is not None:
            self._assert_tables_in_schema(analyzed.tables, schema)
        executor = self._executors.get(binding.engine)
        if executor is None:
            raise PolicyViolation(f"No executor configured for engine {binding.engine.value}")
        executed = executor.execute(
            binding,
            analyzed.sql,
            timeout_seconds=self._query_timeout_seconds,
            max_rows=max_rows,
        )
        return ToolResponse(
            summary={
                "engine": binding.engine.value,
                "tables": analyzed.tables,
                "row_count": len(executed.rows),
                "columns": executed.columns,
                "rows": executed.rows,
                "executed_sql": analyzed.sql,
            },
            raw={"row_count": len(executed.rows)},
            truncated=executed.truncated,
            metadata={"source": "internal-api-platform-db"},
        )

    def schema_directory(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        query: str = "",
        limit: int | None = None,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.DATABASE,
        )
        table_limit = self._effective_schema_limit(limit)
        schema = self._schema_directory_for_binding(binding, query=query, table_limit=table_limit)
        if schema is None:
            schema = SchemaDirectory(
                tables=[],
                limitation=f"Schema directory is not configured for {binding.engine.value}",
            )
        summary = {
            "environment": binding.environment.code,
            "base": binding.base.code,
            "workshop": binding.workshop.code if binding.workshop else None,
            "engine": binding.engine.value,
            **schema.to_summary(),
            "diagnostic_action": (
                "use_listed_tables_and_columns_only"
                if schema.tables
                else "stop_and_report_insufficient_evidence"
            ),
        }
        return ToolResponse(
            summary=summary,
            raw={"table_count": len(schema.tables)},
            truncated=schema.truncated,
            metadata={"source": "internal-api-platform-schema"},
        )

    def redis_get(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        key: str,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.REDIS,
        )
        assert_read_command("get")
        enforce_key_namespace(key, key_prefix=self._redis_prefix(binding))
        response = self._redis.get(binding, key)
        response.metadata.setdefault("source", "internal-api-platform-redis")
        return response

    def redis_scan(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        pattern: str,
        limit: int | None = None,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.REDIS,
        )
        assert_read_command("scan")
        effective_limit = limit or self._redis_scan_limit
        enforce_scan_pattern(
            pattern,
            key_prefix=self._redis_prefix(binding),
            scan_limit=self._redis_scan_limit,
            limit=effective_limit,
        )
        response = self._redis.scan(binding, pattern, effective_limit)
        response.metadata.setdefault("source", "internal-api-platform-redis")
        return response

    def query_loki(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
        )
        effective_selector = build_effective_selector(selector, workshop=binding.workshop)
        response = self._loki.query(
            binding,
            selector=effective_selector,
            query=query,
            minutes=minutes,
            limit=limit,
        )
        response.metadata.setdefault("source", "internal-api-platform-loki")
        return response

    def loki_labels(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
        )
        response = self._loki.labels(
            binding,
            selector=self._diagnostic_selector(binding),
            minutes=minutes,
            limit=limit,
        )
        response.metadata.setdefault("source", "internal-api-platform-loki-diagnostics")
        return response

    def loki_label_values(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        label: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        assert_loki_label_allowed(label)
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
        )
        response = self._loki.label_values(
            binding,
            label=label,
            selector=self._diagnostic_selector(binding),
            minutes=minutes,
            limit=limit,
        )
        response.metadata.setdefault("source", "internal-api-platform-loki-diagnostics")
        return response

    def loki_probe(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
        )
        effective_selector = build_effective_selector(selector, workshop=binding.workshop)
        response = self._loki.probe(
            binding,
            selector=effective_selector,
            query=query,
            minutes=minutes,
            limit=limit,
        )
        response.metadata.setdefault("source", "internal-api-platform-loki-diagnostics")
        return response

    def _redis_prefix(self, binding: ResourceBinding) -> str | None:
        return binding.workshop.redis_key_prefix if binding.workshop else None

    @staticmethod
    def _diagnostic_selector(binding: ResourceBinding) -> dict[str, str]:
        return dict(binding.workshop.loki_label) if binding.workshop else {}

    def _effective_rows(self, limit: int | None) -> int:
        if limit is None or limit < 1:
            return self._max_rows
        return min(limit, self._max_rows)

    def _effective_schema_limit(self, limit: int | None) -> int:
        if limit is None or limit < 1:
            return self._schema_table_limit
        return min(limit, self._schema_table_limit)

    def _schema_directory_for_binding(
        self,
        binding: ResourceBinding,
        *,
        query: str,
        table_limit: int | None = None,
    ) -> SchemaDirectory | None:
        inspector = self._schema_inspectors.for_engine(binding.engine)
        table_prefix = binding.workshop.table_prefix if binding.workshop else None
        return inspector.read(
            binding,
            table_prefix=table_prefix,
            query=query,
            table_limit=table_limit or self._schema_table_limit,
            column_limit=self._schema_column_limit,
        )

    def _assert_tables_in_schema(self, tables: list[str], schema: SchemaDirectory) -> None:
        if not schema.tables:
            raise PolicyViolation(
                "Schema directory is empty for the target",
                diagnostic_action="stop_and_report_insufficient_evidence",
            )
        known = {name.lower() for name in schema.table_names()}
        for table in tables:
            if table.lower() not in known:
                raise PolicyViolation(
                    f"Table '{table}' is not available in the target schema directory",
                    diagnostic_action="stop_or_use_schema_directory",
                )

    def _audit(self, user_id: str, target: TargetRef, decision: str, reason: str) -> None:
        _audit_logger.info(
            "platform_access",
            extra={
                "platform_user": user_id or "-",
                "platform_environment": target.environment,
                "platform_base": target.base,
                "platform_workshop": target.workshop or "-",
                "platform_kind": target.kind.value,
                "platform_decision": decision,
                "platform_reason": reason,
            },
        )
