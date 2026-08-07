from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.agent_config.application.builtin_tool_envelope import (
    AgentBuiltinToolEnvelopeService,
)
from app.modules.api_capability.infrastructure import (
    ApiCapabilityRepository,
    CapabilityPublicationRepository,
)
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.internal_tools.application.legacy_migration import (
    BuiltinToolLegacyWriteGuard,
)
from app.modules.model_connection.application import ModelConnectionService
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NotFound, NonRetryableExecutionError


DEFAULT_AGENT_CODE = "default-diagnostic-agent"
FORBIDDEN_CONFIG_KEYS = {
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "bash",
    "write",
    "edit",
    "shell",
    "system_prompt",
    "safety_rules",
    "base_url",
    "provider_url",
}
ALLOWED_CONFIG_KEYS = {
    "business_role",
    "business_instructions",
    "model_policy",
    "execution",
    # Service-level compatibility accepts only an empty historical field; the
    # HTTP write schema no longer exposes it and the write guard rejects names.
    "tools",
    "skills",
    "routing",
    "channels",
    "api_capability_release_ids",
    "builtin_tool_release_ids",
}
FORBIDDEN_INSTRUCTION_PATTERNS = (
    "ignore safety",
    "ignore permission",
    "bypass permission",
    "execute bash",
    "write database",
    "modify database",
    "reveal secret",
    "忽略安全",
    "绕过权限",
    "修改数据库",
    "泄露密钥",
)


class AgentConfigService:
    def __init__(
        self,
        repository: AgentConfigRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        skill_loader: SkillLoader,
        model_connection_service: ModelConnectionService | None = None,
        allowed_models: set[str] | None = None,
        api_capability_repository: ApiCapabilityRepository | None = None,
        capability_publication_repository: (CapabilityPublicationRepository | None) = None,
        builtin_tool_envelopes: AgentBuiltinToolEnvelopeService | None = None,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.skill_loader = skill_loader
        self.model_connection_service = model_connection_service
        self.allowed_models = allowed_models or {"claude-sonnet-4-20250514"}
        self.api_capability_repository = api_capability_repository
        self.capability_publication_repository = capability_publication_repository
        self.builtin_tool_envelopes = builtin_tool_envelopes

    def get(self, agent_code: str = DEFAULT_AGENT_CODE) -> dict[str, Any]:
        definition = self.repository.get_definition(agent_code)
        latest = self.repository.latest_revision(str(definition["id"]))
        current = None
        if definition.get("current_publication_id"):
            current = self.repository.get_publication(str(definition["current_publication_id"]))
        return {
            "definition": definition,
            "draft": latest,
            "current_publication": current,
            "catalog": self.catalog(),
            "management_mode": (
                "editable" if definition["code"] == DEFAULT_AGENT_CODE else "read_only"
            ),
            "model_connections": (
                self.model_connection_service.list_connections()
                if self.model_connection_service is not None
                else []
            ),
        }

    def list_agents(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for definition in self.repository.list_definitions():
            publication = None
            if definition.get("current_publication_id"):
                publication = self.repository.get_publication(
                    str(definition["current_publication_id"])
                )
            model_connection = (
                (publication.get("snapshot") or {}).get("model_connection") or {}
                if publication
                else {}
            )
            model_status = "legacy_global_connection"
            if model_connection and self.model_connection_service is not None:
                try:
                    model_status = str(
                        self.model_connection_service.public_revision(
                            str(model_connection.get("revision_id") or "")
                        ).get("status")
                        or "unavailable"
                    )
                except NotFound:
                    model_status = "missing_revision"
            usage = (
                self.model_connection_service.repository.active_application_usage(
                    str(publication["id"])
                )
                if publication and self.model_connection_service is not None
                else []
            )
            values.append(
                {
                    **definition,
                    "management_mode": (
                        "editable" if definition["code"] == DEFAULT_AGENT_CODE else "read_only"
                    ),
                    "current_publication": (
                        {
                            "id": publication["id"],
                            "revision": publication["revision"],
                            "config_hash": publication["config_hash"],
                        }
                        if publication
                        else None
                    ),
                    "model_connection_status": model_status,
                    "active_application_count": len(usage),
                }
            )
        return values

    def skill_catalog(self) -> list[dict[str, Any]]:
        return self.skill_loader.catalog()

    def catalog(self) -> dict[str, Any]:
        return {
            "models": sorted(self.allowed_models),
            "tools": sorted(self.repository.enabled_tools() & ToolRegistry.READONLY_TOOLS),
            "skills": sorted(self.skill_loader.load()),
            "connectors": self.repository.connector_catalog(),
            "api_capabilities": (
                self.api_capability_repository.list_catalog(selectable_only=True)
                if self.api_capability_repository is not None
                else []
            ),
            "builtin_tool_releases": (
                self.builtin_tool_envelopes.catalog()
                if self.builtin_tool_envelopes is not None
                else []
            ),
        }

    def save_draft(
        self,
        *,
        actor_id: str,
        agent_code: str,
        expected_revision: int,
        config: dict[str, Any],
        correlation_id: str = "",
    ) -> dict[str, Any]:
        BuiltinToolLegacyWriteGuard(
            self.repository.database
        ).reject_agent_name_bindings(
            config.get("tools"),
            source_id=agent_code,
            correlation_id=correlation_id,
        )
        return self._save_draft(
            actor_id=actor_id,
            agent_code=agent_code,
            expected_revision=expected_revision,
            config=config,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _save_draft(
        self,
        *,
        actor_id: str,
        agent_code: str,
        expected_revision: int,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_mvp_write_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
        )
        definition = self.repository.get_definition(agent_code)
        raw_errors = self._validate_shape(config)
        if raw_errors:
            raise NonRetryableExecutionError(
                "Agent configuration shape is invalid",
                safe_message="Agent 配置无效",
                error_code="validation_failed",
                field_errors=raw_errors,
            )
        normalized = self._normalize(config)
        with self.repository.database.unit_of_work():
            revision = self.repository.save_draft(
                agent_id=str(definition["id"]),
                expected_revision=expected_revision,
                config=normalized,
                config_hash=_hash(normalized),
                actor_id=actor_id,
            )
        self.audit_service.record(
            "agent.config.draft_saved",
            status="SUCCEEDED",
            summary="Agent draft revision saved",
            actor_id=actor_id,
            payload={
                "agent_code": agent_code,
                "revision": revision["revision"],
                "config_hash": revision["config_hash"],
            },
        )
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def validate_revision(
        self, *, actor_id: str, agent_code: str, revision_id: str
    ) -> dict[str, Any]:
        self._require_mvp_write_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
        )
        definition = self.repository.get_definition(agent_code)
        revision = self.repository.get_revision(revision_id)
        if str(revision["agent_id"]) != str(definition["id"]):
            raise NonRetryableExecutionError(
                "Revision belongs to another Agent",
                safe_message="修订版本不属于此 Agent",
            )
        errors = self._validate_config(revision["config"])
        return self.repository.set_validation(revision_id, valid=not errors, errors=errors)

    def publish(
        self,
        *,
        actor_id: str,
        agent_code: str,
        revision_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        revision = self.repository.get_revision(revision_id)
        BuiltinToolLegacyWriteGuard(
            self.repository.database
        ).reject_agent_name_bindings(
            (revision.get("config") or {}).get("tools"),
            source_id=revision_id,
            correlation_id=correlation_id,
        )
        return self._publish(
            actor_id=actor_id,
            agent_code=agent_code,
            revision_id=revision_id,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _publish(
        self,
        *,
        actor_id: str,
        agent_code: str,
        revision_id: str,
    ) -> dict[str, Any]:
        self._require_mvp_write_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
        )
        definition = self.repository.get_definition(agent_code)
        revision = self.repository.get_revision(revision_id)
        if str(revision["agent_id"]) != str(definition["id"]):
            raise NonRetryableExecutionError(
                "Revision belongs to another Agent",
                safe_message="修订版本不属于此 Agent",
            )
        existing = self.repository.publication_for_revision(
            agent_id=str(definition["id"]),
            revision_id=revision_id,
        )
        if existing is not None:
            if str(definition.get("current_publication_id") or "") == str(existing["id"]):
                self.repository.mark_revision_published(revision_id)
                return self._verified_publication(existing)
            raise NonRetryableExecutionError(
                "Agent revision was already published and is no longer current",
                safe_message="该修订版本已经发布；如需重新启用，请在发布历史中回退到该版本",
                error_code="revision_already_published",
            )
        revision = self.validate_revision(
            actor_id=actor_id, agent_code=agent_code, revision_id=revision_id
        )
        errors = revision["validation"].get("errors") or []
        if errors:
            raise NonRetryableExecutionError(
                "Agent configuration validation failed",
                safe_message="Agent 配置无效",
                error_code="validation_failed",
                field_errors=errors,
            )
        with self.repository.database.unit_of_work():
            snapshot = dict(revision["config"])
            release_ids = list(snapshot.pop("api_capability_release_ids", []) or [])
            builtin_tool_release_ids = list(snapshot.pop("builtin_tool_release_ids", []) or [])
            builtin_tool_envelope = (
                self.builtin_tool_envelopes.prepare(builtin_tool_release_ids)
                if self.builtin_tool_envelopes is not None
                else []
            )
            snapshot["builtin_tool_envelope"] = builtin_tool_envelope
            if self.capability_publication_repository is not None:
                snapshot["capability_envelope"] = (
                    self.capability_publication_repository.prepare_agent_envelope(release_ids)
                )
            model_policy = snapshot.get("model_policy") or {}
            connection_revision_id = str(model_policy.get("model_connection_revision_id") or "")
            if self.model_connection_service is not None and not connection_revision_id:
                raise NonRetryableExecutionError(
                    "New Agent publications require a model connection revision",
                    safe_message="发布前请选择状态正常的模型连接",
                    error_code="model_connection_required",
                    field_errors=[
                        {
                            "field": "model_policy.model_connection_revision_id",
                            "message": "必须选择状态正常的模型连接",
                        }
                    ],
                )
            if self.model_connection_service is not None:
                connection_revision = self.model_connection_service.public_revision(
                    connection_revision_id
                )
                if connection_revision["status"] != "ready":
                    raise NonRetryableExecutionError(
                        "Model connection revision is not ready",
                        safe_message="发布前请先轮换模型凭据",
                        error_code="model_connection_rotation_required",
                    )
                snapshot["model_connection"] = {
                    "id": connection_revision["connection_id"],
                    "code": connection_revision["connection_code"],
                    "revision_id": connection_revision["id"],
                    "revision": connection_revision["revision"],
                    "config_hash": connection_revision["config_hash"],
                    "config": connection_revision["config"],
                }
            publication = self.repository.create_publication(
                agent_id=str(definition["id"]),
                revision_id=revision_id,
                revision=int(revision["revision"]),
                snapshot=snapshot,
                config_hash=_hash(snapshot),
                actor_id=actor_id,
            )
            if self.capability_publication_repository is not None:
                self.capability_publication_repository.freeze_agent_envelope(
                    str(publication["id"]),
                    release_ids=release_ids,
                )
                publication = self.repository.get_publication(str(publication["id"]))
            if self.builtin_tool_envelopes is not None:
                self.builtin_tool_envelopes.freeze(
                    agent_publication_id=str(publication["id"]),
                    envelopes=builtin_tool_envelope,
                )
                publication = self.repository.get_publication(str(publication["id"]))
        self.audit_service.record(
            "agent.config.published",
            status="SUCCEEDED",
            summary="Agent publication created",
            actor_id=actor_id,
            payload={
                "agent_code": agent_code,
                "publication_id": publication["id"],
                "revision": publication["revision"],
                "config_hash": publication["config_hash"],
                "model_connection_revision_id": connection_revision_id,
                "model_connection_config_hash": (
                    (snapshot.get("model_connection") or {}).get("config_hash") or ""
                ),
                "provider_host": _provider_host(
                    str(
                        ((snapshot.get("model_connection") or {}).get("config") or {}).get(
                            "base_url"
                        )
                        or ""
                    )
                ),
                "model": str(model_policy.get("model") or ""),
            },
        )
        return publication

    def rollback(self, *, actor_id: str, agent_code: str, publication_id: str) -> dict[str, Any]:
        selected = self.publication(publication_id)
        model_connection = (selected.get("snapshot") or {}).get("model_connection") or {}
        if model_connection and self.model_connection_service is not None:
            self.model_connection_service.runtime_binding(
                str(model_connection.get("revision_id") or "")
            )
        return self._rollback(
            actor_id=actor_id,
            agent_code=agent_code,
            publication_id=publication_id,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _rollback(
        self, *, actor_id: str, agent_code: str, publication_id: str
    ) -> dict[str, Any]:
        self._require_mvp_write_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
        )
        definition = self.repository.get_definition(agent_code)
        publication = self.repository.set_current_publication(
            agent_id=str(definition["id"]), publication_id=publication_id
        )
        self.audit_service.record(
            "agent.config.rolled_back",
            status="SUCCEEDED",
            summary="Agent current publication rolled back",
            actor_id=actor_id,
            payload={
                "agent_code": agent_code,
                "publication_id": publication_id,
                "revision": publication["revision"],
            },
        )
        return publication

    def current_publication(self, agent_code: str) -> dict[str, Any]:
        publication = self.repository.current_publication(agent_code)
        return self._verified_publication(publication)

    def publication(self, publication_id: str) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        return self._verified_publication(publication)

    def _verified_publication(self, publication: dict[str, Any]) -> dict[str, Any]:
        if int(publication.get("schema_version") or 0) != 1:
            raise NonRetryableExecutionError(
                "Unsupported Agent publication schema",
                safe_message="不支持此 Agent 配置结构版本",
            )
        if _hash(publication["snapshot"]) != str(publication["config_hash"]):
            raise NonRetryableExecutionError(
                "Agent publication hash mismatch",
                safe_message="Agent 配置完整性校验失败",
            )
        snapshot = publication["snapshot"]
        if self.builtin_tool_envelopes is not None and "builtin_tool_envelope" in snapshot:
            envelope = snapshot.get("builtin_tool_envelope")
            if not isinstance(envelope, list):
                raise NonRetryableExecutionError(
                    "Agent publication Built-in Tool Envelope is invalid",
                    safe_message="Agent 内置工具发布事实完整性校验失败",
                    error_code="agent_builtin_tool_envelope_hash_mismatch",
                )
            self.builtin_tool_envelopes.verify_frozen(
                agent_publication_id=str(publication["id"]),
                envelopes=envelope,
            )
        return publication

    def connector_allowed(self, *, publication_id: str, direction: str, connector_id: str) -> bool:
        return connector_id in self.repository.publication_connectors(publication_id, direction)

    def publications(self, agent_code: str) -> list[dict[str, Any]]:
        definition = self.repository.get_definition(agent_code)
        values = self.repository.list_publications(str(definition["id"]))
        for publication in values:
            publication["active_applications"] = (
                self.model_connection_service.repository.active_application_usage(
                    str(publication["id"])
                )
                if self.model_connection_service is not None
                else []
            )
            publication["model_runtime_mode"] = (
                "pinned_connection"
                if (publication.get("snapshot") or {}).get("model_connection")
                else "legacy_global_connection"
            )
        return values

    def allowed_tools(self, *, publication_id: str, user_id: str, project_code: str) -> list[str]:
        del user_id, project_code
        assigned = self.repository.publication_tools(publication_id)
        enabled = self.repository.enabled_tools()
        return sorted(ToolRegistry.READONLY_TOOLS & assigned & enabled)

    @staticmethod
    def _require_mvp_write_agent(agent_code: str) -> None:
        if agent_code != DEFAULT_AGENT_CODE:
            raise NonRetryableExecutionError(
                "MVP Agent write attempted for a non-default Agent",
                safe_message="当前管理版本中此 Agent 只能查看，不能编辑",
                error_code="agent_read_only",
            )

    def _normalize(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "business_role": str(config.get("business_role") or "").strip(),
            "business_instructions": str(config.get("business_instructions") or "").strip(),
            "model_policy": dict(config.get("model_policy") or {}),
            "execution": dict(config.get("execution") or {}),
            "skills": sorted({str(item) for item in (config.get("skills") or [])}),
            "routing": dict(config.get("routing") or {}),
            "channels": dict(config.get("channels") or {}),
            "api_capability_release_ids": sorted(
                {
                    str(item).strip()
                    for item in (config.get("api_capability_release_ids") or [])
                    if str(item).strip()
                }
            ),
            "builtin_tool_release_ids": sorted(
                [
                    str(item).strip()
                    for item in (config.get("builtin_tool_release_ids") or [])
                    if str(item).strip()
                ]
            ),
        }
        return normalized

    def _validate_shape(self, config: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for key in sorted(set(config) - ALLOWED_CONFIG_KEYS):
            errors.append({"field": key, "message": "此字段不可配置"})
        release_ids = config.get("api_capability_release_ids") or []
        if not isinstance(release_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in release_ids
        ):
            errors.append(
                {
                    "field": "api_capability_release_ids",
                    "message": "必须是非空 Release ID 数组",
                }
            )
        builtin_release_ids = config.get("builtin_tool_release_ids") or []
        if not isinstance(builtin_release_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in builtin_release_ids
        ):
            errors.append(
                {
                    "field": "builtin_tool_release_ids",
                    "message": "必须是非空 Release ID 数组",
                }
            )
        elif len(builtin_release_ids) != len(set(builtin_release_ids)):
            errors.append(
                {
                    "field": "builtin_tool_release_ids",
                    "message": "Release ID 不得重复",
                }
            )
        nested = {
            "model_policy": {
                "runtime",
                "model",
                "model_connection_revision_id",
            },
            "execution": {"max_turns", "timeout_seconds"},
            "routing": {"project_code"},
            "channels": {"ingress", "delivery"},
        }
        for field, allowed in nested.items():
            value = config.get(field) or {}
            if not isinstance(value, dict):
                errors.append({"field": field, "message": "必须是对象"})
                continue
            for key in sorted(set(value) - allowed):
                errors.append({"field": f"{field}.{key}", "message": "此字段不可配置"})
        return errors

    def _validate_config(self, config: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        serialized = json.dumps(config, ensure_ascii=False).lower()
        for key in FORBIDDEN_CONFIG_KEYS:
            if f'"{key}"' in serialized:
                errors.append({"field": key, "message": "此字段由平台安全策略控制"})
        instructions = str(config.get("business_instructions") or "").lower()
        for pattern in FORBIDDEN_INSTRUCTION_PATTERNS:
            if pattern in instructions:
                errors.append(
                    {
                        "field": "business_instructions",
                        "message": "业务指令与平台安全规则冲突",
                    }
                )
                break
        model_policy = config.get("model_policy") or {}
        model = str(model_policy.get("model") or "") if isinstance(model_policy, dict) else ""
        connection_revision_id = (
            str(model_policy.get("model_connection_revision_id") or "")
            if isinstance(model_policy, dict)
            else ""
        )
        runtime = (
            str(model_policy.get("runtime") or "claude_agent_sdk")
            if isinstance(model_policy, dict)
            else ""
        )
        if runtime != "claude_agent_sdk":
            errors.append(
                {
                    "field": "model_policy.runtime",
                    "message": "仅支持 claude_agent_sdk",
                }
            )
        if connection_revision_id:
            if self.model_connection_service is None:
                errors.append(
                    {
                        "field": "model_policy.model_connection_revision_id",
                        "message": "模型连接服务不可用",
                    }
                )
            else:
                try:
                    connection = self.model_connection_service.public_revision(
                        connection_revision_id
                    )
                except Exception:
                    errors.append(
                        {
                            "field": "model_policy.model_connection_revision_id",
                            "message": "模型连接版本不存在",
                        }
                    )
                else:
                    if connection["status"] != "ready":
                        errors.append(
                            {
                                "field": "model_policy.model_connection_revision_id",
                                "message": "模型连接需要轮换凭据",
                            }
                        )
                    if model != str(connection["config"]["model"]):
                        errors.append(
                            {
                                "field": "model_policy.model",
                                "message": "模型必须与所选模型连接版本一致",
                            }
                        )
        elif model not in self.allowed_models:
            errors.append({"field": "model_policy.model", "message": "模型尚未注册"})
        available_skills = set(self.skill_loader.load())
        for skill_code in config.get("skills") or []:
            if str(skill_code) not in available_skills:
                errors.append(
                    {
                        "field": "skills",
                        "message": f"Skill {skill_code} 尚未注册",
                    }
                )
        channels = config.get("channels") or {}
        if isinstance(channels, dict):
            for direction in ("ingress", "delivery"):
                for connector_id in channels.get(direction) or []:
                    if not self.repository.connector_exists(str(connector_id), direction):
                        errors.append(
                            {
                                "field": f"channels.{direction}",
                                "message": f"连接器 {connector_id} 不可用",
                            }
                        )
        if self.capability_publication_repository is not None:
            try:
                self.capability_publication_repository.prepare_agent_envelope(
                    list(config.get("api_capability_release_ids") or [])
                )
            except (NotFound, NonRetryableExecutionError) as exc:
                errors.append(
                    {
                        "field": "api_capability_release_ids",
                        "message": exc.safe_message,
                    }
                )
        if self.builtin_tool_envelopes is not None:
            try:
                self.builtin_tool_envelopes.prepare(
                    list(config.get("builtin_tool_release_ids") or [])
                )
            except NonRetryableExecutionError as exc:
                errors.append(
                    {
                        "field": "builtin_tool_release_ids",
                        "message": exc.safe_message,
                    }
                )
        execution = config.get("execution") or {}
        if isinstance(execution, dict):
            try:
                max_turns = int(execution.get("max_turns") or 12)
                timeout = int(execution.get("timeout_seconds") or 300)
            except (TypeError, ValueError):
                errors.append({"field": "execution", "message": "执行限制必须是整数"})
                return errors
            if not 1 <= max_turns <= 100:
                errors.append({"field": "execution.max_turns", "message": "必须在 1 到 100 之间"})
            if not 10 <= timeout <= 3600:
                errors.append(
                    {
                        "field": "execution.timeout_seconds",
                        "message": "必须在 10 到 3600 之间",
                    }
                )
        return errors


def _hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _provider_host(base_url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(base_url).hostname or "")[:255]
    except ValueError:
        return ""
