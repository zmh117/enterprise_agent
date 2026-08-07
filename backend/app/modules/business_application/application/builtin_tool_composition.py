from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.modules.platform_config.application.validation import (
    validate_resource_placement,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
    new_id,
    now_iso,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


_TARGET_SCOPE_TYPES = frozenset({"global", "environment", "base", "workshop"})
_APPLICATION_TARGET_SCOPE_TYPES = frozenset({"environment", "base", "workshop"})
_TARGET_KEYS = frozenset(
    {
        "target_scope_type",
        "environment_code",
        "base_code",
        "workshop_code",
    }
)
_MAX_TARGET_PATHS = 500
_MAX_TARGET_MATRIX_CELLS = 20_000
_SELECTION_KEYS = frozenset({"tool_release_id", "resources"})
_MAPPING_KEYS = frozenset(
    {
        "resource_slot",
        "target_scope_type",
        "environment_code",
        "base_code",
        "workshop_code",
        "placement",
        "resource_revision_id",
        "workshop_partition_policy_revision_id",
        "loki_scope_policy_revision_id",
    }
)


class ApplicationBuiltinToolCompositionService:
    """Freeze exact built-in Tool and Resource Mapping facts for an application."""

    def __init__(
        self,
        database: Database,
        registry: HandlerRegistry | None = None,
        topology: PlatformConfigRepository | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or build_builtin_handler_registry()
        self.topology = topology or PlatformConfigRepository(database)

    def prepare_targets(self, raw_targets: object) -> list[dict[str, Any]]:
        if not isinstance(raw_targets, list):
            raise self._invalid(
                "Application target paths must be a list",
                "应用目标清单必须是列表",
                field="target_paths",
                code="builtin_tool_application_target_invalid",
            )
        if len(raw_targets) > _MAX_TARGET_PATHS:
            raise self._invalid(
                "Application target path limit exceeded",
                "应用目标数量超过发布上限",
                field="target_paths",
                code="builtin_tool_application_target_invalid",
            )
        targets = [
            self._prepare_target(
                raw,
                field=f"target_paths.{index}",
            )
            for index, raw in enumerate(raw_targets)
        ]
        targets.sort(key=lambda value: str(value["target_key"]))
        keys = [str(value["target_key"]) for value in targets]
        if len(keys) != len(set(keys)):
            raise self._invalid(
                "Application target paths must be unique",
                "应用目标不能重复",
                field="target_paths",
                code="builtin_tool_application_target_invalid",
            )
        return targets

    def persist_draft_targets(
        self,
        *,
        application_revision_id: str,
        targets: list[dict[str, Any]],
    ) -> None:
        timestamp = now_iso()
        for target_order, target in enumerate(targets):
            self.database.execute(
                """
                insert into business_application_revision_target
                  (id, application_revision_id, target_scope_type, target_key,
                   environment_id, base_id, workshop_id, target_hash,
                   target_order, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("application_revision_target"),
                    application_revision_id,
                    target["target_scope_type"],
                    target["target_key"],
                    target["environment_id"],
                    target["base_id"],
                    target["workshop_id"],
                    target["target_hash"],
                    target_order,
                    timestamp,
                ),
            )

    def prepare_publication_targets(
        self,
        targets: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for index, stored in enumerate(targets):
            current = self._prepare_target(
                {
                    "target_scope_type": stored.get("target_scope_type"),
                    "environment_code": stored.get("environment_code"),
                    "base_code": stored.get("base_code"),
                    "workshop_code": stored.get("workshop_code"),
                },
                field=f"target_paths.{index}",
            )
            for field in (
                "target_key",
                "environment_id",
                "base_id",
                "workshop_id",
                "target_hash",
            ):
                if (stored.get(field) or None) != (current.get(field) or None):
                    raise self._invalid(
                        "Stored application target changed before publication",
                        "应用目标在发布前已变化，请重新保存 Draft",
                        field=f"target_paths.{index}",
                        code="builtin_tool_application_target_invalid",
                    )
            prepared.append(current)
        prepared.sort(key=lambda value: str(value["target_key"]))
        return prepared

    def persist_publication_targets(
        self,
        *,
        application_publication_id: str,
        targets: list[dict[str, Any]],
    ) -> None:
        existing = self._publication_target_facts(application_publication_id)
        expected = self.snapshot_targets(targets)
        if existing:
            if existing != expected:
                raise self._invalid(
                    "Existing application publication targets differ",
                    "该业务应用发布版本的目标清单不一致",
                    field="target_paths",
                    code="publication_binding_conflict",
                )
            return
        timestamp = now_iso()
        for target in targets:
            self.database.execute(
                """
                insert into business_application_publication_target
                  (id, application_publication_id, target_scope_type,
                   target_key, environment_id, base_id, workshop_id,
                   target_hash, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("application_publication_target"),
                    application_publication_id,
                    target["target_scope_type"],
                    target["target_key"],
                    target["environment_id"],
                    target["base_id"],
                    target["workshop_id"],
                    target["target_hash"],
                    timestamp,
                ),
            )

    def validate_target_matrix(
        self,
        *,
        targets: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        definitions = {
            str(tool["tool_identifier"]): self.registry.require(
                str(tool["tool_identifier"]),
                str(tool["handler_version"]),
            )
            for tool in tools
        }
        cell_count = sum(
            len(targets) * max(1, len(definition.resource_slots))
            for definition in definitions.values()
        )
        if cell_count > _MAX_TARGET_MATRIX_CELLS:
            raise self._invalid(
                "Application target matrix limit exceeded",
                "应用目标矩阵超过发布上限",
                field="target_paths",
                code="builtin_tool_application_target_invalid",
            )
        if (
            any(
                slot.required
                for definition in definitions.values()
                for slot in definition.resource_slots
            )
            and not targets
        ):
            raise self._invalid(
                "Required Tool slots have no explicit application targets",
                "已选工具存在必需资源槽，请先配置应用目标",
                field="target_paths",
                code="builtin_tool_resource_mapping_missing",
            )

        resource_facts: dict[str, dict[str, Any]] = {}
        resolved: list[dict[str, Any]] = []
        for tool in tools:
            definition = definitions[str(tool["tool_identifier"])]
            slots = {slot.code: slot for slot in definition.resource_slots}
            resources = list(tool.get("resources") or [])
            for mapping_index, mapping in enumerate(resources):
                if not any(self._mapping_covers_target(mapping, target) for target in targets):
                    raise self._invalid(
                        "Resource Mapping is outside explicit application targets",
                        "资源映射未覆盖任何显式应用目标",
                        field=(
                            f"builtin_tools.{tool['tool_identifier']}.resources.{mapping_index}"
                        ),
                        code="builtin_tool_resource_mapping_overlap",
                    )
            slot_codes = set(slots).union(str(mapping["resource_slot"]) for mapping in resources)
            for slot_code in sorted(slot_codes):
                slot = slots.get(slot_code)
                if slot is None:
                    raise self._invalid(
                        "Stored Mapping uses an undeclared Tool slot",
                        "资源映射使用了工具未声明的资源槽",
                        field=f"builtin_tools.{tool['tool_identifier']}.resources",
                    )
                for target in targets:
                    candidates = [
                        mapping
                        for mapping in resources
                        if str(mapping["resource_slot"]) == slot_code
                        and self._mapping_covers_target(mapping, target)
                    ]
                    if not candidates:
                        if slot.required:
                            raise self._matrix_error(
                                code="builtin_tool_resource_mapping_missing",
                                message="Required Resource Mapping is missing",
                                safe_message="应用目标缺少必需的工具资源映射",
                                tool=tool,
                                slot_code=slot_code,
                                target=target,
                                candidate_count=0,
                            )
                        continue
                    placements = {str(mapping.get("placement") or "") for mapping in candidates}
                    if "" in placements and len(placements) > 1:
                        raise self._matrix_error(
                            code="builtin_tool_resource_mapping_overlap",
                            message="No-placement and placed Resource Mappings overlap",
                            safe_message="同一目标不能混用无 placement 与 cloud/edge 映射",
                            tool=tool,
                            slot_code=slot_code,
                            target=target,
                            candidate_count=len(candidates),
                        )
                    for placement_key in sorted(placements):
                        matches = [
                            mapping
                            for mapping in candidates
                            if str(mapping.get("placement") or "") == placement_key
                        ]
                        if len(matches) != 1:
                            raise self._matrix_error(
                                code="builtin_tool_resource_mapping_overlap",
                                message="Resource Mapping target scopes overlap",
                                safe_message="资源映射范围重叠，无法唯一解析",
                                tool=tool,
                                slot_code=slot_code,
                                target=target,
                                candidate_count=len(matches),
                            )
                        mapping = matches[0]
                        revision_id = str(mapping["resource_revision_id"])
                        resource = resource_facts.get(revision_id)
                        if resource is None:
                            resource = self._published_resource_fact(revision_id)
                            resource_facts[revision_id] = resource
                        policy_facts = self._validate_matrix_policy(
                            mapping=mapping,
                            target=target,
                            resource=resource,
                            field=(
                                f"builtin_tools.{tool['tool_identifier']}."
                                f"{slot_code}.{target['target_key']}"
                            ),
                        )
                        resolved.append(
                            {
                                "tool_identifier": tool["tool_identifier"],
                                "tool_release_id": tool["tool_release_id"],
                                "handler_version": tool["handler_version"],
                                "implementation_digest": tool["implementation_digest"],
                                "resource_slot": slot_code,
                                "target_scope_type": target["target_scope_type"],
                                "target_key": target["target_key"],
                                "environment_id": target["environment_id"],
                                "base_id": target["base_id"],
                                "workshop_id": target["workshop_id"],
                                "target_hash": target["target_hash"],
                                "placement": placement_key or None,
                                "resource_revision_id": revision_id,
                                "resource_content_hash": resource["resource_content_hash"],
                                "resource_kind": resource["resource_kind"],
                                "resource_scope_type": resource["scope_type"],
                                "workshop_partition_policy_revision_id": mapping[
                                    "workshop_partition_policy_revision_id"
                                ],
                                "loki_scope_policy_revision_id": mapping[
                                    "loki_scope_policy_revision_id"
                                ],
                                "workshop_partition_policy_hash": policy_facts[
                                    "workshop_partition_policy_hash"
                                ],
                                "loki_scope_policy_hash": policy_facts["loki_scope_policy_hash"],
                                "mapping_hash": mapping["mapping_hash"],
                            }
                        )
        self._validate_workshop_policy_consistency(resolved)
        resolved.sort(
            key=lambda value: (
                str(value["tool_identifier"]),
                str(value["resource_slot"]),
                str(value["target_key"]),
                str(value.get("placement") or ""),
            )
        )
        return resolved

    def _validate_workshop_policy_consistency(
        self,
        resolved: list[dict[str, Any]],
    ) -> None:
        policies_by_boundary: dict[tuple[str, str], set[str]] = {}
        placements_by_boundary: dict[tuple[str, str], set[str]] = {}
        for item in resolved:
            workshop_id = str(item.get("workshop_id") or "")
            resource_kind = str(item.get("resource_kind") or "")
            if not workshop_id or resource_kind not in {"database", "redis"}:
                continue
            boundary = (workshop_id, resource_kind)
            policies_by_boundary.setdefault(boundary, set()).add(
                str(item.get("workshop_partition_policy_revision_id") or "")
            )
            placements_by_boundary.setdefault(boundary, set()).add(str(item.get("placement") or ""))
        for boundary, policy_ids in policies_by_boundary.items():
            if len(policy_ids) <= 1:
                continue
            workshop_id, resource_kind = boundary
            placements = sorted(placements_by_boundary[boundary])
            raise self._invalid(
                "Workshop Resource Mappings use inconsistent Partition Policy Revisions "
                f"for {workshop_id}/{resource_kind}: placements={placements}",
                "同一车间的 cloud、edge 或无 placement 资源必须使用同一个分区策略版本",
                field="builtin_tools.resources.workshop_partition_policy_revision_id",
                code="builtin_tool_partition_policy_inconsistent",
            )

    def prepare_draft(
        self,
        *,
        agent_publication_id: str,
        raw_tools: object,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_tools, list):
            raise self._invalid(
                "Application built-in Tool selection must be a list",
                "内置只读工具配置必须是列表",
                field="builtin_tools",
            )
        prepared: list[dict[str, Any]] = []
        seen_release_ids: set[str] = set()
        for index, raw in enumerate(raw_tools):
            if not isinstance(raw, dict):
                raise self._invalid(
                    "Application built-in Tool selection must be an object",
                    "内置只读工具选择项必须是对象",
                    field=f"builtin_tools.{index}",
                )
            self._require_keys(
                raw,
                _SELECTION_KEYS,
                field=f"builtin_tools.{index}",
            )
            release_id = str(raw.get("tool_release_id") or "").strip()
            if not release_id or release_id in seen_release_ids:
                raise self._invalid(
                    "Application built-in Tool Releases must be non-empty and unique",
                    "内置只读工具 Release 不能为空或重复",
                    field=f"builtin_tools.{index}.tool_release_id",
                )
            seen_release_ids.add(release_id)
            envelope = self._require_exact_envelope(
                agent_publication_id=agent_publication_id,
                tool_release_id=release_id,
                require_active=True,
            )
            definition = self._require_exact_definition(envelope)
            raw_resources = raw.get("resources") or []
            if not isinstance(raw_resources, list):
                raise self._invalid(
                    "Application built-in Tool resources must be a list",
                    "工具资源映射必须是列表",
                    field=f"builtin_tools.{index}.resources",
                )
            resources = [
                self._prepare_mapping(
                    definition=definition,
                    raw=value,
                    field=f"builtin_tools.{index}.resources.{mapping_index}",
                )
                for mapping_index, value in enumerate(raw_resources)
            ]
            resources.sort(key=self._mapping_sort_key)
            self._require_unique_mappings(resources, field=f"builtin_tools.{index}.resources")
            exact = {
                "agent_publication_id": str(envelope["agent_publication_id"]),
                "agent_publication_tool_id": str(envelope["id"]),
                "tool_identifier": str(envelope["tool_identifier"]),
                "tool_release_id": str(envelope["tool_release_id"]),
                "handler_version": str(envelope["handler_version"]),
                "implementation_digest": str(envelope["implementation_digest"]),
                "public_schema_hash": str(envelope["public_schema_hash"]),
                "resources": resources,
            }
            exact["selection_hash"] = snapshot_hash(self.snapshot_tool(exact))
            prepared.append(exact)
        prepared.sort(key=lambda value: str(value["tool_identifier"]))
        return prepared

    def persist_draft(
        self,
        *,
        application_revision_id: str,
        tools: list[dict[str, Any]],
    ) -> None:
        timestamp = now_iso()
        for selection_order, tool in enumerate(tools):
            selection_id = new_id("application_revision_tool")
            self.database.execute(
                """
                insert into business_application_revision_builtin_tool
                  (id, application_revision_id, agent_publication_id,
                   agent_publication_tool_id, tool_identifier, tool_release_id,
                   handler_version, implementation_digest, public_schema_hash,
                   selection_hash, selection_order, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selection_id,
                    application_revision_id,
                    tool["agent_publication_id"],
                    tool["agent_publication_tool_id"],
                    tool["tool_identifier"],
                    tool["tool_release_id"],
                    tool["handler_version"],
                    tool["implementation_digest"],
                    tool["public_schema_hash"],
                    tool["selection_hash"],
                    selection_order,
                    timestamp,
                ),
            )
            for mapping_order, mapping in enumerate(tool["resources"]):
                self.database.execute(
                    """
                    insert into business_application_revision_builtin_tool_resource
                      (id, application_revision_tool_id, resource_slot,
                       target_scope_type, target_key, environment_id, base_id,
                       workshop_id, placement, placement_key,
                       resource_revision_id,
                       workshop_partition_policy_revision_id,
                       loki_scope_policy_revision_id, mapping_hash,
                       mapping_order, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("application_revision_tool_resource"),
                        selection_id,
                        mapping["resource_slot"],
                        mapping["target_scope_type"],
                        mapping["target_key"],
                        mapping["environment_id"],
                        mapping["base_id"],
                        mapping["workshop_id"],
                        mapping["placement"],
                        mapping["placement"] or "",
                        mapping["resource_revision_id"],
                        mapping["workshop_partition_policy_revision_id"] or None,
                        mapping["loki_scope_policy_revision_id"] or None,
                        mapping["mapping_hash"],
                        mapping_order,
                        timestamp,
                    ),
                )

    def prepare_publication(
        self,
        *,
        agent_publication_id: str,
        tools: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for index, stored in enumerate(tools):
            envelope = self._require_exact_envelope(
                agent_publication_id=agent_publication_id,
                tool_release_id=str(stored.get("tool_release_id") or ""),
                require_active=True,
            )
            definition = self._require_exact_definition(envelope)
            for field in (
                "agent_publication_tool_id",
                "tool_identifier",
                "handler_version",
                "implementation_digest",
                "public_schema_hash",
            ):
                if str(stored.get(field) or "") != str(
                    envelope["id" if field == "agent_publication_tool_id" else field]
                ):
                    raise self._invalid(
                        "Stored application Tool selection differs from its Agent Envelope",
                        "应用工具选择与 Agent 发布信封不一致",
                        field=f"builtin_tools.{index}.{field}",
                    )
            resources = []
            for mapping_index, mapping in enumerate(stored.get("resources") or []):
                validated = self._revalidate_stored_mapping(
                    mapping,
                    definition=definition,
                    field=f"builtin_tools.{index}.resources.{mapping_index}",
                )
                resources.append(validated)
            resources.sort(key=self._mapping_sort_key)
            exact = {
                "agent_publication_id": agent_publication_id,
                "agent_publication_tool_id": str(envelope["id"]),
                "tool_identifier": str(envelope["tool_identifier"]),
                "tool_release_id": str(envelope["tool_release_id"]),
                "handler_version": str(envelope["handler_version"]),
                "implementation_digest": str(envelope["implementation_digest"]),
                "public_schema_hash": str(envelope["public_schema_hash"]),
                "resources": resources,
            }
            exact["selection_hash"] = snapshot_hash(self.snapshot_tool(exact))
            if exact["selection_hash"] != str(stored.get("selection_hash") or ""):
                raise self._invalid(
                    "Stored application Tool selection hash mismatch",
                    "应用工具选择完整性校验失败",
                    field=f"builtin_tools.{index}",
                )
            prepared.append(exact)
        prepared.sort(key=lambda value: str(value["tool_identifier"]))
        return prepared

    def persist_publication(
        self,
        *,
        application_publication_id: str,
        tools: list[dict[str, Any]],
    ) -> None:
        existing = self._publication_facts(application_publication_id)
        expected = self.snapshot(tools)
        if existing:
            if existing != expected:
                raise self._invalid(
                    "Existing application built-in Tool Mapping differs",
                    "该业务应用发布版本的内置工具资源映射不一致",
                    field="builtin_tools",
                    code="publication_binding_conflict",
                )
            return
        timestamp = now_iso()
        for tool in tools:
            application_tool_id = new_id("application_publication_tool")
            self.database.execute(
                """
                insert into business_application_publication_builtin_tool
                  (id, application_publication_id, agent_publication_id,
                   agent_publication_tool_id, tool_identifier, tool_release_id,
                   handler_version, implementation_digest, public_schema_hash,
                   allowlist_hash, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_tool_id,
                    application_publication_id,
                    tool["agent_publication_id"],
                    tool["agent_publication_tool_id"],
                    tool["tool_identifier"],
                    tool["tool_release_id"],
                    tool["handler_version"],
                    tool["implementation_digest"],
                    tool["public_schema_hash"],
                    tool["selection_hash"],
                    timestamp,
                ),
            )
            for mapping in tool["resources"]:
                self.database.execute(
                    """
                    insert into business_application_publication_builtin_tool_resource
                      (id, application_tool_id, resource_slot,
                       target_scope_type, target_key, environment_id, base_id,
                       workshop_id, placement, placement_key,
                       resource_revision_id,
                       workshop_partition_policy_revision_id,
                       loki_scope_policy_revision_id, mapping_hash, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("application_publication_tool_resource"),
                        application_tool_id,
                        mapping["resource_slot"],
                        mapping["target_scope_type"],
                        mapping["target_key"],
                        mapping["environment_id"],
                        mapping["base_id"],
                        mapping["workshop_id"],
                        mapping["placement"],
                        mapping["placement"] or "",
                        mapping["resource_revision_id"],
                        mapping["workshop_partition_policy_revision_id"] or None,
                        mapping["loki_scope_policy_revision_id"] or None,
                        mapping["mapping_hash"],
                        timestamp,
                    ),
                )

    def prepare_resolution_set(
        self,
        resolutions: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for resolution in resolutions:
            item = {
                "tool_identifier": resolution["tool_identifier"],
                "tool_release_id": resolution["tool_release_id"],
                "handler_version": resolution["handler_version"],
                "implementation_digest": resolution["implementation_digest"],
                "resource_slot": resolution["resource_slot"],
                "target_scope_type": resolution["target_scope_type"],
                "target_key": resolution["target_key"],
                "target_hash": resolution["target_hash"],
                "environment_id": resolution["environment_id"],
                "base_id": resolution["base_id"],
                "workshop_id": resolution["workshop_id"],
                "placement": resolution["placement"],
                "resource_revision_id": resolution["resource_revision_id"],
                "resource_content_hash": resolution["resource_content_hash"],
                "resource_kind": resolution["resource_kind"],
                "resource_scope_type": resolution["resource_scope_type"],
                "workshop_partition_policy_revision_id": resolution[
                    "workshop_partition_policy_revision_id"
                ],
                "workshop_partition_policy_hash": resolution["workshop_partition_policy_hash"],
                "loki_scope_policy_revision_id": resolution["loki_scope_policy_revision_id"],
                "loki_scope_policy_hash": resolution["loki_scope_policy_hash"],
                "mapping_hash": resolution["mapping_hash"],
            }
            item["resolution_hash"] = snapshot_hash(item)
            items.append(item)
        items.sort(
            key=lambda value: (
                str(value["tool_identifier"]),
                str(value["resource_slot"]),
                str(value["target_key"]),
                str(value.get("placement") or ""),
            )
        )
        return {
            "schema_version": 1,
            "resolution_count": len(items),
            "resolution_set_hash": snapshot_hash(items),
            "resolutions": items,
        }

    def persist_publication_resolutions(
        self,
        *,
        application_publication_id: str,
        resolution_set: dict[str, Any],
    ) -> None:
        canonical = self.prepare_resolution_set(resolution_set.get("resolutions") or [])
        if canonical != resolution_set:
            raise self._invalid(
                "Application resolution set hash is invalid",
                "业务应用资源解析表完整性校验失败",
                field="builtin_tool_resolution_set",
                code="publication_binding_conflict",
            )
        existing = self._publication_resolution_set(application_publication_id)
        if existing is not None:
            if existing != resolution_set:
                raise self._invalid(
                    "Existing application resolution set differs",
                    "该业务应用发布版本的资源解析表不一致",
                    field="builtin_tool_resolution_set",
                    code="publication_binding_conflict",
                )
            return
        partial = self.database.execute_one(
            """
            select count(*) as count
              from business_application_publication_builtin_tool_resolution
             where application_publication_id = ?
            """,
            (application_publication_id,),
        )
        if partial and int(partial["count"]) > 0:
            raise self._invalid(
                "Application resolution rows exist without their set hash",
                "业务应用发布版本存在不完整的资源解析表",
                field="builtin_tool_resolution_set",
                code="publication_binding_conflict",
            )
        application_tools = {
            str(row["tool_identifier"]): row
            for row in self.database.execute(
                """
                select *
                  from business_application_publication_builtin_tool
                 where application_publication_id = ?
                """,
                (application_publication_id,),
            )
        }
        timestamp = now_iso()
        resolutions = list(resolution_set.get("resolutions") or [])
        for resolution_order, resolution in enumerate(resolutions):
            application_tool = application_tools.get(str(resolution["tool_identifier"]))
            if application_tool is None or any(
                str(application_tool[field]) != str(resolution[field])
                for field in (
                    "tool_release_id",
                    "handler_version",
                    "implementation_digest",
                )
            ):
                raise self._invalid(
                    "Resolution does not match the frozen application Tool",
                    "资源解析结果与应用工具发布事实不一致",
                    field=(f"builtin_tool_resolution_set.resolutions.{resolution_order}"),
                    code="publication_binding_conflict",
                )
            self.database.execute(
                """
                insert into business_application_publication_builtin_tool_resolution
                  (id, application_publication_id, application_tool_id,
                   tool_identifier, tool_release_id, handler_version,
                   implementation_digest, resource_slot, target_scope_type,
                   target_key, target_hash, environment_id, base_id,
                   workshop_id, placement, placement_key,
                   resource_revision_id, resource_content_hash, resource_kind,
                   resource_scope_type,
                   workshop_partition_policy_revision_id,
                   workshop_partition_policy_hash,
                   loki_scope_policy_revision_id, loki_scope_policy_hash,
                   mapping_hash, resolution_hash, resolution_order, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("application_tool_resolution"),
                    application_publication_id,
                    application_tool["id"],
                    resolution["tool_identifier"],
                    resolution["tool_release_id"],
                    resolution["handler_version"],
                    resolution["implementation_digest"],
                    resolution["resource_slot"],
                    resolution["target_scope_type"],
                    resolution["target_key"],
                    resolution["target_hash"],
                    resolution["environment_id"],
                    resolution["base_id"],
                    resolution["workshop_id"],
                    resolution["placement"],
                    resolution["placement"] or "",
                    resolution["resource_revision_id"],
                    resolution["resource_content_hash"],
                    resolution["resource_kind"],
                    resolution["resource_scope_type"],
                    resolution["workshop_partition_policy_revision_id"] or None,
                    resolution["workshop_partition_policy_hash"] or None,
                    resolution["loki_scope_policy_revision_id"] or None,
                    resolution["loki_scope_policy_hash"] or None,
                    resolution["mapping_hash"],
                    resolution["resolution_hash"],
                    resolution_order,
                    timestamp,
                ),
            )
        self.database.execute(
            """
            insert into business_application_publication_builtin_tool_resolution_set
              (application_publication_id, schema_version, resolution_count,
               resolution_set_hash, created_at)
            values (?, 1, ?, ?, ?)
            """,
            (
                application_publication_id,
                len(resolutions),
                resolution_set["resolution_set_hash"],
                timestamp,
            ),
        )

    def snapshot(self, tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.snapshot_tool(tool) for tool in tools]

    def publication_facts(
        self,
        application_publication_id: str,
    ) -> dict[str, Any]:
        return {
            "tools": self._publication_facts(application_publication_id),
            "targets": self._publication_target_facts(application_publication_id),
            "resolution_set": self._publication_resolution_set(application_publication_id),
        }

    def management_catalog(
        self,
        *,
        agent_publication_ids: Iterable[str],
    ) -> dict[str, Any]:
        envelopes: dict[str, list[dict[str, Any]]] = {}
        for publication_id in sorted({str(value) for value in agent_publication_ids}):
            rows = self.database.execute(
                """
                select envelope.*, release.release_revision,
                       release.tool_semantic_version,
                       release.status as release_status,
                       installation.installation_status,
                       installation.implementation_digest as installed_digest,
                       manifest.manifest_json
                  from agent_publication_builtin_tool envelope
                  join builtin_tool_release release
                    on release.id = envelope.tool_release_id
                  left join builtin_tool_installation installation
                    on installation.tool_identifier = envelope.tool_identifier
                   and installation.handler_version = envelope.handler_version
                  left join builtin_tool_manifest_projection manifest
                    on manifest.tool_identifier = envelope.tool_identifier
                   and manifest.handler_version = envelope.handler_version
                   and manifest.implementation_digest = envelope.implementation_digest
                 where envelope.agent_publication_id = ?
                 order by envelope.tool_identifier
                """,
                (publication_id,),
            )
            values: list[dict[str, Any]] = []
            for row in rows:
                manifest = json.loads(str(row.get("manifest_json") or "{}"))
                code_exact = False
                try:
                    definition = self.registry.require(
                        str(row["tool_identifier"]),
                        str(row["handler_version"]),
                    )
                    code_exact = (
                        definition.implementation_digest
                        == str(row["implementation_digest"])
                        and definition.public_schema_hash
                        == str(row["public_schema_hash"])
                    )
                except HandlerRegistryError:
                    pass
                exact_installed = (
                    str(row.get("installation_status") or "") == "INSTALLED"
                    and str(row.get("installed_digest") or "")
                    == str(row["implementation_digest"])
                    and code_exact
                )
                values.append(
                    {
                        "tool_identifier": str(row["tool_identifier"]),
                        "tool_release_id": str(row["tool_release_id"]),
                        "release_revision": int(row["release_revision"]),
                        "tool_semantic_version": str(
                            row["tool_semantic_version"]
                        ),
                        "handler_version": str(row["handler_version"]),
                        "implementation_digest": str(
                            row["implementation_digest"]
                        ),
                        "public_schema_hash": str(row["public_schema_hash"]),
                        "display_name": str(
                            manifest.get("display_name")
                            or row["tool_identifier"]
                        ),
                        "model_description": str(
                            row.get("model_description")
                            or manifest.get("description")
                            or ""
                        ),
                        "resource_slots": list(
                            manifest.get("resource_slots") or []
                        ),
                        "release_status": str(row["release_status"]),
                        "installation_status": str(
                            row.get("installation_status") or "MISSING"
                        ),
                        "selectable": (
                            str(row["release_status"]) == "ACTIVE"
                            and exact_installed
                        ),
                    }
                )
            envelopes[publication_id] = values

        resources = [
            {
                "resource_revision_id": str(row["resource_revision_id"]),
                "resource_revision": int(row["resource_revision"]),
                "resource_code": str(row["resource_code"]),
                "resource_name": str(row["resource_name"]),
                "resource_kind": str(row["resource_kind"]),
                "scope_type": str(row["scope_type"]),
                "environment_code": str(row.get("environment_code") or ""),
                "base_code": str(row.get("base_code") or ""),
                "workshop_code": str(row.get("workshop_code") or ""),
                "content_hash": str(row["content_hash"]),
            }
            for row in self.database.execute(
                """
                select revision.id as resource_revision_id,
                       revision.revision as resource_revision,
                       revision.content_hash, resource.code as resource_code,
                       resource.name as resource_name,
                       resource.resource_kind, resource.scope_type,
                       environment.code as environment_code,
                       base.code as base_code, workshop.code as workshop_code
                  from platform_resource_revision revision
                  join platform_resource resource
                    on resource.id = revision.resource_id
                  left join platform_environment environment
                    on environment.id = resource.environment_id
                  left join platform_base base on base.id = resource.base_id
                  left join platform_workshop workshop
                    on workshop.id = resource.workshop_id
                 where revision.status = 'PUBLISHED'
                   and resource.status = 'enabled'
                 order by resource.resource_kind, resource.code,
                          revision.revision desc
                """
            )
        ]
        workshop_policies = [
            {
                "policy_revision_id": str(row["policy_revision_id"]),
                "policy_revision": int(row["policy_revision"]),
                "policy_code": str(row["policy_code"]),
                "environment_code": str(row["environment_code"]),
                "base_code": str(row["base_code"]),
                "workshop_code": str(row["workshop_code"]),
                "database_rule_enabled": bool(
                    row["database_rule_enabled"]
                ),
                "redis_rule_enabled": bool(row["redis_rule_enabled"]),
                "content_hash": str(row["content_hash"]),
            }
            for row in self.database.execute(
                """
                select revision.id as policy_revision_id,
                       revision.revision as policy_revision,
                       revision.database_rule_enabled,
                       revision.redis_rule_enabled, revision.content_hash,
                       policy.code as policy_code,
                       environment.code as environment_code,
                       base.code as base_code,
                       workshop.code as workshop_code
                  from workshop_partition_policy_revision revision
                  join workshop_partition_policy policy
                    on policy.id = revision.policy_id
                  join platform_workshop workshop
                    on workshop.id = policy.workshop_id
                  join platform_base base on base.id = workshop.base_id
                  join platform_environment environment
                    on environment.id = base.environment_id
                 where revision.status = 'PUBLISHED'
                   and policy.status = 'enabled'
                 order by policy.code, revision.revision desc
                """
            )
        ]
        loki_policies: list[dict[str, Any]] = []
        for row in self.database.execute(
            """
            select revision.id as policy_revision_id,
                   revision.revision as policy_revision,
                   revision.resource_revision_id, revision.content_hash,
                   revision.health_status, policy.code as policy_code,
                   environment.code as environment_code,
                   base.code as base_code
              from loki_scope_policy_revision revision
              join loki_scope_policy policy on policy.id = revision.policy_id
              join platform_environment environment
                on environment.id = policy.environment_id
              left join platform_base base on base.id = policy.base_id
             where revision.status = 'PUBLISHED'
               and policy.status = 'enabled'
             order by policy.code, revision.revision desc
            """
        ):
            conditions = self.database.execute(
                """
                select label_key, label_value
                  from loki_scope_policy_revision_condition
                 where policy_revision_id = ?
                 order by position
                """,
                (str(row["policy_revision_id"]),),
            )
            loki_policies.append(
                {
                    "policy_revision_id": str(row["policy_revision_id"]),
                    "policy_revision": int(row["policy_revision"]),
                    "policy_code": str(row["policy_code"]),
                    "resource_revision_id": str(
                        row["resource_revision_id"]
                    ),
                    "environment_code": str(row["environment_code"]),
                    "base_code": str(row.get("base_code") or ""),
                    "health_status": str(row["health_status"]),
                    "conditions": [
                        {
                            "key": str(condition["label_key"]),
                            "value": str(condition["label_value"]),
                        }
                        for condition in conditions
                    ],
                    "content_hash": str(row["content_hash"]),
                }
            )

        environments = self.topology.list_environments(
            include_disabled=False
        )
        bases = self.topology.list_bases(include_disabled=False)
        workshops = self.topology.list_workshops(include_disabled=False)
        base_keys_with_workshops = {
            (str(item["environment_code"]), str(item["base_code"]))
            for item in workshops
        }
        environments_with_bases = {
            str(item["environment_code"]) for item in bases
        }
        targets = [
            {
                "target_scope_type": "workshop",
                "environment_code": str(item["environment_code"]),
                "base_code": str(item["base_code"]),
                "workshop_code": str(item["code"]),
                "display_name": str(item.get("display_name") or item["code"]),
            }
            for item in workshops
        ]
        targets.extend(
            {
                "target_scope_type": "base",
                "environment_code": str(item["environment_code"]),
                "base_code": str(item["code"]),
                "workshop_code": "",
                "display_name": str(item.get("display_name") or item["code"]),
            }
            for item in bases
            if (str(item["environment_code"]), str(item["code"]))
            not in base_keys_with_workshops
        )
        targets.extend(
            {
                "target_scope_type": "environment",
                "environment_code": str(item["code"]),
                "base_code": "",
                "workshop_code": "",
                "display_name": str(item.get("display_name") or item["code"]),
            }
            for item in environments
            if str(item["code"]) not in environments_with_bases
        )
        targets.sort(
            key=lambda item: (
                str(item["environment_code"]),
                str(item["base_code"]),
                str(item["workshop_code"]),
            )
        )
        return {
            "builtin_tools_by_agent_publication": envelopes,
            "resource_revisions": resources,
            "workshop_policy_revisions": workshop_policies,
            "loki_policy_revisions": loki_policies,
            "target_paths": targets,
        }

    @staticmethod
    def snapshot_targets(
        targets: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "target_scope_type": target["target_scope_type"],
                "target_key": target["target_key"],
                "environment_id": target["environment_id"],
                "base_id": target["base_id"],
                "workshop_id": target["workshop_id"],
                "environment_code": target["environment_code"],
                "base_code": target["base_code"],
                "workshop_code": target["workshop_code"],
                "environment_revision": target["environment_revision"],
                "base_revision": target["base_revision"],
                "workshop_revision": target["workshop_revision"],
                "target_hash": target["target_hash"],
            }
            for target in targets
        ]

    @staticmethod
    def snapshot_tool(tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent_publication_id": tool["agent_publication_id"],
            "agent_publication_tool_id": tool["agent_publication_tool_id"],
            "tool_identifier": tool["tool_identifier"],
            "tool_release_id": tool["tool_release_id"],
            "handler_version": tool["handler_version"],
            "implementation_digest": tool["implementation_digest"],
            "public_schema_hash": tool["public_schema_hash"],
            "resources": [
                {
                    "resource_slot": mapping["resource_slot"],
                    "target_scope_type": mapping["target_scope_type"],
                    "target_key": mapping["target_key"],
                    "environment_id": mapping["environment_id"],
                    "base_id": mapping["base_id"],
                    "workshop_id": mapping["workshop_id"],
                    "placement": mapping["placement"],
                    "resource_revision_id": mapping["resource_revision_id"],
                    "workshop_partition_policy_revision_id": mapping[
                        "workshop_partition_policy_revision_id"
                    ],
                    "loki_scope_policy_revision_id": mapping["loki_scope_policy_revision_id"],
                    "mapping_hash": mapping["mapping_hash"],
                }
                for mapping in tool["resources"]
            ],
        }

    def _prepare_target(
        self,
        raw: object,
        *,
        field: str,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise self._invalid(
                "Application target path must be an object",
                "应用目标必须是对象",
                field=field,
                code="builtin_tool_application_target_invalid",
            )
        self._require_keys(raw, _TARGET_KEYS, field=field)
        scope_type = str(raw.get("target_scope_type") or "").strip()
        if scope_type not in _APPLICATION_TARGET_SCOPE_TYPES:
            raise self._invalid(
                "Application target scope type is invalid",
                "应用目标范围只能为环境、基地或车间叶子",
                field=f"{field}.target_scope_type",
                code="builtin_tool_application_target_invalid",
            )
        environment_code = str(raw.get("environment_code") or "").strip()
        base_code = str(raw.get("base_code") or "").strip()
        workshop_code = str(raw.get("workshop_code") or "").strip()
        environment_id, base_id, workshop_id = self._resolve_target(
            target_scope_type=scope_type,
            environment_code=environment_code,
            base_code=base_code,
            workshop_code=workshop_code,
            field=field,
        )
        environment = self.topology.get_environment(str(environment_id))
        base = self.topology.get_base(str(base_id)) if base_id else None
        workshop = self.topology.get_workshop(str(workshop_id)) if workshop_id else None
        if (
            str(environment.get("status") or "") != "enabled"
            or (base is not None and str(base.get("status") or "") != "enabled")
            or (workshop is not None and str(workshop.get("status") or "") != "enabled")
            or not self._is_leaf_target(
                scope_type=scope_type,
                environment_id=str(environment_id),
                base_id=str(base_id or ""),
            )
        ):
            raise self._invalid(
                "Application target must be an enabled topology leaf",
                "应用目标必须是当前启用的真实叶子节点",
                field=field,
                code="builtin_tool_application_target_invalid",
            )
        target = {
            "target_scope_type": scope_type,
            "target_key": self._target_key(
                scope_type,
                str(environment_id),
                str(base_id) if base_id else None,
                str(workshop_id) if workshop_id else None,
            ),
            "environment_id": str(environment_id),
            "base_id": str(base_id) if base_id else None,
            "workshop_id": str(workshop_id) if workshop_id else None,
            "environment_code": environment_code,
            "base_code": base_code,
            "workshop_code": workshop_code,
            "environment_revision": int(environment.get("revision") or 0),
            "base_revision": int((base or {}).get("revision") or 0),
            "workshop_revision": int((workshop or {}).get("revision") or 0),
        }
        target["target_hash"] = snapshot_hash(target)
        return target

    def _is_leaf_target(
        self,
        *,
        scope_type: str,
        environment_id: str,
        base_id: str,
    ) -> bool:
        if scope_type == "workshop":
            return True
        if scope_type == "base":
            row = self.database.execute_one(
                """
                select count(*) as count
                  from platform_workshop
                 where base_id = ? and status = 'enabled'
                """,
                (base_id,),
            )
            return bool(row and int(row["count"]) == 0)
        row = self.database.execute_one(
            """
            select count(*) as count
              from platform_base
             where environment_id = ? and status = 'enabled'
            """,
            (environment_id,),
        )
        return bool(row and int(row["count"]) == 0)

    def _prepare_mapping(
        self,
        *,
        definition: Any,
        raw: object,
        field: str,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise self._invalid(
                "Application Resource Mapping must be an object",
                "应用资源映射必须是对象",
                field=field,
            )
        self._require_keys(raw, _MAPPING_KEYS, field=field)
        slot_code = str(raw.get("resource_slot") or "").strip()
        slots = {slot.code: slot for slot in definition.resource_slots}
        slot = slots.get(slot_code)
        if slot is None:
            raise self._invalid(
                "Application Resource Mapping uses an undeclared Tool slot",
                "资源映射使用了工具未声明的资源槽",
                field=f"{field}.resource_slot",
            )
        target_scope_type = str(raw.get("target_scope_type") or "").strip()
        if target_scope_type not in _TARGET_SCOPE_TYPES:
            raise self._invalid(
                "Application Resource Mapping target scope is invalid",
                "资源映射目标范围无效",
                field=f"{field}.target_scope_type",
            )
        if target_scope_type != "global" and target_scope_type not in set(slot.allowed_scope_types):
            raise self._invalid(
                "Tool slot does not allow the selected target scope",
                "工具资源槽不允许所选目标范围",
                field=f"{field}.target_scope_type",
            )
        environment_id, base_id, workshop_id = self._resolve_target(
            target_scope_type=target_scope_type,
            environment_code=str(raw.get("environment_code") or "").strip(),
            base_code=str(raw.get("base_code") or "").strip(),
            workshop_code=str(raw.get("workshop_code") or "").strip(),
            field=field,
        )
        placement_value = validate_resource_placement(raw.get("placement"))
        placement = placement_value.value if placement_value is not None else None
        resource = self._require_resource_revision(
            revision_id=str(raw.get("resource_revision_id") or "").strip(),
            resource_kind=str(slot.resource_kind),
            target_scope_type=target_scope_type,
            environment_id=environment_id,
            base_id=base_id,
            workshop_id=workshop_id,
            field=f"{field}.resource_revision_id",
        )
        if str(slot.resource_kind) == "loki" and placement is not None:
            raise self._invalid(
                "Loki Resource Mapping cannot declare placement",
                "Loki 资源映射不能配置 cloud/edge",
                field=f"{field}.placement",
            )
        workshop_policy_id = str(raw.get("workshop_partition_policy_revision_id") or "").strip()
        loki_policy_id = str(raw.get("loki_scope_policy_revision_id") or "").strip()
        if workshop_policy_id and loki_policy_id:
            raise self._invalid(
                "A Resource Mapping cannot use both Workshop and Loki policies",
                "同一资源映射不能同时绑定车间分区策略和 Loki 范围策略",
                field=field,
            )
        if workshop_policy_id:
            self._require_workshop_policy(
                revision_id=workshop_policy_id,
                resource_kind=str(slot.resource_kind),
                workshop_id=workshop_id,
                field=f"{field}.workshop_partition_policy_revision_id",
            )
        if loki_policy_id:
            self._require_loki_policy(
                revision_id=loki_policy_id,
                resource_revision_id=str(resource["id"]),
                environment_id=environment_id,
                base_id=base_id,
                resource_kind=str(slot.resource_kind),
                field=f"{field}.loki_scope_policy_revision_id",
            )
        mapping = {
            "resource_slot": slot_code,
            "target_scope_type": target_scope_type,
            "target_key": self._target_key(
                target_scope_type,
                environment_id,
                base_id,
                workshop_id,
            ),
            "environment_id": environment_id,
            "base_id": base_id,
            "workshop_id": workshop_id,
            "placement": placement,
            "resource_revision_id": str(resource["id"]),
            "workshop_partition_policy_revision_id": workshop_policy_id,
            "loki_scope_policy_revision_id": loki_policy_id,
        }
        mapping["mapping_hash"] = snapshot_hash(mapping)
        return mapping

    def _revalidate_stored_mapping(
        self,
        mapping: dict[str, Any],
        *,
        definition: Any,
        field: str,
    ) -> dict[str, Any]:
        resource = self.database.execute_one(
            """
            select rr.id, rr.status as revision_status, r.status as resource_status,
                   r.resource_kind, r.scope_type, r.environment_id, r.base_id,
                   r.workshop_id
              from platform_resource_revision rr
              join platform_resource r on r.id = rr.resource_id
             where rr.id = ?
            """,
            (str(mapping.get("resource_revision_id") or ""),),
        )
        if (
            resource is None
            or str(resource["revision_status"]) != "PUBLISHED"
            or str(resource["resource_status"]) != "enabled"
        ):
            raise self._invalid(
                "Stored Resource Revision is not Published",
                "资源 Revision 已不可用于发布",
                field=f"{field}.resource_revision_id",
                code="builtin_tool_resource_mapping_missing",
            )
        slot_code = str(mapping.get("resource_slot") or "")
        slots = {slot.code: slot for slot in definition.resource_slots}
        slot = slots.get(slot_code)
        target_scope_type = str(mapping.get("target_scope_type") or "")
        if (
            slot is None
            or str(resource["resource_kind"]) != str(slot.resource_kind)
            or (
                target_scope_type != "global"
                and target_scope_type not in set(slot.allowed_scope_types)
            )
            or not self._resource_covers_target(
                resource=resource,
                target_scope_type=target_scope_type,
                environment_id=str(mapping.get("environment_id") or "") or None,
                base_id=str(mapping.get("base_id") or "") or None,
                workshop_id=str(mapping.get("workshop_id") or "") or None,
            )
        ):
            raise self._invalid(
                "Stored Resource Mapping no longer matches its Tool slot and target",
                "资源映射与工具资源槽或业务目标不匹配",
                field=field,
            )
        placement_value = validate_resource_placement(mapping.get("placement"))
        if str(resource["resource_kind"]) == "loki" and placement_value is not None:
            raise self._invalid(
                "Loki Resource Mapping cannot declare placement",
                "Loki 资源映射不能配置 cloud/edge",
                field=f"{field}.placement",
            )
        workshop_policy_id = str(mapping.get("workshop_partition_policy_revision_id") or "")
        loki_policy_id = str(mapping.get("loki_scope_policy_revision_id") or "")
        if workshop_policy_id:
            self._require_workshop_policy(
                revision_id=workshop_policy_id,
                resource_kind=str(resource["resource_kind"]),
                workshop_id=str(mapping.get("workshop_id") or "") or None,
                field=f"{field}.workshop_partition_policy_revision_id",
            )
        if loki_policy_id:
            self._require_loki_policy(
                revision_id=loki_policy_id,
                resource_revision_id=str(resource["id"]),
                environment_id=str(mapping.get("environment_id") or "") or None,
                base_id=str(mapping.get("base_id") or "") or None,
                resource_kind=str(resource["resource_kind"]),
                field=f"{field}.loki_scope_policy_revision_id",
            )
        exact = {
            "resource_slot": str(mapping["resource_slot"]),
            "target_scope_type": str(mapping["target_scope_type"]),
            "target_key": str(mapping["target_key"]),
            "environment_id": str(mapping.get("environment_id") or "") or None,
            "base_id": str(mapping.get("base_id") or "") or None,
            "workshop_id": str(mapping.get("workshop_id") or "") or None,
            "placement": str(mapping.get("placement") or "") or None,
            "resource_revision_id": str(mapping["resource_revision_id"]),
            "workshop_partition_policy_revision_id": workshop_policy_id,
            "loki_scope_policy_revision_id": loki_policy_id,
        }
        expected_hash = snapshot_hash(exact)
        if expected_hash != str(mapping.get("mapping_hash") or ""):
            raise self._invalid(
                "Stored Resource Mapping hash mismatch",
                "资源映射完整性校验失败",
                field=field,
            )
        exact["mapping_hash"] = expected_hash
        return exact

    def _require_exact_envelope(
        self,
        *,
        agent_publication_id: str,
        tool_release_id: str,
        require_active: bool,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select envelope.*, release.status as release_status,
                   installation.installation_status,
                   installation.implementation_digest as installed_digest
              from agent_publication_builtin_tool envelope
              join builtin_tool_release release
                on release.id = envelope.tool_release_id
              left join builtin_tool_installation installation
                on installation.tool_identifier = envelope.tool_identifier
               and installation.handler_version = envelope.handler_version
             where envelope.agent_publication_id = ?
               and envelope.tool_release_id = ?
            """,
            (agent_publication_id, tool_release_id),
        )
        if row is None:
            raise self._invalid(
                "Built-in Tool Release is outside the exact Agent Envelope",
                "所选内置工具不在当前 Agent 发布信封中",
                field="builtin_tools.tool_release_id",
            )
        if require_active and str(row["release_status"]) != "ACTIVE":
            raise self._invalid(
                "Built-in Tool Release is not ACTIVE for a new publication",
                "所选内置工具 Release 已不可用于新发布",
                field="builtin_tools.tool_release_id",
            )
        if str(row.get("installation_status") or "") != "INSTALLED" or str(
            row.get("installed_digest") or ""
        ) != str(row["implementation_digest"]):
            raise self._invalid(
                "Exact built-in Tool implementation is not installed",
                "所选内置工具的精确代码实现不可用",
                field="builtin_tools.tool_release_id",
            )
        return dict(row)

    def _require_exact_definition(self, envelope: dict[str, Any]) -> Any:
        try:
            definition = self.registry.require(
                str(envelope["tool_identifier"]),
                str(envelope["handler_version"]),
            )
        except HandlerRegistryError as exc:
            raise self._invalid(
                str(exc),
                "代码中不存在所选内置工具的精确版本",
                field="builtin_tools.tool_release_id",
            ) from exc
        if definition.implementation_digest != str(
            envelope["implementation_digest"]
        ) or definition.public_schema_hash != str(envelope["public_schema_hash"]):
            raise self._invalid(
                "Installed built-in Tool digest or schema differs from its envelope",
                "内置工具代码摘要或公开 Schema 与发布信封不一致",
                field="builtin_tools.tool_release_id",
            )
        return definition

    def _require_resource_revision(
        self,
        *,
        revision_id: str,
        resource_kind: str,
        target_scope_type: str,
        environment_id: str | None,
        base_id: str | None,
        workshop_id: str | None,
        field: str,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select rr.*, r.resource_kind, r.scope_type, r.environment_id,
                   r.base_id, r.workshop_id, r.status as resource_status
              from platform_resource_revision rr
              join platform_resource r on r.id = rr.resource_id
             where rr.id = ?
            """,
            (revision_id,),
        )
        if (
            row is None
            or str(row["status"]) != "PUBLISHED"
            or str(row["resource_status"]) != "enabled"
        ):
            raise self._invalid(
                "Resource Revision is not Published and enabled",
                "资源 Revision 不存在或不可用于发布",
                field=field,
            )
        if str(row["resource_kind"]) != resource_kind:
            raise self._invalid(
                "Resource kind does not match the Tool slot",
                "资源类型与工具资源槽不匹配",
                field=field,
            )
        if not self._resource_covers_target(
            resource=row,
            target_scope_type=target_scope_type,
            environment_id=environment_id,
            base_id=base_id,
            workshop_id=workshop_id,
        ):
            raise self._invalid(
                "Resource scope does not cover the Mapping target",
                "资源范围不能覆盖所选业务目标",
                field=field,
            )
        return dict(row)

    @staticmethod
    def _resource_covers_target(
        *,
        resource: dict[str, Any],
        target_scope_type: str,
        environment_id: str | None,
        base_id: str | None,
        workshop_id: str | None,
    ) -> bool:
        resource_scope = str(resource["scope_type"])
        if target_scope_type == "global":
            return resource_scope == "global"
        if resource_scope == "global":
            return True
        if str(resource.get("environment_id") or "") != str(environment_id or ""):
            return False
        if resource_scope == "environment":
            return True
        if resource_scope == "base":
            return target_scope_type in {"base", "workshop"} and str(
                resource.get("base_id") or ""
            ) == str(base_id or "")
        if resource_scope == "workshop":
            return target_scope_type == "workshop" and str(
                resource.get("workshop_id") or ""
            ) == str(workshop_id or "")
        return False

    def _require_workshop_policy(
        self,
        *,
        revision_id: str,
        resource_kind: str,
        workshop_id: str | None,
        field: str,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select revision.status, revision.content_hash,
                   revision.database_rule_enabled,
                   revision.redis_rule_enabled, policy.status as policy_status,
                   policy.workshop_id
              from workshop_partition_policy_revision revision
              join workshop_partition_policy policy
                on policy.id = revision.policy_id
             where revision.id = ?
            """,
            (revision_id,),
        )
        rule_enabled = bool(
            row
            and (
                (resource_kind == "database" and int(row["database_rule_enabled"]) == 1)
                or (resource_kind == "redis" and int(row["redis_rule_enabled"]) == 1)
            )
        )
        if (
            row is None
            or str(row["status"]) != "PUBLISHED"
            or str(row["policy_status"]) != "enabled"
            or not workshop_id
            or str(row["workshop_id"]) != workshop_id
            or not rule_enabled
        ):
            raise self._invalid(
                "Workshop Partition Policy Revision is not applicable",
                "车间分区策略 Revision 不存在、未发布或不适用于该资源",
                field=field,
                code="builtin_tool_policy_not_published",
            )
        return dict(row)

    def _require_loki_policy(
        self,
        *,
        revision_id: str,
        resource_revision_id: str,
        environment_id: str | None,
        base_id: str | None,
        resource_kind: str,
        field: str,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select revision.status, revision.content_hash,
                   revision.resource_revision_id,
                   policy.status as policy_status, policy.environment_id,
                   policy.base_id
              from loki_scope_policy_revision revision
              join loki_scope_policy policy on policy.id = revision.policy_id
             where revision.id = ?
            """,
            (revision_id,),
        )
        if (
            resource_kind != "loki"
            or row is None
            or str(row["status"]) != "PUBLISHED"
            or str(row["policy_status"]) != "enabled"
            or str(row["resource_revision_id"]) != resource_revision_id
            or str(row["environment_id"]) != str(environment_id or "")
            or (row.get("base_id") is not None and str(row["base_id"]) != str(base_id or ""))
        ):
            raise self._invalid(
                "Loki Scope Policy Revision is not applicable",
                "Loki 范围策略 Revision 不存在、未发布或不适用于该资源",
                field=field,
                code="builtin_tool_policy_not_published",
            )
        return dict(row)

    def _resolve_target(
        self,
        *,
        target_scope_type: str,
        environment_code: str,
        base_code: str,
        workshop_code: str,
        field: str,
    ) -> tuple[str | None, str | None, str | None]:
        required = {
            "global": (False, False, False),
            "environment": (True, False, False),
            "base": (True, True, False),
            "workshop": (True, True, True),
        }[target_scope_type]
        supplied = (bool(environment_code), bool(base_code), bool(workshop_code))
        if supplied != required:
            raise self._invalid(
                "Application Resource Mapping target path shape is invalid",
                "资源映射目标路径与范围层级不一致",
                field=field,
            )
        if target_scope_type == "global":
            return None, None, None
        try:
            return self.topology.resolve_scope_ids(
                environment_code=environment_code,
                base_code=base_code or None,
                workshop_code=workshop_code or None,
            )
        except NotFound as exc:
            raise self._invalid(
                str(exc),
                "资源映射引用的业务目标不存在",
                field=field,
            ) from exc

    def _publication_facts(
        self,
        application_publication_id: str,
    ) -> list[dict[str, Any]]:
        tools = self.database.execute(
            """
            select * from business_application_publication_builtin_tool
             where application_publication_id = ?
             order by tool_identifier
            """,
            (application_publication_id,),
        )
        result: list[dict[str, Any]] = []
        for tool in tools:
            resources = self.database.execute(
                """
                select *
                  from business_application_publication_builtin_tool_resource
                 where application_tool_id = ?
                 order by resource_slot, target_scope_type, target_key,
                          placement_key
                """,
                (str(tool["id"]),),
            )
            result.append(
                self.snapshot_tool(
                    {
                        **tool,
                        "agent_publication_tool_id": tool["agent_publication_tool_id"],
                        "selection_hash": tool["allowlist_hash"],
                        "resources": [
                            {
                                **resource,
                                "environment_id": resource.get("environment_id"),
                                "base_id": resource.get("base_id"),
                                "workshop_id": resource.get("workshop_id"),
                                "placement": resource.get("placement"),
                                "workshop_partition_policy_revision_id": str(
                                    resource.get("workshop_partition_policy_revision_id") or ""
                                ),
                                "loki_scope_policy_revision_id": str(
                                    resource.get("loki_scope_policy_revision_id") or ""
                                ),
                            }
                            for resource in resources
                        ],
                    }
                )
            )
        return result

    def _publication_target_facts(
        self,
        application_publication_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select target.*, environment.code as environment_code,
                   environment.revision as environment_revision,
                   base.code as base_code, base.revision as base_revision,
                   workshop.code as workshop_code,
                   workshop.revision as workshop_revision
              from business_application_publication_target target
              join platform_environment environment
                on environment.id = target.environment_id
              left join platform_base base on base.id = target.base_id
              left join platform_workshop workshop
                on workshop.id = target.workshop_id
             where target.application_publication_id = ?
             order by target.target_key
            """,
            (application_publication_id,),
        )
        return self.snapshot_targets(
            [
                {
                    **row,
                    "base_id": str(row.get("base_id") or "") or None,
                    "workshop_id": str(row.get("workshop_id") or "") or None,
                    "environment_code": str(row["environment_code"]),
                    "base_code": str(row.get("base_code") or ""),
                    "workshop_code": str(row.get("workshop_code") or ""),
                    "environment_revision": int(row["environment_revision"]),
                    "base_revision": int(row.get("base_revision") or 0),
                    "workshop_revision": int(row.get("workshop_revision") or 0),
                }
                for row in rows
            ]
        )

    def _publication_resolution_set(
        self,
        application_publication_id: str,
    ) -> dict[str, Any] | None:
        resolution_set = self.database.execute_one(
            """
            select schema_version, resolution_count, resolution_set_hash
              from business_application_publication_builtin_tool_resolution_set
             where application_publication_id = ?
            """,
            (application_publication_id,),
        )
        if resolution_set is None:
            return None
        rows = self.database.execute(
            """
            select *
              from business_application_publication_builtin_tool_resolution
             where application_publication_id = ?
             order by resolution_order
            """,
            (application_publication_id,),
        )
        resolutions = [
            {
                "tool_identifier": row["tool_identifier"],
                "tool_release_id": row["tool_release_id"],
                "handler_version": row["handler_version"],
                "implementation_digest": row["implementation_digest"],
                "resource_slot": row["resource_slot"],
                "target_scope_type": row["target_scope_type"],
                "target_key": row["target_key"],
                "target_hash": row["target_hash"],
                "environment_id": row["environment_id"],
                "base_id": row.get("base_id"),
                "workshop_id": row.get("workshop_id"),
                "placement": row.get("placement"),
                "resource_revision_id": row["resource_revision_id"],
                "resource_content_hash": row["resource_content_hash"],
                "resource_kind": row["resource_kind"],
                "resource_scope_type": row["resource_scope_type"],
                "workshop_partition_policy_revision_id": str(
                    row.get("workshop_partition_policy_revision_id") or ""
                ),
                "workshop_partition_policy_hash": str(
                    row.get("workshop_partition_policy_hash") or ""
                ),
                "loki_scope_policy_revision_id": str(
                    row.get("loki_scope_policy_revision_id") or ""
                ),
                "loki_scope_policy_hash": str(row.get("loki_scope_policy_hash") or ""),
                "mapping_hash": row["mapping_hash"],
                "resolution_hash": row["resolution_hash"],
            }
            for row in rows
        ]
        if int(resolution_set["resolution_count"]) != len(resolutions):
            raise self._invalid(
                "Application resolution count does not match persisted rows",
                "业务应用发布版本的资源解析表计数不一致",
                field="builtin_tool_resolution_set",
                code="publication_binding_conflict",
            )
        persisted = {
            "schema_version": int(resolution_set["schema_version"]),
            "resolution_count": int(resolution_set["resolution_count"]),
            "resolution_set_hash": str(resolution_set["resolution_set_hash"]),
            "resolutions": resolutions,
        }
        if self.prepare_resolution_set(resolutions) != persisted:
            raise self._invalid(
                "Application resolution set hash does not match persisted rows",
                "业务应用发布版本的资源解析表完整性校验失败",
                field="builtin_tool_resolution_set",
                code="publication_binding_conflict",
            )
        return persisted

    @staticmethod
    def _mapping_covers_target(
        mapping: dict[str, Any],
        target: dict[str, Any],
    ) -> bool:
        scope_type = str(mapping["target_scope_type"])
        if scope_type == "global":
            return True
        if str(mapping.get("environment_id") or "") != str(target.get("environment_id") or ""):
            return False
        if scope_type == "environment":
            return True
        if str(mapping.get("base_id") or "") != str(target.get("base_id") or ""):
            return False
        if scope_type == "base":
            return True
        return str(mapping.get("workshop_id") or "") == str(target.get("workshop_id") or "")

    def _published_resource_fact(
        self,
        resource_revision_id: str,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select revision.id, revision.status as revision_status,
                   revision.content_hash as resource_content_hash,
                   resource.status as resource_status,
                   resource.resource_kind, resource.scope_type,
                   resource.environment_id, resource.base_id,
                   resource.workshop_id
              from platform_resource_revision revision
              join platform_resource resource
                on resource.id = revision.resource_id
             where revision.id = ?
            """,
            (resource_revision_id,),
        )
        if (
            row is None
            or str(row["revision_status"]) != "PUBLISHED"
            or str(row["resource_status"]) != "enabled"
        ):
            raise self._invalid(
                "Resource Revision is no longer Published",
                "资源 Revision 已不可用于发布",
                field="builtin_tools.resources.resource_revision_id",
                code="builtin_tool_resource_mapping_missing",
            )
        return dict(row)

    def _validate_matrix_policy(
        self,
        *,
        mapping: dict[str, Any],
        target: dict[str, Any],
        resource: dict[str, Any],
        field: str,
    ) -> dict[str, str]:
        resource_kind = str(resource["resource_kind"])
        workshop_policy_id = str(mapping.get("workshop_partition_policy_revision_id") or "")
        loki_policy_id = str(mapping.get("loki_scope_policy_revision_id") or "")
        workshop_policy_hash = ""
        loki_policy_hash = ""
        if (
            resource_kind in {"database", "redis"}
            and str(target["target_scope_type"]) == "workshop"
            and str(resource["scope_type"]) != "workshop"
        ):
            if not workshop_policy_id:
                raise self._invalid(
                    "Shared Workshop Resource Mapping requires a Published Policy Revision",
                    "共享数据库或 Redis 的车间目标缺少已发布分区策略",
                    field=field,
                    code="builtin_tool_policy_not_published",
                )
        if workshop_policy_id:
            policy = self._require_workshop_policy(
                revision_id=workshop_policy_id,
                resource_kind=resource_kind,
                workshop_id=str(target.get("workshop_id") or "") or None,
                field=field,
            )
            workshop_policy_hash = str(policy["content_hash"])
        if resource_kind == "loki":
            if str(mapping["target_scope_type"]) == "workshop":
                raise self._invalid(
                    "Loki Mapping cannot bind a Workshop target",
                    "Loki 映射只能锚定环境或基地范围，不能绑定车间",
                    field=field,
                    code="builtin_tool_resource_mapping_overlap",
                )
            if not loki_policy_id:
                raise self._invalid(
                    "Loki Mapping requires a Published Scope Policy Revision",
                    "Loki 映射缺少已发布范围策略",
                    field=field,
                    code="builtin_tool_policy_not_published",
                )
            policy = self._require_loki_policy(
                revision_id=loki_policy_id,
                resource_revision_id=str(resource["id"]),
                environment_id=str(target["environment_id"]),
                base_id=str(target.get("base_id") or "") or None,
                resource_kind=resource_kind,
                field=field,
            )
            loki_policy_hash = str(policy["content_hash"])
        return {
            "workshop_partition_policy_hash": workshop_policy_hash,
            "loki_scope_policy_hash": loki_policy_hash,
        }

    @staticmethod
    def _mapping_sort_key(value: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(value["resource_slot"]),
            str(value["target_scope_type"]),
            str(value["target_key"]),
            str(value.get("placement") or ""),
        )

    def _require_unique_mappings(
        self,
        resources: list[dict[str, Any]],
        *,
        field: str,
    ) -> None:
        keys = [
            (
                str(value["resource_slot"]),
                str(value["target_key"]),
                str(value.get("placement") or ""),
            )
            for value in resources
        ]
        if len(keys) != len(set(keys)):
            raise self._invalid(
                "Duplicate Application Resource Mapping target",
                "同一工具资源槽、目标和 placement 不能重复配置",
                field=field,
            )

    @staticmethod
    def _target_key(
        target_scope_type: str,
        environment_id: str | None,
        base_id: str | None,
        workshop_id: str | None,
    ) -> str:
        if target_scope_type == "global":
            return "global"
        values = [f"environment:{environment_id}"]
        if base_id:
            values.append(f"base:{base_id}")
        if workshop_id:
            values.append(f"workshop:{workshop_id}")
        return "/".join(values)

    def _require_keys(
        self,
        value: dict[str, Any],
        allowed: frozenset[str],
        *,
        field: str,
    ) -> None:
        unknown = sorted(set(value).difference(allowed))
        if unknown:
            raise self._invalid(
                f"Unknown Application Resource Mapping fields: {unknown}",
                "内置工具资源映射包含未知字段",
                field=field,
            )

    def _matrix_error(
        self,
        *,
        code: str,
        message: str,
        safe_message: str,
        tool: dict[str, Any],
        slot_code: str,
        target: dict[str, Any],
        candidate_count: int,
    ) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message=safe_message,
            error_code=code,
            field_errors=[
                {
                    "field": (
                        f"builtin_tools.{tool['tool_identifier']}."
                        f"{slot_code}.{target['target_key']}"
                    ),
                    "message": safe_message,
                }
            ],
            diagnostics={
                "tool_identifier": str(tool["tool_identifier"]),
                "tool_release_id": str(tool["tool_release_id"]),
                "resource_slot": slot_code,
                "environment_id": str(target["environment_id"]),
                "base_id": str(target.get("base_id") or ""),
                "workshop_id": str(target.get("workshop_id") or ""),
                "candidate_count": candidate_count,
            },
        )

    @staticmethod
    def _invalid(
        message: str,
        safe_message: str,
        *,
        field: str,
        code: str = "builtin_tool_resource_mapping_invalid",
    ) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message=safe_message,
            error_code=code,
            field_errors=[{"field": field, "message": safe_message}],
        )
