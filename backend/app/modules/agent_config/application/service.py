from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.model_connection.application import ModelConnectionService
from app.modules.mcp_tool_publications import McpToolPublicationService
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
    "skills",
    "routing",
    "channels",
    "mcp_tool_publication_ids",
}
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
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
        mcp_tool_publication_service: McpToolPublicationService | None = None,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.skill_loader = skill_loader
        self.model_connection_service = model_connection_service
        self.allowed_models = allowed_models or {"claude-sonnet-4-20250514"}
        self.mcp_tool_publication_service = mcp_tool_publication_service

    def get(self, agent_code: str = DEFAULT_AGENT_CODE) -> dict[str, Any]:
        definition = self.repository.get_definition(agent_code)
        latest = self.repository.latest_revision(str(definition["id"]))
        current = None
        if definition.get("current_publication_id"):
            current = self.repository.get_publication(str(definition["current_publication_id"]))
            current["active_applications"] = self.repository.active_application_usage(
                str(current["id"])
            )
        return {
            "definition": definition,
            "draft": latest,
            "current_publication": current,
            "catalog": self.catalog(),
            "management_mode": "editable" if definition["status"] == "enabled" else "read_only",
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
                self.repository.active_application_usage(str(publication["id"]))
                if publication
                else []
            )
            values.append(
                {
                    **definition,
                    "management_mode": (
                        "editable" if definition["status"] == "enabled" else "read_only"
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
                    "active_applications": usage,
                }
            )
        return values

    @operation_unit_of_work(lambda service: service.repository.database)
    def create(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        description: str,
        project_code: str,
        expected_revision: int = 0,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code="*",
            action="edit",
        )
        if expected_revision != 0:
            raise NonRetryableExecutionError(
                "New Agent expected revision must be zero",
                safe_message="Agent 已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        normalized_code = self._validate_code(code, "code")
        normalized_project = self._validate_code(project_code, "project_code")
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 200:
            raise self._field_error("name", "名称长度必须在 1 到 200 之间")
        if len(description) > 4000:
            raise self._field_error("description", "说明长度不能超过 4000")
        request = {
            "expected_revision": expected_revision,
            "code": normalized_code,
            "name": normalized_name,
            "description": description.strip(),
            "project_code": normalized_project,
        }
        replay = self._idempotent(idempotency_key, "agent.create", actor_id, request)
        if replay is not None:
            return replay
        definition = self.repository.create_definition(
            code=normalized_code,
            name=normalized_name,
            description=description.strip(),
            project_code=normalized_project,
            actor_id=actor_id,
        )
        self.audit_service.record(
            "agent.definition.created",
            status="SUCCEEDED",
            summary="Agent definition created",
            actor_id=actor_id,
            payload={"agent_code": normalized_code, "project_code": normalized_project},
        )
        response = self.get(str(definition["code"]))
        self._remember(idempotency_key, "agent.create", actor_id, request, response)
        return response

    @operation_unit_of_work(lambda service: service.repository.database)
    def update_definition(
        self,
        *,
        actor_id: str,
        agent_code: str,
        expected_revision: int,
        name: str,
        description: str,
        project_code: str,
        status: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
        )
        definition = self.repository.get_definition(agent_code)
        if status not in {"enabled", "disabled", "archived"}:
            raise self._field_error("status", "不支持此 Agent 状态")
        if str(definition["status"]) == "archived" and status != "archived":
            raise NonRetryableExecutionError(
                "Archived Agent cannot be restored",
                safe_message="已归档 Agent 不能恢复",
                error_code="invalid_lifecycle",
            )
        if status == "archived":
            if str(definition["status"]) != "disabled":
                raise NonRetryableExecutionError(
                    "Agent must be disabled before archive",
                    safe_message="Agent 必须先停用才能归档",
                    error_code="invalid_lifecycle",
                )
            usage = self.repository.active_usage_for_agent(str(definition["id"]))
            if usage:
                raise NonRetryableExecutionError(
                    "Agent is referenced by active applications",
                    safe_message="Agent 仍被活动业务应用引用，不能归档",
                    error_code="dependency_in_use",
                )
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 200:
            raise self._field_error("name", "名称长度必须在 1 到 200 之间")
        request = {
            "agent_code": agent_code,
            "expected_revision": expected_revision,
            "name": normalized_name,
            "description": description.strip(),
            "project_code": self._validate_code(project_code, "project_code"),
            "status": status,
        }
        replay = self._idempotent(idempotency_key, "agent.update", actor_id, request)
        if replay is not None:
            return replay
        if int(definition["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Agent revision conflict",
                safe_message="Agent 已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(definition["revision"])},
            )
        updated = self.repository.update_definition(
            code=agent_code,
            expected_revision=expected_revision,
            name=normalized_name,
            description=description.strip(),
            project_code=str(request["project_code"]),
            status=status,
        )
        self.audit_service.record(
            "agent.definition.updated",
            status="SUCCEEDED",
            summary="Agent definition updated",
            actor_id=actor_id,
            payload={"agent_code": agent_code, "status": status},
        )
        response = self.get(str(updated["code"]))
        self._remember(idempotency_key, "agent.update", actor_id, request, response)
        return response

    def skill_catalog(self) -> list[dict[str, Any]]:
        return self.skill_loader.catalog()

    def catalog(self) -> dict[str, Any]:
        return {
            "models": sorted(self.allowed_models),
            "skills": sorted(self.skill_loader.load()),
            "connectors": self.repository.connector_catalog(),
            "mcp_tools": self.repository.mcp_tool_catalog(),
        }

    def save_draft(
        self,
        *,
        actor_id: str,
        agent_code: str,
        expected_revision: int,
        config: dict[str, Any],
        correlation_id: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        del correlation_id
        return self._save_draft(
            actor_id=actor_id,
            agent_code=agent_code,
            expected_revision=expected_revision,
            config=config,
            idempotency_key=idempotency_key,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _save_draft(
        self,
        *,
        actor_id: str,
        agent_code: str,
        expected_revision: int,
        config: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
        )
        definition = self.repository.get_definition(agent_code)
        request = {
            "agent_code": agent_code,
            "expected_revision": expected_revision,
            "config": config,
        }
        replay = self._idempotent(idempotency_key, "agent.save_draft", actor_id, request)
        if replay is not None:
            return replay
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
        self._remember(
            idempotency_key,
            "agent.save_draft",
            actor_id,
            request,
            revision,
        )
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def validate_revision(
        self,
        *,
        actor_id: str,
        agent_code: str,
        revision_id: str,
        expected_revision: int,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self._require_enabled_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
        )
        definition = self.repository.get_definition(agent_code)
        request = {
            "agent_code": agent_code,
            "revision_id": revision_id,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(
            idempotency_key,
            "agent.validate",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        if int(definition["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Agent revision conflict",
                safe_message="Agent 已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(definition["revision"])},
            )
        revision = self.repository.get_revision(revision_id)
        if str(revision["agent_id"]) != str(definition["id"]):
            raise NonRetryableExecutionError(
                "Revision belongs to another Agent",
                safe_message="修订版本不属于此 Agent",
            )
        errors = self._validate_config(revision["config"])
        result = self.repository.set_validation(revision_id, valid=not errors, errors=errors)
        self.audit_service.record(
            "agent.config.validated",
            status="SUCCEEDED",
            summary="Agent revision validated",
            actor_id=actor_id,
            payload={
                "agent_code": agent_code,
                "revision_id": revision_id,
                "valid": not errors,
                "error_count": len(errors),
            },
        )
        self._remember(
            idempotency_key,
            "agent.validate",
            actor_id,
            request,
            result,
        )
        return result

    def publish(
        self,
        *,
        actor_id: str,
        agent_code: str,
        revision_id: str,
        expected_revision: int,
        correlation_id: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        del correlation_id
        return self._publish(
            actor_id=actor_id,
            agent_code=agent_code,
            revision_id=revision_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _publish(
        self,
        *,
        actor_id: str,
        agent_code: str,
        revision_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
        )
        definition = self.repository.get_definition(agent_code)
        request = {
            "agent_code": agent_code,
            "revision_id": revision_id,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(idempotency_key, "agent.publish", actor_id, request)
        if replay is not None:
            return replay
        if int(definition["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Agent revision conflict",
                safe_message="Agent 已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(definition["revision"])},
            )
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
            actor_id=actor_id,
            agent_code=agent_code,
            revision_id=revision_id,
            expected_revision=expected_revision,
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
            tool_publication_ids = list(snapshot.get("mcp_tool_publication_ids") or [])
            tool_publications = (
                self.mcp_tool_publication_service.prepare_agent_selection(tool_publication_ids)
                if self.mcp_tool_publication_service is not None
                else self.repository.validate_mcp_tool_publications(tool_publication_ids)
            )
            snapshot["mcp_tools"] = [
                {
                    "id": item["id"],
                    "code": item["code"],
                    "server_code": item["server_code"],
                    "server_version": item["server_version"],
                    "tool_name": item["tool_name"],
                    "required_scope": item["required_scope"],
                    "tool_schema_hash": item["tool_schema_hash"],
                    "resource_kind": item["resource_kind"],
                    "resource_code": item["resource_code"],
                    "resource_deployment_id": item["resource_deployment_id"],
                    "resource_revision_id": item["resource_revision_id"],
                    "config_hash": item["config_hash"],
                }
                for item in tool_publications
            ]
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
                mcp_tool_publication_ids=tool_publication_ids,
                expected_definition_revision=expected_revision,
            )
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
        self._remember(
            idempotency_key,
            "agent.publish",
            actor_id,
            request,
            publication,
        )
        return publication

    def rollback(
        self,
        *,
        actor_id: str,
        agent_code: str,
        publication_id: str,
        expected_revision: int,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self._require_enabled_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
        )
        definition = self.repository.get_definition(agent_code)
        request = {
            "agent_code": agent_code,
            "publication_id": publication_id,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(
            idempotency_key,
            "agent.rollback",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        if int(definition["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Agent revision conflict",
                safe_message="Agent 已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(definition["revision"])},
            )
        selected = self.publication(publication_id)
        selected_tool_ids = list(
            (selected.get("snapshot") or {}).get("mcp_tool_publication_ids") or []
        )
        if self.mcp_tool_publication_service is not None:
            self.mcp_tool_publication_service.prepare_agent_selection(selected_tool_ids)
        else:
            self.repository.validate_mcp_tool_publications(selected_tool_ids)
        model_connection = (selected.get("snapshot") or {}).get("model_connection") or {}
        if model_connection and self.model_connection_service is not None:
            self.model_connection_service.runtime_binding(
                str(model_connection.get("revision_id") or "")
            )
        return self._rollback(
            actor_id=actor_id,
            agent_code=agent_code,
            publication_id=publication_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _rollback(
        self,
        *,
        actor_id: str,
        agent_code: str,
        publication_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled_agent(agent_code)
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
        )
        definition = self.repository.get_definition(agent_code)
        request = {
            "agent_code": agent_code,
            "publication_id": publication_id,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(idempotency_key, "agent.rollback", actor_id, request)
        if replay is not None:
            return replay
        publication = self.repository.set_current_publication(
            agent_id=str(definition["id"]),
            publication_id=publication_id,
            expected_revision=expected_revision,
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
        self._remember(
            idempotency_key,
            "agent.rollback",
            actor_id,
            request,
            publication,
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
        return publication

    def connector_allowed(self, *, publication_id: str, direction: str, connector_id: str) -> bool:
        return connector_id in self.repository.publication_connectors(publication_id, direction)

    def publications(self, agent_code: str) -> list[dict[str, Any]]:
        definition = self.repository.get_definition(agent_code)
        values = self.repository.list_publications(str(definition["id"]))
        for publication in values:
            publication["active_applications"] = self.repository.active_application_usage(
                str(publication["id"])
            )
            publication["mcp_tools"] = self.repository.publication_mcp_tools(str(publication["id"]))
            publication["model_runtime_mode"] = (
                "pinned_connection"
                if (publication.get("snapshot") or {}).get("model_connection")
                else "legacy_global_connection"
            )
        return values

    def _require_enabled_agent(self, agent_code: str) -> None:
        definition = self.repository.get_definition(agent_code)
        if str(definition["status"]) != "enabled":
            raise NonRetryableExecutionError(
                "Agent is not enabled",
                safe_message="只有已启用的 Agent 可以编辑或发布",
                error_code="invalid_lifecycle",
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
            "mcp_tool_publication_ids": list(
                dict.fromkeys(str(item) for item in (config.get("mcp_tool_publication_ids") or []))
            ),
        }
        return normalized

    def _validate_shape(self, config: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for key in sorted(set(config) - ALLOWED_CONFIG_KEYS):
            errors.append({"field": key, "message": "此字段不可配置"})
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
        raw_tools = config.get("mcp_tool_publication_ids") or []
        if not isinstance(raw_tools, list) or len(raw_tools) > 100:
            errors.append(
                {"field": "mcp_tool_publication_ids", "message": "必须是最多 100 项的列表"}
            )
        elif any(not isinstance(item, str) or not item.strip() for item in raw_tools):
            errors.append({"field": "mcp_tool_publication_ids", "message": "发布版本 ID 无效"})
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
        try:
            tool_ids = list(config.get("mcp_tool_publication_ids") or [])
            if self.mcp_tool_publication_service is not None:
                self.mcp_tool_publication_service.prepare_agent_selection(tool_ids)
            else:
                self.repository.validate_mcp_tool_publications(tool_ids)
        except NonRetryableExecutionError:
            errors.append(
                {
                    "field": "mcp_tool_publication_ids",
                    "message": "包含不可用的 MCP Tool 发布版本",
                }
            )
        return errors

    @staticmethod
    def _validate_code(value: str, field: str) -> str:
        normalized = value.strip().lower()
        if not 2 <= len(normalized) <= 120 or not CODE_PATTERN.fullmatch(normalized):
            raise AgentConfigService._field_error(field, "必须使用稳定的小写编码")
        return normalized

    @staticmethod
    def _field_error(field: str, message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            f"{field}: {message}",
            safe_message="Agent 配置无效",
            error_code="validation_failed",
            field_errors=[{"field": field, "message": message}],
        )

    def _idempotent(
        self,
        key: str,
        operation: str,
        actor_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not key:
            return None
        if len(key) > 128:
            raise self._field_error("idempotency_key", "幂等键长度超出限制")
        row = self.repository.database.execute_one(
            "select * from management_operation_idempotency where idempotency_key = ?",
            (key,),
        )
        if row is None:
            return None
        request_hash = _hash(request)
        if (
            str(row["operation"]) != operation
            or str(row["actor_id"]) != actor_id
            or str(row["request_hash"]) != request_hash
        ):
            raise NonRetryableExecutionError(
                "Agent idempotency conflict",
                safe_message="重复请求与原请求不一致",
                error_code="idempotency_conflict",
            )
        try:
            response = json.loads(str(row["response_json"]))
        except json.JSONDecodeError as exc:
            raise NonRetryableExecutionError(
                "Agent idempotency ledger is invalid",
                safe_message="幂等记录完整性校验失败",
                error_code="idempotency_integrity_failed",
            ) from exc
        if not isinstance(response, dict):
            raise NonRetryableExecutionError(
                "Agent idempotency response is invalid",
                safe_message="幂等记录完整性校验失败",
                error_code="idempotency_integrity_failed",
            )
        return response

    def _remember(
        self,
        key: str,
        operation: str,
        actor_id: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        if not key:
            return
        self.repository.database.execute(
            """
            insert into management_operation_idempotency
              (idempotency_key, operation, actor_id, request_hash, response_json, created_at)
            values (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                key,
                operation,
                actor_id,
                _hash(request),
                json.dumps(response, ensure_ascii=False, sort_keys=True),
            ),
        )


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
