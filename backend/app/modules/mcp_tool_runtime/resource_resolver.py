from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.modules.mcp_tool_runtime.domain.addressing import ResourceBinding
from app.modules.mcp_tool_runtime.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    LokiConnection,
    OracleClientMode,
    OracleCompat,
    RedisConnection,
    ResourceKind,
    Workshop,
)
from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.application.resource_scope_bindings import (
    select_resource_scope_binding,
)
from app.modules.platform_config.domain.provider_contracts import (
    CanonicalProviderDocument,
    ProviderContractRegistry,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, ToolPolicyError
from app.shared.resource_role import normalize_resource_role, RESOURCE_ROLE_MESSAGE


@dataclass(frozen=True, slots=True)
class ResolvedToolResource:
    resource_id: str
    resource_code: str
    resource_revision_id: str
    resource_content_hash: str
    placement: str
    table_prefix: str
    redis_namespace_prefixes: tuple[str, ...]
    loki_selector_conditions: tuple[tuple[str, str], ...]
    scope_target: tuple[str, str, str]
    binding: ResourceBinding


@dataclass(frozen=True, slots=True)
class PublishedToolResourceAddress:
    resource_id: str
    resource_code: str
    resource_kind: str
    resource_revision_id: str
    resource_revision: int
    resource_content_hash: str
    environment: str
    base: str
    workshop: str
    placement: str
    query_limits: dict[str, int] = field(default_factory=dict)

    @property
    def target(self) -> tuple[str, str, str]:
        return (self.environment, self.base, self.workshop)

    @property
    def resolution_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.resource_kind,
            self.environment,
            self.base,
            self.workshop,
            self.placement,
        )

    @property
    def sort_key(self) -> tuple[str, str, str, str, str, str, str]:
        return (*self.resolution_key, self.resource_code, self.resource_revision_id)


class DirectResourceResolver:
    """Resolve exactly one published Resource without an Application mapping table."""

    def __init__(
        self,
        database: Database,
        *,
        secret_provider: EncryptedDbSecretProvider,
        provider_contracts: ProviderContractRegistry | None = None,
    ) -> None:
        self.database = database
        self.secret_provider = secret_provider
        self.provider_contracts = provider_contracts or ProviderContractRegistry()

    def resolve(
        self,
        *,
        resource_kind: str,
        environment: str,
        base: str = "",
        workshop: str = "",
        placement: str = "",
    ) -> ResolvedToolResource:
        kind = str(resource_kind or "").strip().lower()
        environment = str(environment or "").strip()
        base = str(base or "").strip()
        workshop = str(workshop or "").strip()
        try:
            placement = normalize_resource_role(placement)
        except ValueError as exc:
            raise ToolPolicyError(
                "Invalid MCP Resource role", safe_message=RESOURCE_ROLE_MESSAGE,
                error_code="mcp_resource_placement_invalid",
            ) from exc
        if kind not in {"database", "redis", "loki"}:
            raise ToolPolicyError(
                f"Unsupported MCP Resource kind: {kind}",
                safe_message="工具所需资源类型无效",
                error_code="mcp_resource_kind_invalid",
            )
        if not environment and kind != "loki":
            raise ToolPolicyError(
                "A non-global MCP Resource requires an environment",
                safe_message="工具调用必须指定环境",
                error_code="mcp_resource_target_incomplete",
            )
        if placement and kind == "loki":
            raise ToolPolicyError(
                f"Invalid MCP Resource placement: {placement}",
                safe_message="Loki 工具资源不能配置资源角色 placement",
                error_code="mcp_resource_placement_invalid",
            )

        candidates = [
            row
            for row in self._latest_published(kind)
            if self._matches(
                row,
                environment=environment,
                base=base,
                workshop=workshop,
                placement=placement,
            )
        ]
        if not candidates:
            raise ToolPolicyError(
                "No published MCP Resource matches the Job target",
                safe_message="当前 Job 目标没有可用的已发布工具资源",
                error_code="mcp_resource_not_resolved",
            )
        if len(candidates) != 1:
            raise ToolPolicyError(
                "Multiple published MCP Resources match the Job target",
                safe_message="当前 Job 目标匹配到多个工具资源，请明确资源角色 placement；同角色重复时请修正资源配置",
                error_code="mcp_resource_ambiguous",
                diagnostics={
                    "candidate_count": len(candidates),
                    "candidate_codes": sorted(str(row["code"]) for row in candidates),
                },
            )
        row = candidates[0]
        return self._materialize(
            row,
            environment=environment,
            base=base,
            workshop=workshop,
        )

    def directory(self) -> dict[str, Any]:
        """Return only non-secret Resource addresses for model context."""

        return {
            "resources": [
                {
                    "code": value.resource_code,
                    "kind": value.resource_kind,
                    "environment": value.environment,
                    "base": value.base,
                    "workshop": value.workshop,
                    "placement": value.placement,
                }
                for value in self.list_published_addresses()
            ]
        }

    def list_published_addresses(
        self,
        *,
        resource_kind: str = "",
    ) -> tuple[PublishedToolResourceAddress, ...]:
        """Read current non-secret call targets without resolving provider credentials."""

        selected_kind = str(resource_kind or "").strip().lower()
        if selected_kind and selected_kind not in {"database", "redis", "loki"}:
            raise ToolPolicyError(
                f"Unsupported MCP Resource kind: {selected_kind}",
                safe_message="工具资源类型无效",
                error_code="mcp_resource_kind_invalid",
            )
        kinds = (selected_kind,) if selected_kind else ("database", "redis", "loki")
        addresses: list[PublishedToolResourceAddress] = []
        for kind in kinds:
            for row in self._latest_published_address_rows(kind):
                for environment, base, workshop in self._published_call_targets(row):
                    if not self._matches(
                        row,
                        environment=environment,
                        base=base,
                        workshop=workshop,
                        placement=str(row.get("placement") or ""),
                    ):
                        continue
                    addresses.append(
                        PublishedToolResourceAddress(
                            resource_id=str(row["resource_id"]),
                            resource_code=str(row["code"]),
                            resource_kind=kind,
                            resource_revision_id=str(row["resource_revision_id"]),
                            resource_revision=int(row.get("revision") or 0),
                            resource_content_hash=str(row.get("content_hash") or ""),
                            environment=environment,
                            base=base,
                            workshop=workshop,
                            placement=str(row.get("placement") or ""),
                            query_limits=self._published_query_limits(row, kind),
                        )
                    )
        return tuple(sorted(addresses, key=lambda value: value.sort_key))

    def _latest_published_address_rows(self, resource_kind: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select resource.id as resource_id, resource.code, resource.resource_kind,
                   resource.scope_type, revision.placement,
                   environment.code as environment_code,
                   base.code as base_code, workshop.code as workshop_code,
                   revision.id as resource_revision_id, revision.revision,
                   revision.scope_bindings_json, revision.content_hash, revision.config_json
              from platform_resource resource
              join platform_resource_revision revision
                on revision.resource_id = resource.id
              left join platform_environment environment
                on environment.id = resource.environment_id
              left join platform_base base on base.id = resource.base_id
              left join platform_workshop workshop
                on workshop.id = resource.workshop_id
             where resource.status = 'enabled'
               and resource.resource_kind = ?
               and revision.status = 'PUBLISHED'
             order by resource.code, revision.revision desc
            """,
            (resource_kind,),
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest.setdefault(str(row["resource_id"]), row)
        return list(latest.values())

    @staticmethod
    def _published_query_limits(row: dict[str, Any], kind: str) -> dict[str, int]:
        if kind != "loki":
            return {}
        try:
            config = json.loads(str(row["config_json"]))
            result = {key: config[key] for key in ("max_minutes", "max_lines")}
            if any(type(value) is not int or value < 1 for value in result.values()):
                raise ValueError("Invalid numeric limits")
            return result
        except (KeyError, ValueError, TypeError):
            raise ToolPolicyError(
                "Published resource query limits are invalid",
                safe_message="已发布资源查询限制无效，请管理员重新验证并发布",
                error_code="resource_query_limits_invalid",
            ) from None

    @staticmethod
    def _published_call_targets(row: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
        try:
            bindings = json.loads(str(row.get("scope_bindings_json") or "[]"))
        except (TypeError, json.JSONDecodeError):
            return ()
        if not isinstance(bindings, list):
            return ()
        targets = {
            (
                str(value.get("environment_code") or "").strip(),
                str(value.get("base_code") or "").strip(),
                str(value.get("workshop_code") or "").strip(),
            )
            for value in bindings
            if isinstance(value, dict) and str(value.get("environment_code") or "").strip()
        }
        if targets:
            return tuple(sorted(targets))
        if str(row.get("resource_kind") or "") == "loki":
            return ()
        environment = str(row.get("environment_code") or "").strip()
        if not environment:
            return ()
        return (
            (
                environment,
                str(row.get("base_code") or "").strip(),
                str(row.get("workshop_code") or "").strip(),
            ),
        )

    def _latest_published(self, resource_kind: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select resource.id as resource_id, resource.code, resource.resource_kind,
                   resource.scope_type, revision.placement,
                   environment.code as environment_code,
                   base.code as base_code, workshop.code as workshop_code,
                   revision.id as resource_revision_id, revision.revision,
                   revision.provider_type, revision.provider_contract_version,
                   revision.config_json, revision.secret_refs_json,
                   revision.scope_bindings_json,
                   revision.content_hash
              from platform_resource resource
              join platform_resource_revision revision
                on revision.resource_id = resource.id
              left join platform_environment environment
                on environment.id = resource.environment_id
              left join platform_base base on base.id = resource.base_id
              left join platform_workshop workshop
                on workshop.id = resource.workshop_id
             where resource.status = 'enabled'
               and resource.resource_kind = ?
               and revision.status = 'PUBLISHED'
             order by resource.code, revision.revision desc
            """,
            (resource_kind,),
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest.setdefault(str(row["resource_id"]), row)
        return list(latest.values())

    @staticmethod
    def _matches(
        row: dict[str, Any],
        *,
        environment: str,
        base: str,
        workshop: str,
        placement: str,
    ) -> bool:
        scope_type = str(row.get("scope_type") or "")
        if scope_type != "global" and str(row.get("environment_code") or "") != environment:
            return False
        resource_base = str(row.get("base_code") or "")
        resource_workshop = str(row.get("workshop_code") or "")
        if resource_base and resource_base != base:
            return False
        if resource_workshop and resource_workshop != workshop:
            return False
        if resource_base and not base or resource_workshop and not workshop:
            return False
        resource_placement = str(row.get("placement") or "")
        if placement and resource_placement != placement:
            return False
        return True

    def _materialize(
        self,
        row: dict[str, Any],
        *,
        environment: str,
        base: str,
        workshop: str,
    ) -> ResolvedToolResource:
        try:
            config = json.loads(str(row["config_json"]))
            secret_refs = json.loads(str(row["secret_refs_json"]))
            scope_bindings = json.loads(str(row.get("scope_bindings_json") or "[]"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ToolPolicyError(
                "Published MCP Resource document is invalid",
                safe_message="已发布工具资源配置无效",
                error_code="mcp_resource_revision_invalid",
            ) from exc
        try:
            scope_binding = select_resource_scope_binding(
                scope_bindings,
                resource_kind=str(row["resource_kind"]),
                environment_code=environment,
                base_code=base,
                workshop_code=workshop,
            )
        except NonRetryableExecutionError as exc:
            raise ToolPolicyError(
                "Published MCP Resource scope binding is invalid",
                safe_message="已发布工具资源的数据范围无效",
                error_code="mcp_resource_scope_invalid",
            ) from exc
        kind = str(row["resource_kind"])
        if (kind == "loki" or (workshop and kind in {"database", "redis"})) and not scope_binding:
            raise ToolPolicyError(
                "Published MCP Resource has no exact data-scope binding",
                safe_message="当前目标没有已发布的数据范围配置",
                error_code="mcp_resource_scope_not_resolved",
            )
        scope_binding = scope_binding or {}
        table_prefix = str(scope_binding.get("table_prefix") or "")
        redis_namespace_prefixes = tuple(
            str(value)
            for value in scope_binding.get("namespace_prefixes", [])
            if str(value)
        )
        selector_value = scope_binding.get("selector_conditions") or {}
        if not isinstance(selector_value, dict):
            raise ToolPolicyError(
                "Published Loki selector conditions are invalid",
                safe_message="已发布 Loki selector 无效",
                error_code="mcp_resource_scope_invalid",
            )
        loki_selector_conditions = tuple(
            sorted((str(key), str(value)) for key, value in selector_value.items())
        )
        document = CanonicalProviderDocument(
            provider_type=str(row["provider_type"]),
            contract_version=str(row["provider_contract_version"]),
            resource_kind=str(row["resource_kind"]),
            config=dict(config),
            secret_refs={str(key): str(value) for key, value in dict(secret_refs).items()},
        )
        contract = self.provider_contracts.require(document.provider_type)
        if contract.contract_version != document.contract_version:
            raise ToolPolicyError(
                "Published MCP Resource uses a stale Provider contract",
                safe_message="工具资源 Provider 契约已变化，请重新验证并发布",
                error_code="mcp_resource_contract_stale",
            )
        projected = self.provider_contracts.runtime_projection(
            document,
            resolve_secret=self.secret_provider.resolve,
        )
        engine = (
            DatabaseEngine(document.provider_type)
            if document.resource_kind == "database"
            else DatabaseEngine.MYSQL
        )
        database = None
        redis = None
        loki = None
        if document.resource_kind == "database":
            database_name = str(
                projected.get("database")
                or projected.get("service_name")
                or projected.get("sid")
                or ""
            )
            database = DatabaseConnection(
                host=str(projected["host"]),
                port=int(projected["port"]),
                database=database_name,
                user=str(projected["user"]),
                password=str(projected.get("password") or ""),
                schema=str(projected.get("schema") or ""),
                oracle_client_mode=OracleClientMode.THICK,
                oracle_compat=OracleCompat.LEGACY,
                use_sid=bool(projected.get("sid")),
            )
        elif document.resource_kind == "redis":
            tls = projected.get("tls") or {}
            redis = RedisConnection(
                host=str(projected["host"]),
                port=int(projected["port"]),
                db=int(projected.get("db") or 0),
                username=str(projected.get("username") or ""),
                password=str(projected.get("password") or ""),
                tls_enabled=bool(tls.get("enabled", False)),
                tls_verify_certificate=bool(tls.get("verify_certificate", True)),
            )
        else:
            loki = LokiConnection(
                base_url=str(projected["base_url"]),
                tenant_id=str(projected.get("tenant") or ""),
                auth_token=str(projected.get("auth_token") or ""),
                timeout_seconds=int(projected["timeout_seconds"]),
                max_minutes=int(projected["max_minutes"]),
                max_lines=int(projected["max_lines"]),
            )
        environment_code = environment or str(row.get("environment_code") or "global")
        base_code = base or str(row.get("base_code") or "environment")
        workshop_value = (
            Workshop(
                code=workshop,
                table_prefix=table_prefix,
                redis_key_prefix=(redis_namespace_prefixes[0] if redis_namespace_prefixes else ""),
            )
            if workshop
            else None
        )
        base_value = Base(
            code=base_code,
            engine=engine,
            database=database,
            redis=redis,
            loki=loki,
            workshops=({workshop: workshop_value} if workshop_value else {}),
        )
        environment_value = Environment(
            code=environment_code,
            bases={base_code: base_value},
        )
        return ResolvedToolResource(
            resource_id=str(row["resource_id"]),
            resource_code=str(row["code"]),
            resource_revision_id=str(row["resource_revision_id"]),
            resource_content_hash=str(row["content_hash"]),
            placement=str(row.get("placement") or ""),
            table_prefix=table_prefix,
            redis_namespace_prefixes=redis_namespace_prefixes,
            loki_selector_conditions=loki_selector_conditions,
            scope_target=(
                str(scope_binding.get("environment_code") or environment),
                str(scope_binding.get("base_code") or ""),
                str(scope_binding.get("workshop_code") or ""),
            ),
            binding=ResourceBinding(
                environment=environment_value,
                base=base_value,
                kind=ResourceKind(str(row["resource_kind"])),
                workshop=workshop_value,
                engine=engine,
                database=database,
                redis=redis,
                loki=loki,
            ),
        )
