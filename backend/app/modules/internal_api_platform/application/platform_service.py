from __future__ import annotations

from dataclasses import replace
import json
import logging
from typing import Any

from ..domain.access import AccessPolicy
from ..domain.addressing import (
    LokiScopePolicyFact,
    ResourceBinding,
    TargetRef,
    WorkshopPartitionPolicyFact,
)
from ..domain.errors import (
    AuthorizationError,
    PlatformError,
    PolicyViolation,
    ResolutionError,
)
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
from .job_authorization import AuthorizedJobContext, JobAccessAuthorizer
from app.modules.platform_config.application.secret_reload import (
    SecretChangeReloader,
)
from app.modules.platform_config.application.runtime_generation import (
    PublishedRuntimeGenerationReloader,
)
from app.modules.platform_config.application.snapshot import (
    RuntimeTopologySnapshot,
)

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
        max_response_bytes: int = 1024 * 1024,
        redis_scan_limit: int = 200,
        schema_table_limit: int = 50,
        schema_column_limit: int = 80,
        config_source: str = "unknown",
        config_revision: int = 0,
        config_hash: str = "",
        config_errors: list[str] | None = None,
        config_resource_count: int = 0,
        job_access_authorizer: JobAccessAuthorizer | None = None,
        secret_change_reloader: SecretChangeReloader | None = None,
        runtime_generation_reloader: (PublishedRuntimeGenerationReloader | None) = None,
    ) -> None:
        self._registry = registry
        self._access = access_policy
        self._effective_runtime = (registry.capture(), access_policy)
        self._executors = executors
        self._schema_inspectors = schema_inspector_factory or SchemaInspectorFactory()
        self._redis = redis_gateway
        self._loki = loki_client
        self._max_rows = max_rows
        self._query_timeout_seconds = query_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._redis_scan_limit = redis_scan_limit
        self._schema_table_limit = schema_table_limit
        self._schema_column_limit = schema_column_limit
        self._config_source = config_source
        self._config_revision = config_revision
        self._config_hash = config_hash
        self._config_errors = config_errors or []
        self._config_resource_count = config_resource_count
        self._job_access_authorizer = job_access_authorizer
        self._secret_change_reloader = secret_change_reloader
        self._runtime_generation_reloader = runtime_generation_reloader
        self._last_known_good = {
            "source": config_source,
            "revision": config_revision,
            "config_hash": config_hash,
            "resource_count": config_resource_count,
        }
        self._reload_degraded = False
        self._active_snapshot = RuntimeTopologySnapshot(
            topology=registry.topology,
            access_policy=access_policy,
            source=config_source,
            revision=config_revision,
            config_hash=config_hash,
            resource_count=config_resource_count,
            errors=list(config_errors or []),
        )

    def config_status(self) -> dict[str, Any]:
        return {
            "source": self._config_source,
            "revision": self._config_revision,
            "config_hash": self._config_hash,
            "valid": not self._config_errors,
            "errors": self._config_errors,
            "resource_count": self._config_resource_count,
            "degraded": self._reload_degraded,
            "last_known_good": dict(self._last_known_good),
            "generation": {
                "id": self._active_snapshot.generation_id,
                "number": self._active_snapshot.generation_no,
                "published_digest": self._active_snapshot.published_digest,
                "effective_digest": self._active_snapshot.effective_digest,
            },
            "resource_states": [dict(value) for value in self._active_snapshot.resource_states],
            "application_states": [
                dict(value) for value in self._active_snapshot.application_states
            ],
        }

    def capture_runtime_snapshot(self) -> RuntimeTopologySnapshot:
        """Capture the exact immutable generation used by one request."""

        return self._active_snapshot

    def close(self) -> None:
        if self._secret_change_reloader is not None:
            self._secret_change_reloader.close()
        if self._runtime_generation_reloader is not None:
            self._runtime_generation_reloader.close()
        if self._job_access_authorizer is not None:
            self._job_access_authorizer.close()

    def attach_secret_change_reloader(
        self,
        reloader: SecretChangeReloader,
    ) -> None:
        self._secret_change_reloader = reloader

    def poll_secret_changes(self) -> dict[str, int]:
        if self._secret_change_reloader is None:
            return {"claimed": 0, "succeeded": 0, "failed": 0}
        return self._secret_change_reloader.poll_once()

    def attach_runtime_generation_reloader(
        self,
        reloader: PublishedRuntimeGenerationReloader,
    ) -> None:
        self._runtime_generation_reloader = reloader

    def poll_runtime_generation(self) -> dict[str, Any]:
        if self._runtime_generation_reloader is None:
            return {
                "observed": False,
                "activated": False,
                "retained_lkg": False,
            }
        result = self._runtime_generation_reloader.poll_once()
        return {
            "observed": result.observed,
            "activated": result.activated,
            "retained_lkg": result.retained_lkg,
            "generation_id": result.generation_id,
            "generation_no": result.generation_no,
            "published_digest": result.published_digest,
            "error_code": result.error_code,
        }

    def apply_runtime_snapshot(
        self,
        snapshot: RuntimeTopologySnapshot,
    ) -> bool:
        if not snapshot.valid or snapshot.source == "database-invalid":
            self._reload_degraded = True
            self._config_errors = ["相关资源凭据重载失败，继续使用 Last Known Good"]
            return False
        registry_generation = self._registry.replace(
            snapshot.topology,
            revision_resources=snapshot.revision_resources,
        )
        self._access = snapshot.access_policy
        self._effective_runtime = (
            registry_generation,
            snapshot.access_policy,
        )
        self._active_snapshot = snapshot
        self._config_source = snapshot.source
        self._config_revision = snapshot.revision
        self._config_hash = snapshot.config_hash
        self._config_resource_count = snapshot.resource_count
        self._config_errors = []
        self._reload_degraded = False
        self._last_known_good = {
            "source": snapshot.source,
            "revision": snapshot.revision,
            "config_hash": snapshot.config_hash,
            "resource_count": snapshot.resource_count,
        }
        return True

    def _authorize_and_resolve(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        kind: ResourceKind,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        capability_code: str = "",
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ResourceBinding:
        target = TargetRef(environment=environment, base=base, kind=kind, workshop=workshop)
        registry_generation, access_policy = self._effective_runtime
        try:
            authorized = self._authorize_target(
                user_id=user_id,
                job_id=job_id,
                project_code=project_code,
                application_id=application_id,
                capability_code=capability_code,
                target=target,
                access_policy=access_policy,
                placement=placement,
                tool_call_id=tool_call_id,
                correlation_id=correlation_id,
            )
        except PlatformError as exc:
            self._audit(user_id, target, "deny", exc.code)
            raise
        try:
            if (
                isinstance(authorized, AuthorizedJobContext)
                and authorized.schema_version >= 2
            ):
                if authorized.schema_version >= 3:
                    revision = registry_generation.revision_resources.get(
                        authorized.resource_revision_id
                    )
                    if (
                        revision is None
                        or revision.resource_revision_id
                        != authorized.resource_revision_id
                    ):
                        raise ResolutionError(
                            "Frozen Resource Revision is not loaded exactly"
                        )
                binding = self._registry.resolve_revision(
                    target,
                    resource_revision_id=authorized.resource_revision_id,
                    generation=registry_generation,
                )
            else:
                binding = self._registry.resolve(
                    target,
                    generation=registry_generation,
                )
            if (
                kind is ResourceKind.LOKI
                and isinstance(authorized, AuthorizedJobContext)
                and authorized.loki_scope_policy_revision_id
            ):
                binding = replace(
                    binding,
                    loki_scope_policy=LokiScopePolicyFact(
                        policy_revision_id=authorized.loki_scope_policy_revision_id,
                        content_hash=authorized.loki_scope_policy_content_hash,
                        conditions=authorized.loki_scope_conditions,
                    ),
                )
            if (
                isinstance(authorized, AuthorizedJobContext)
                and authorized.workshop_partition_policy_revision_id
            ):
                binding = replace(
                    binding,
                    workshop_partition_policy=(
                        WorkshopPartitionPolicyFact(
                            policy_revision_id=(
                                authorized.workshop_partition_policy_revision_id
                            ),
                            content_hash=(
                                authorized.workshop_partition_policy_content_hash
                            ),
                            database_table_prefix=(
                                authorized.database_table_prefix or None
                            ),
                            redis_prefixes=authorized.redis_prefixes,
                        )
                    ),
                )
        except PlatformError as exc:
            self._audit(user_id, target, "deny", exc.code)
            raise
        self._audit(user_id, target, "allow", "ok")
        return binding

    def _authorize_target(
        self,
        *,
        user_id: str,
        job_id: str,
        project_code: str,
        application_id: str,
        capability_code: str,
        target: TargetRef,
        access_policy: AccessPolicy | None = None,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> AuthorizedJobContext | None:
        if self._job_access_authorizer is not None and capability_code:
            if not job_id:
                raise AuthorizationError("Agent Job authorization context is invalid")
            return self._job_access_authorizer.authorize(
                job_id=job_id,
                user_id=user_id,
                project_code=project_code,
                application_id=application_id,
                capability_code=capability_code,
                target=target,
                placement=placement,
                tool_call_id=tool_call_id,
                correlation_id=correlation_id,
            )
        (access_policy or self._access).authorize(
            user_id=user_id,
            target=target,
        )
        return None

    def topology_directory(
        self,
        *,
        user_id: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        capability_code: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> dict[str, Any]:
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
                        if self._can_access(
                            user_id,
                            environment.code,
                            base.code,
                            ws.code,
                            job_id=job_id,
                            project_code=project_code,
                            application_id=application_id,
                            capability_code=capability_code,
                            tool_call_id=tool_call_id,
                            correlation_id=correlation_id,
                        )
                    ]
                    if not workshops:
                        continue
                    bases.append(self._base_entry(base, workshops))
                else:
                    if not self._can_access(
                        user_id,
                        environment.code,
                        base.code,
                        None,
                        job_id=job_id,
                        project_code=project_code,
                        application_id=application_id,
                        capability_code=capability_code,
                        tool_call_id=tool_call_id,
                        correlation_id=correlation_id,
                    ):
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
        if self._job_access_authorizer is not None and capability_code and not environments:
            raise AuthorizationError("Agent Job authorization context is invalid")
        return {"environments": environments}

    def er_context(
        self,
        *,
        user_id: str,
        query: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        return ToolResponse(
            summary={
                "source": "internal-platform-er",
                "query": query,
                "addressing": self.topology_directory(
                    user_id=user_id,
                    job_id=job_id,
                    project_code=project_code,
                    application_id=application_id,
                    capability_code="get_er_context",
                    tool_call_id=tool_call_id,
                    correlation_id=correlation_id,
                ),
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

    def business_flow_context(
        self,
        *,
        user_id: str,
        query: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        return ToolResponse(
            summary={
                "source": "internal-platform-business-flow",
                "query": query,
                "addressing": self.topology_directory(
                    user_id=user_id,
                    job_id=job_id,
                    project_code=project_code,
                    application_id=application_id,
                    capability_code="get_business_flow_context",
                    tool_call_id=tool_call_id,
                    correlation_id=correlation_id,
                ),
                "nodes": [],
                "edges": [],
                "note": (
                    "Resolve environment/base/workshop from 'addressing' before calling "
                    "data tools. Business-flow graph is not connected yet."
                ),
            },
            metadata={"source": "internal-api-platform"},
        )

    def _can_access(
        self,
        user_id: str,
        environment: str,
        base: str,
        workshop: str | None,
        *,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        capability_code: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> bool:
        target = TargetRef(
            environment=environment,
            base=base,
            kind=ResourceKind.DATABASE,
            workshop=workshop,
        )
        try:
            self._authorize_target(
                user_id=user_id,
                job_id=job_id,
                project_code=project_code,
                application_id=application_id,
                capability_code=capability_code,
                target=target,
                tool_call_id=tool_call_id,
                correlation_id=correlation_id,
            )
        except PlatformError:
            return False
        return True

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
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        kind: ResourceKind,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=kind,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="get_schema_directory",
            placement=placement,
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
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
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        sql: str,
        limit: int | None = None,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.DATABASE,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="query_database",
            placement=placement,
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
        )
        max_rows = self._effective_rows(limit)
        table_prefix = self._database_table_prefix(binding)
        oracle_compat = OracleCompat.MODERN
        if binding.database is not None:
            oracle_compat = getattr(binding.database, "oracle_compat", OracleCompat.MODERN)
        allowed_database, allowed_schema = self._database_namespace(binding)
        analyzed = analyze_readonly_query(
            sql,
            engine=binding.engine,
            max_rows=max_rows,
            table_prefix=table_prefix,
            allowed_database=allowed_database,
            allowed_schema=allowed_schema,
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
        executed = self._bound_database_response(executed)
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

    def _bound_database_response(self, executed: Any) -> Any:
        rows: list[dict[str, Any]] = []
        response_bytes = 0
        truncated = bool(executed.truncated)
        for row in executed.rows:
            encoded = json.dumps(
                row,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
            if response_bytes + len(encoded) > self._max_response_bytes:
                truncated = True
                break
            rows.append(row)
            response_bytes += len(encoded)
        executed.rows = rows
        executed.truncated = truncated
        executed.response_bytes = response_bytes
        return executed

    def schema_directory(
        self,
        *,
        user_id: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        query: str = "",
        limit: int | None = None,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.DATABASE,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="get_schema_directory",
            placement=placement,
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
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
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        key: str,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.REDIS,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="query_redis_get",
            placement=placement,
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
        )
        assert_read_command("get")
        enforce_key_namespace(key, key_prefixes=self._redis_prefixes(binding))
        response = self._redis.get(binding, key)
        response.metadata.setdefault("source", "internal-api-platform-redis")
        return response

    def redis_scan(
        self,
        *,
        user_id: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        pattern: str,
        limit: int | None = None,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.REDIS,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="query_redis_scan",
            placement=placement,
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
        )
        assert_read_command("scan")
        effective_limit = limit or self._redis_scan_limit
        normalized_pattern = enforce_scan_pattern(
            pattern,
            key_prefixes=self._redis_prefixes(binding),
            scan_limit=self._redis_scan_limit,
            limit=effective_limit,
        )
        response = self._redis.scan(binding, normalized_pattern, effective_limit)
        response.metadata.setdefault("source", "internal-api-platform-redis")
        return response

    def query_loki(
        self,
        *,
        user_id: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="query_loki",
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
        )
        effective_selector = self._loki_selector(
            binding,
            selector,
            require_mandatory=bool(job_id),
        )
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
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        minutes: int,
        limit: int,
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="diagnose_loki_labels",
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
        )
        response = self._loki.labels(
            binding,
            selector=self._mandatory_loki_selector(
                binding,
                require_mandatory=bool(job_id),
            ),
            minutes=minutes,
            limit=limit,
        )
        response.metadata.setdefault("source", "internal-api-platform-loki-diagnostics")
        return response

    def loki_label_values(
        self,
        *,
        user_id: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        label: str,
        minutes: int,
        limit: int,
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        assert_loki_label_allowed(label)
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="diagnose_loki_label_values",
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
        )
        response = self._loki.label_values(
            binding,
            label=label,
            selector=self._mandatory_loki_selector(
                binding,
                require_mandatory=bool(job_id),
            ),
            minutes=minutes,
            limit=limit,
        )
        response.metadata.setdefault("source", "internal-api-platform-loki-diagnostics")
        return response

    def loki_probe(
        self,
        *,
        user_id: str,
        job_id: str = "",
        project_code: str = "",
        application_id: str = "",
        environment: str,
        base: str,
        workshop: str | None,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        binding = self._authorize_and_resolve(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            kind=ResourceKind.LOKI,
            job_id=job_id,
            project_code=project_code,
            application_id=application_id,
            capability_code="diagnose_loki_probe",
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
        )
        effective_selector = self._loki_selector(
            binding,
            selector,
            require_mandatory=bool(job_id),
        )
        response = self._loki.probe(
            binding,
            selector=effective_selector,
            query=query,
            minutes=minutes,
            limit=limit,
        )
        response.metadata.setdefault("source", "internal-api-platform-loki-diagnostics")
        return response

    @staticmethod
    def _database_table_prefix(
        binding: ResourceBinding,
    ) -> str | None:
        if binding.workshop_partition_policy is not None:
            return (
                binding.workshop_partition_policy.database_table_prefix
            )
        if binding.workshop and binding.workshop.table_prefix:
            return binding.workshop.table_prefix
        return None

    @staticmethod
    def _redis_prefixes(binding: ResourceBinding) -> tuple[str, ...]:
        if binding.workshop_partition_policy is not None:
            return binding.workshop_partition_policy.redis_prefixes
        if binding.workshop and binding.workshop.redis_key_prefix:
            return (binding.workshop.redis_key_prefix,)
        return ()

    @staticmethod
    def _mandatory_loki_selector(
        binding: ResourceBinding,
        *,
        require_mandatory: bool,
    ) -> dict[str, str]:
        conditions = (
            binding.loki_scope_policy.conditions if binding.loki_scope_policy is not None else ()
        )
        if require_mandatory and not conditions:
            raise PolicyViolation("Published Loki Scope Policy is required")
        return dict(conditions)

    @staticmethod
    def _loki_selector(
        binding: ResourceBinding,
        selector: dict[str, str],
        *,
        require_mandatory: bool,
    ) -> dict[str, str]:
        return build_effective_selector(
            selector,
            mandatory_conditions=(
                binding.loki_scope_policy.conditions
                if binding.loki_scope_policy is not None
                else ()
            ),
            require_mandatory=require_mandatory,
        )

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

    @staticmethod
    def _database_namespace(
        binding: ResourceBinding,
    ) -> tuple[str | None, str | None]:
        database = binding.database
        if database is None:
            return None, None
        if binding.engine is DatabaseEngine.MYSQL:
            return str(database.database or "") or None, None
        if binding.engine is DatabaseEngine.SQLSERVER:
            return (
                str(database.database or "") or None,
                str(database.schema or "").strip() or "dbo",
            )
        return None, str(database.schema or database.user or "") or None

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
