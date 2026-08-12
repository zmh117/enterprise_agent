from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.model_connection.application import ModelConnectionService
from app.modules.model_connection.domain import DEFAULT_MODEL_CONNECTION_CODE
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NotFound, NonRetryableExecutionError


DEFAULT_AGENT_CODE = "default-diagnostic-agent"
SUPPORTED_RUNTIME_KINDS = frozenset({"python-v1", "typescript-v1"})
AGENT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
PROJECT_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
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
    "skills",
    "routing",
    "channels",
    "mcp_tool_ids",
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
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.skill_loader = skill_loader
        self.model_connection_service = model_connection_service
        self.allowed_models = allowed_models or {"claude-sonnet-4-20250514"}

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
            "management_mode": "editable",
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
                    "management_mode": "editable",
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

    def create_agent(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        description: str,
        project_code: str,
        runtime_kind: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        del correlation_id
        return self._create_agent(
            actor_id=actor_id,
            code=code,
            name=name,
            description=description,
            project_code=project_code,
            runtime_kind=runtime_kind,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _create_agent(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        description: str,
        project_code: str,
        runtime_kind: str,
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code="*",
            action="edit",
        )
        normalized = _normalize_definition_fields(
            code=code,
            name=name,
            description=description,
            project_code=project_code,
            runtime_kind=runtime_kind,
        )
        config = self.initial_config(
            name=normalized["name"],
            project_code=normalized["project_code"],
        )
        created = self.repository.create_definition_with_initial_draft(
            code=normalized["code"],
            name=normalized["name"],
            description=normalized["description"],
            project_code=normalized["project_code"],
            runtime_kind=normalized["runtime_kind"],
            classification="business",
            config=config,
            config_hash=_hash(config),
            actor_id=actor_id,
        )
        self.audit_service.record(
            "agent.definition.created",
            status="SUCCEEDED",
            summary="Agent definition and initial draft created",
            actor_id=actor_id,
            payload={
                "agent_code": normalized["code"],
                "runtime_kind": normalized["runtime_kind"],
                "project_code": normalized["project_code"],
                "initial_revision": created["draft"]["revision"],
            },
        )
        return created

    def initial_config(self, *, name: str, project_code: str) -> dict[str, Any]:
        model = sorted(self.allowed_models)[0]
        connection_revision_id = ""
        if self.model_connection_service is not None:
            try:
                connection = self.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
                revision = connection.get("current_revision") or {}
                connection_model = str((revision.get("config") or {}).get("model") or "")
                if connection_model:
                    model = connection_model
                connection_revision_id = str(revision.get("id") or "")
            except NotFound:
                pass
        return build_initial_agent_config(
            name=name,
            project_code=project_code,
            model=model,
            model_connection_revision_id=connection_revision_id,
        )

    def skill_catalog(self) -> list[dict[str, Any]]:
        return self.skill_loader.catalog()

    def catalog(self) -> dict[str, Any]:
        return {
            "models": sorted(self.allowed_models),
            "skills": sorted(self.skill_loader.load()),
            "connectors": self.repository.connector_catalog(),
            "mcp_tools": [
                {
                    "server_code": definition.server_code,
                    "identifier": definition.identifier,
                    "description": definition.description,
                    "schema_hash": definition.schema_hash,
                    "resource_kind": definition.resource_kind,
                    "read_only": definition.read_only,
                }
                for definition in MCP_TOOL_MANIFEST.values()
            ],
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
        del correlation_id
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
        del correlation_id
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
            runtime_kind = str(definition.get("runtime_kind") or "")
            if runtime_kind not in SUPPORTED_RUNTIME_KINDS:
                raise NonRetryableExecutionError(
                    "Agent Definition runtime is unsupported",
                    safe_message="Agent Runtime 配置无效",
                    error_code="agent_runtime_kind_unsupported",
                )
            snapshot["runtime_kind"] = runtime_kind
            tool_ids = list(snapshot.pop("mcp_tool_ids", []) or [])
            mcp_tool_envelope = [
                {
                    "server_code": MCP_TOOL_MANIFEST[identifier].server_code,
                    "tool_identifier": identifier,
                    "schema_hash": MCP_TOOL_MANIFEST[identifier].schema_hash,
                }
                for identifier in tool_ids
            ]
            snapshot["mcp_tool_envelope"] = mcp_tool_envelope
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
                runtime_kind=runtime_kind,
                snapshot=snapshot,
                config_hash=_hash(snapshot),
                actor_id=actor_id,
            )
            self.repository.freeze_mcp_tools(
                agent_publication_id=str(publication["id"]),
                envelopes=mcp_tool_envelope,
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
                "runtime_kind": publication["runtime_kind"],
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
    def _rollback(self, *, actor_id: str, agent_code: str, publication_id: str) -> dict[str, Any]:
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
        schema_version = int(publication.get("schema_version") or 0)
        if schema_version not in {1, 2}:
            raise NonRetryableExecutionError(
                "Unsupported Agent publication schema",
                safe_message="不支持此 Agent 配置结构版本",
                error_code="agent_publication_schema_unsupported",
            )
        if _hash(publication["snapshot"]) != str(publication["config_hash"]):
            raise NonRetryableExecutionError(
                "Agent publication hash mismatch",
                safe_message="Agent 配置完整性校验失败",
                error_code="agent_publication_hash_mismatch",
            )
        snapshot = publication["snapshot"]
        runtime_kind = str(publication.get("runtime_kind") or "")
        definition = self.repository.get_definition_by_id(str(publication["agent_id"]))
        definition_runtime = str(definition.get("runtime_kind") or "")
        if runtime_kind not in SUPPORTED_RUNTIME_KINDS or definition_runtime != runtime_kind:
            raise NonRetryableExecutionError(
                "Agent publication runtime does not match its Definition",
                safe_message="Agent Runtime 发布事实完整性校验失败",
                error_code="agent_publication_runtime_mismatch",
            )
        if schema_version == 1:
            if runtime_kind != "python-v1" or snapshot.get("runtime_kind") not in {
                None,
                "python-v1",
            }:
                raise NonRetryableExecutionError(
                    "Legacy Agent publication runtime is invalid",
                    safe_message="旧 Agent Runtime 发布事实无效",
                    error_code="agent_publication_runtime_mismatch",
                )
        elif snapshot.get("runtime_kind") != runtime_kind:
            raise NonRetryableExecutionError(
                "Agent publication snapshot runtime mismatch",
                safe_message="Agent Runtime 发布快照完整性校验失败",
                error_code="agent_publication_runtime_mismatch",
            )
        if "mcp_tool_envelope" in snapshot:
            envelope = snapshot.get("mcp_tool_envelope")
            if not isinstance(envelope, list):
                raise NonRetryableExecutionError(
                    "Agent publication MCP Tool Envelope is invalid",
                    safe_message="Agent MCP 工具发布事实完整性校验失败",
                    error_code="agent_mcp_tool_envelope_invalid",
                )
            self.repository.verify_mcp_tools(
                agent_publication_id=str(publication["id"]),
                envelopes=envelope,
            )
        return publication

    def connector_allowed(self, *, publication_id: str, direction: str, connector_id: str) -> bool:
        return connector_id in self.repository.publication_connectors(publication_id, direction)

    def publications(self, agent_code: str) -> list[dict[str, Any]]:
        definition = self.repository.get_definition(agent_code)
        values = [
            self._verified_publication(value)
            for value in self.repository.list_publications(str(definition["id"]))
        ]
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
        return sorted(set(MCP_TOOL_MANIFEST) & assigned)

    def _normalize(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "business_role": str(config.get("business_role") or "").strip(),
            "business_instructions": str(config.get("business_instructions") or "").strip(),
            "model_policy": dict(config.get("model_policy") or {}),
            "execution": dict(config.get("execution") or {}),
            "skills": sorted({str(item) for item in (config.get("skills") or [])}),
            "routing": dict(config.get("routing") or {}),
            "channels": dict(config.get("channels") or {}),
            "mcp_tool_ids": sorted(
                {
                    str(item).strip()
                    for item in (config.get("mcp_tool_ids") or [])
                    if str(item).strip()
                }
            ),
        }
        return normalized

    def _validate_shape(self, config: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for key in sorted(set(config) - ALLOWED_CONFIG_KEYS):
            errors.append({"field": key, "message": "此字段不可配置"})
        tool_ids = config.get("mcp_tool_ids") or []
        if not isinstance(tool_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in tool_ids
        ):
            errors.append(
                {
                    "field": "mcp_tool_ids",
                    "message": "必须是非空 MCP Tool identifier 数组",
                }
            )
        elif len(tool_ids) != len(set(tool_ids)):
            errors.append(
                {
                    "field": "mcp_tool_ids",
                    "message": "MCP Tool identifier 不得重复",
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
        for identifier in config.get("mcp_tool_ids") or []:
            if str(identifier) not in MCP_TOOL_MANIFEST:
                errors.append(
                    {
                        "field": "mcp_tool_ids",
                        "message": f"MCP Tool {identifier} 未注册",
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


def build_initial_agent_config(
    *,
    name: str,
    project_code: str,
    model: str,
    model_connection_revision_id: str = "",
) -> dict[str, Any]:
    return {
        "business_role": name,
        "business_instructions": "",
        "model_policy": {
            "runtime": "claude_agent_sdk",
            "model": model,
            "model_connection_revision_id": model_connection_revision_id,
        },
        "execution": {"max_turns": 12, "timeout_seconds": 300},
        "skills": [],
        "routing": {"project_code": project_code},
        "channels": {"ingress": [], "delivery": []},
        "mcp_tool_ids": [],
    }


def _normalize_definition_fields(
    *,
    code: str,
    name: str,
    description: str,
    project_code: str,
    runtime_kind: str,
) -> dict[str, str]:
    normalized_name = name.strip()
    normalized_description = description.strip()
    normalized_project_code = project_code.strip()
    field_errors: list[dict[str, str]] = []
    if code != code.strip() or AGENT_CODE_PATTERN.fullmatch(code) is None or len(code) > 120:
        field_errors.append(
            {
                "field": "code",
                "message": "必须是 120 字符以内的小写 kebab-case 编码",
            }
        )
    if not normalized_name or len(normalized_name) > 120:
        field_errors.append({"field": "name", "message": "名称长度必须在 1 到 120 之间"})
    if len(normalized_description) > 500:
        field_errors.append({"field": "description", "message": "说明不能超过 500 字符"})
    if (
        not normalized_project_code
        or len(normalized_project_code) > 120
        or PROJECT_CODE_PATTERN.fullmatch(normalized_project_code) is None
    ):
        field_errors.append(
            {
                "field": "project_code",
                "message": "项目编码格式无效",
            }
        )
    if runtime_kind not in SUPPORTED_RUNTIME_KINDS:
        field_errors.append(
            {
                "field": "runtime_kind",
                "message": "仅支持 python-v1 或 typescript-v1",
            }
        )
    if field_errors:
        raise NonRetryableExecutionError(
            "Agent definition is invalid",
            safe_message="Agent 基本信息无效",
            error_code="validation_failed",
            field_errors=field_errors,
        )
    return {
        "code": code,
        "name": normalized_name,
        "description": normalized_description,
        "project_code": normalized_project_code,
        "runtime_kind": runtime_kind,
    }


def agent_config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


_hash = agent_config_hash


def _provider_host(base_url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(base_url).hostname or "")[:255]
    except ValueError:
        return ""
