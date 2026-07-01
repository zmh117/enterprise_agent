from __future__ import annotations

import logging

from ..domain.access import AccessPolicy
from ..domain.addressing import ResourceBinding, TargetRef
from ..domain.errors import PlatformError, PolicyViolation
from ..domain.loki_policy import build_effective_selector
from ..domain.redis_policy import (
    assert_read_command,
    enforce_key_namespace,
    enforce_scan_pattern,
)
from ..domain.results import ToolResponse
from ..domain.sql.analyzer import analyze_readonly_query
from ..domain.topology import DatabaseEngine, ResourceKind
from ..infrastructure.db.executor import QueryExecutor
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
        redis_gateway: RedisGateway,
        loki_client: LokiClient,
        max_rows: int = 100,
        query_timeout_seconds: int = 15,
        redis_scan_limit: int = 200,
    ) -> None:
        self._registry = registry
        self._access = access_policy
        self._executors = executors
        self._redis = redis_gateway
        self._loki = loki_client
        self._max_rows = max_rows
        self._query_timeout_seconds = query_timeout_seconds
        self._redis_scan_limit = redis_scan_limit

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
        analyzed = analyze_readonly_query(
            sql, engine=binding.engine, max_rows=max_rows, table_prefix=table_prefix
        )
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

    def _redis_prefix(self, binding: ResourceBinding) -> str | None:
        return binding.workshop.redis_key_prefix if binding.workshop else None

    def _effective_rows(self, limit: int | None) -> int:
        if limit is None or limit < 1:
            return self._max_rows
        return min(limit, self._max_rows)

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
