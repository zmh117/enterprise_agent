from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.modules.platform_config.infrastructure.repository import (
    json_text,
    new_id,
    now_iso,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


_CONSTRAINT_FIELDS = frozenset(
    {
        "environment_code",
        "base_code",
        "workshop_code",
        "max_rows",
        "max_bytes",
        "timeout_seconds",
        "key_prefix",
        "label_selector",
    }
)


class ApplicationPublicationBindingService:
    """Validate and persist immutable application Handler bindings."""

    def __init__(
        self,
        database: Database,
        registry: HandlerRegistry | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or build_builtin_handler_registry()

    def prepare(
        self,
        *,
        application_id: str,
        agent_publication_id: str,
        capabilities: Iterable[dict[str, Any]],
        raw_bindings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not raw_bindings:
            return []
        enabled_capabilities = {
            str(item["capability_code"])
            for item in capabilities
            if bool(item.get("enabled", True))
        }
        requested_codes = [
            str(item.get("capability_code") or "")
            for item in raw_bindings
        ]
        if (
            not enabled_capabilities
            or len(requested_codes) != len(set(requested_codes))
            or set(requested_codes) != enabled_capabilities
        ):
            raise self._invalid(
                "Handler bindings must cover every enabled application capability",
                "Handler 绑定必须与已启用的业务能力一一对应",
            )
        agent = self.database.execute_one(
            """
            select p.id, d.classification
              from agent_publication p
              join agent_definition d on d.id = p.agent_id
             where p.id = ? and p.status = 'active'
            """,
            (agent_publication_id,),
        )
        if agent is None:
            raise self._invalid(
                "Agent publication is unavailable for Handler binding",
                "Agent 发布版本不可用于 Handler 绑定",
            )
        return [
            self._prepare_binding(
                application_id=application_id,
                agent_publication_id=agent_publication_id,
                agent_classification=str(agent["classification"]),
                raw=raw,
            )
            for raw in raw_bindings
        ]

    def persist(
        self,
        *,
        application_publication_id: str,
        bindings: list[dict[str, Any]],
    ) -> None:
        if not bindings:
            return
        existing = self.database.execute(
            """
            select capability_code
              from business_application_publication_handler
             where application_publication_id = ?
             order by capability_code
            """,
            (application_publication_id,),
        )
        expected_codes = sorted(
            str(item["capability_code"]) for item in bindings
        )
        if existing:
            if [
                str(item["capability_code"]) for item in existing
            ] != expected_codes:
                raise self._invalid(
                    "Existing application Handler bindings do not match",
                    "业务应用发布版本的 Handler 绑定不一致",
                )
            return
        timestamp = now_iso()
        for binding in bindings:
            application_handler_id = new_id("application_handler")
            self.database.execute(
                """
                insert into business_application_publication_handler
                  (id, application_publication_id, handler_publication_id,
                   capability_code, constraints_json, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    application_handler_id,
                    application_publication_id,
                    binding["handler_publication_id"],
                    binding["capability_code"],
                    json_text(binding["constraints"]),
                    timestamp,
                ),
            )
            for resource in binding["resources"]:
                self.database.execute(
                    """
                    insert into business_application_publication_resource
                      (id, application_handler_id, resource_slot,
                       resource_revision_id, constraints_json, binding_hash,
                       created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("application_resource"),
                        application_handler_id,
                        resource["resource_slot"],
                        resource["resource_revision_id"],
                        json_text(resource["constraints"]),
                        resource["binding_hash"],
                        timestamp,
                    ),
                )

    def snapshot(self, bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "capability_code": item["capability_code"],
                "handler_publication_id": item["handler_publication_id"],
                "handler_id": item["handler_id"],
                "handler_version": item["handler_version"],
                "constraints": item["constraints"],
                "resources": item["resources"],
            }
            for item in bindings
        ]

    def _prepare_binding(
        self,
        *,
        application_id: str,
        agent_publication_id: str,
        agent_classification: str,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_keys(
            raw,
            {
                "capability_code",
                "handler_id",
                "handler_version",
                "constraints",
                "resources",
            },
            context="Handler binding",
        )
        capability_code = str(raw.get("capability_code") or "")
        handler_id = str(raw.get("handler_id") or "")
        handler_version = str(raw.get("handler_version") or "")
        try:
            definition = self.registry.require(
                handler_id,
                handler_version,
            )
        except HandlerRegistryError as exc:
            raise self._invalid(
                str(exc),
                "代码中不存在所选 Handler 精确版本",
            ) from exc
        if capability_code not in definition.required_permissions:
            raise self._invalid(
                "Handler does not provide the selected capability",
                "所选 Handler 与业务能力不匹配",
            )
        if (
            definition.visibility == "internal_diagnostic"
            and agent_classification != "internal_diagnostic"
        ):
            raise self._invalid(
                "Internal diagnostic Handler cannot be bound to this Agent",
                "普通业务 Agent 不能绑定内部诊断 Handler",
            )
        installation = self.database.execute_one(
            """
            select implementation_digest, installation_status
              from handler_installation
             where handler_id = ? and handler_version = ?
            """,
            (handler_id, handler_version),
        )
        publication = self.database.execute_one(
            """
            select id from handler_publication
             where handler_id = ? and handler_version = ?
               and status = 'PUBLISHED'
            """,
            (handler_id, handler_version),
        )
        if (
            installation is None
            or installation["installation_status"] != "INSTALLED"
            or installation["implementation_digest"]
            != definition.implementation_digest
            or publication is None
        ):
            raise self._invalid(
                "Handler exact version is not installed and published",
                "所选 Handler 精确版本尚未安装并发布",
            )
        if self.database.execute_one(
            """
            select b.id
              from agent_tool_binding b
              join tool_definition t on t.name = b.tool_name
             where b.publication_id = ? and b.tool_name = ?
               and t.enabled = 1 and t.read_only = 1
            """,
            (agent_publication_id, handler_id),
        ) is None:
            raise self._invalid(
                "Agent publication does not allow Handler",
                "Agent 发布版本未绑定该 Handler",
            )
        constraints = self._constraints(
            raw.get("constraints"),
            context="Handler binding",
        )
        resources = self._prepare_resources(
            definition.resource_slots,
            raw.get("resources"),
        )
        return {
            "application_id": application_id,
            "capability_code": capability_code,
            "handler_publication_id": str(publication["id"]),
            "handler_id": handler_id,
            "handler_version": handler_version,
            "constraints": constraints,
            "resources": resources,
        }

    def _prepare_resources(
        self,
        slots: Iterable[Any],
        raw_resources: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_resources, list):
            raise self._invalid(
                "Handler resources must be a list",
                "Handler 资源绑定格式无效",
            )
        slot_by_code = {str(slot.code): slot for slot in slots}
        requested = [
            str(item.get("resource_slot") or "")
            for item in raw_resources
            if isinstance(item, dict)
        ]
        required = {
            code for code, slot in slot_by_code.items() if slot.required
        }
        if (
            len(requested) != len(raw_resources)
            or len(requested) != len(set(requested))
            or not required.issubset(requested)
            or not set(requested).issubset(slot_by_code)
        ):
            raise self._invalid(
                "Handler resource slots are missing, duplicated, or undeclared",
                "Handler 必需资源槽缺失、重复或未声明",
            )
        result: list[dict[str, Any]] = []
        for raw in raw_resources:
            self._require_keys(
                raw,
                {"resource_slot", "resource_revision_id", "constraints"},
                context="Handler resource binding",
            )
            slot_code = str(raw.get("resource_slot") or "")
            slot = slot_by_code[slot_code]
            revision_id = str(raw.get("resource_revision_id") or "")
            row = self.database.execute_one(
                """
                select rr.id, rr.revision, rr.status,
                       r.id as resource_id, r.code as resource_code,
                       r.resource_kind, r.scope_type, r.status as resource_status,
                       r.environment_id, coalesce(r.base_id, '') as base_id,
                       coalesce(r.workshop_id, '') as workshop_id,
                       e.code as environment_code,
                       coalesce(b.code, '') as base_code,
                       coalesce(w.code, '') as workshop_code
                  from platform_resource_revision rr
                  join platform_resource r on r.id = rr.resource_id
                  join platform_environment e on e.id = r.environment_id
                  left join platform_base b on b.id = r.base_id
                  left join platform_workshop w on w.id = r.workshop_id
                 where rr.id = ?
                """,
                (revision_id,),
            )
            if (
                row is None
                or row["status"] != "PUBLISHED"
                or row["resource_status"] != "enabled"
                or row["resource_kind"] != slot.resource_kind
                or row["scope_type"] not in slot.allowed_scope_types
            ):
                raise self._invalid(
                    "Handler resource revision is unavailable or incompatible",
                    "所选资源发布版本不可用或与 Handler 资源槽不匹配",
                )
            constraints = self._constraints(
                raw.get("constraints"),
                context="Handler resource binding",
            )
            scope = {
                "environment_code": str(row["environment_code"]),
                "base_code": str(row["base_code"]),
                "workshop_code": str(row["workshop_code"]),
            }
            for key, value in scope.items():
                configured = str(constraints.get(key) or "")
                if configured and configured != value:
                    raise self._invalid(
                        "Resource constraint expands or changes its scope",
                        "资源绑定约束不能扩大或替换资源范围",
                    )
                constraints[key] = value
            fact = {
                "resource_slot": slot_code,
                "resource_revision_id": revision_id,
                "resource_id": str(row["resource_id"]),
                "resource_code": str(row["resource_code"]),
                "revision": int(row["revision"]),
                "resource_kind": str(row["resource_kind"]),
                "scope_type": str(row["scope_type"]),
                "environment_id": str(row["environment_id"]),
                "environment_code": str(row["environment_code"]),
                "base_id": str(row["base_id"]),
                "base_code": str(row["base_code"]),
                "workshop_id": str(row["workshop_id"]),
                "workshop_code": str(row["workshop_code"]),
                "constraints": constraints,
            }
            fact["binding_hash"] = snapshot_hash(fact)
            result.append(fact)
        return sorted(result, key=lambda item: item["resource_slot"])

    def _constraints(
        self,
        raw: Any,
        *,
        context: str,
    ) -> dict[str, Any]:
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise self._invalid(
                f"{context} constraints must be an object",
                "Handler 绑定约束格式无效",
            )
        unknown = set(raw).difference(_CONSTRAINT_FIELDS)
        if unknown:
            raise self._invalid(
                f"{context} contains unsupported constraints: {sorted(unknown)}",
                "Handler 绑定包含不支持的约束字段",
            )
        result: dict[str, Any] = {}
        for key, value in raw.items():
            if isinstance(value, bool) or not isinstance(
                value,
                (str, int),
            ):
                raise self._invalid(
                    f"{context} constraint type is invalid: {key}",
                    "Handler 绑定约束值类型无效",
                )
            if isinstance(value, str) and len(value) > 512:
                raise self._invalid(
                    f"{context} constraint is too long: {key}",
                    "Handler 绑定约束值过长",
                )
            if isinstance(value, int) and value < 0:
                raise self._invalid(
                    f"{context} constraint cannot be negative: {key}",
                    "Handler 绑定数值约束不能为负数",
                )
            result[str(key)] = value
        return result

    def _require_keys(
        self,
        value: Any,
        allowed: set[str],
        *,
        context: str,
    ) -> None:
        if not isinstance(value, dict):
            raise self._invalid(
                f"{context} must be an object",
                "Handler 绑定格式无效",
            )
        unknown = set(value).difference(allowed)
        if unknown:
            raise self._invalid(
                f"{context} contains unsupported fields: {sorted(unknown)}",
                "Handler 绑定包含不支持的字段",
            )

    @staticmethod
    def _invalid(message: str, safe_message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message=safe_message,
            error_code="application_handler_binding_invalid",
        )
