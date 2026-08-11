from __future__ import annotations

import json
from dataclasses import dataclass
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
from app.modules.platform_config.domain.provider_contracts import (
    CanonicalProviderDocument,
    ProviderContractRegistry,
)
from app.shared.database import Database
from app.shared.exceptions import ToolPolicyError


@dataclass(frozen=True, slots=True)
class ResolvedToolResource:
    resource_id: str
    resource_code: str
    resource_revision_id: str
    resource_content_hash: str
    placement: str
    binding: ResourceBinding


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
        placement = str(placement or "").strip().lower()
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
        if placement and placement not in {"cloud", "edge"}:
            raise ToolPolicyError(
                f"Invalid MCP Resource placement: {placement}",
                safe_message="资源位置只能为 cloud 或 edge",
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
                safe_message="当前 Job 目标匹配到多个工具资源，请明确 placement 或停用重复资源",
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

        resources = []
        for kind in ("database", "redis", "loki"):
            for row in self._latest_published(kind):
                resources.append(
                    {
                        "code": str(row["code"]),
                        "kind": kind,
                        "environment": str(row.get("environment_code") or ""),
                        "base": str(row.get("base_code") or ""),
                        "workshop": str(row.get("workshop_code") or ""),
                        "placement": str(row.get("placement") or ""),
                    }
                )
        return {"resources": sorted(resources, key=lambda value: value["code"])}

    def _latest_published(self, resource_kind: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select resource.id as resource_id, resource.code, resource.resource_kind,
                   resource.scope_type, resource.placement,
                   environment.code as environment_code,
                   base.code as base_code, workshop.code as workshop_code,
                   revision.id as resource_revision_id, revision.revision,
                   revision.provider_type, revision.provider_contract_version,
                   revision.config_json, revision.secret_refs_json,
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
        except (TypeError, json.JSONDecodeError) as exc:
            raise ToolPolicyError(
                "Published MCP Resource document is invalid",
                safe_message="已发布工具资源配置无效",
                error_code="mcp_resource_revision_invalid",
            ) from exc
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
                max_response_bytes=int(projected["max_response_bytes"]),
            )
        environment_code = environment or str(row.get("environment_code") or "global")
        base_code = base or str(row.get("base_code") or "environment")
        workshop_value = Workshop(
            code=workshop,
            table_prefix="",
            redis_key_prefix="",
        ) if workshop else None
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
