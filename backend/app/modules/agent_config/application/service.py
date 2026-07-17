from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.shared.exceptions import NonRetryableExecutionError


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
    "tools",
    "skills",
    "routing",
    "channels",
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
        allowed_models: set[str] | None = None,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.skill_loader = skill_loader
        self.allowed_models = allowed_models or {"claude-sonnet-4-20250514"}

    def get(self, agent_code: str = DEFAULT_AGENT_CODE) -> dict[str, Any]:
        definition = self.repository.get_definition(agent_code)
        latest = self.repository.latest_revision(str(definition["id"]))
        current = None
        if definition.get("current_publication_id"):
            current = self.repository.get_publication(
                str(definition["current_publication_id"])
            )
        return {
            "definition": definition,
            "draft": latest,
            "current_publication": current,
            "catalog": self.catalog(),
        }

    def catalog(self) -> dict[str, Any]:
        return {
            "models": sorted(self.allowed_models),
            "tools": sorted(self.repository.enabled_tools() & ToolRegistry.READONLY_TOOLS),
            "skills": sorted(self.skill_loader.load()),
            "connectors": self.repository.connector_catalog(),
        }

    def save_draft(
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
                safe_message="Agent configuration is invalid",
                error_code="validation_failed",
                field_errors=raw_errors,
            )
        normalized = self._normalize(config)
        with self.repository.database.transaction():
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
                safe_message="Revision does not belong to this Agent",
            )
        errors = self._validate_config(revision["config"])
        return self.repository.set_validation(
            revision_id, valid=not errors, errors=errors
        )

    def publish(
        self, *, actor_id: str, agent_code: str, revision_id: str
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
        )
        definition = self.repository.get_definition(agent_code)
        revision = self.validate_revision(
            actor_id=actor_id, agent_code=agent_code, revision_id=revision_id
        )
        errors = revision["validation"].get("errors") or []
        if errors:
            raise NonRetryableExecutionError(
                "Agent configuration validation failed",
                safe_message="Agent configuration is invalid",
                error_code="validation_failed",
                field_errors=errors,
            )
        with self.repository.database.transaction():
            publication = self.repository.create_publication(
                agent_id=str(definition["id"]),
                revision_id=revision_id,
                revision=int(revision["revision"]),
                snapshot=revision["config"],
                config_hash=str(revision["config_hash"]),
                actor_id=actor_id,
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
            },
        )
        return publication

    def rollback(
        self, *, actor_id: str, agent_code: str, publication_id: str
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
        )
        definition = self.repository.get_definition(agent_code)
        self.publication(publication_id)
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
                safe_message="Agent configuration schema is unsupported",
            )
        if _hash(publication["snapshot"]) != str(publication["config_hash"]):
            raise NonRetryableExecutionError(
                "Agent publication hash mismatch",
                safe_message="Agent configuration integrity check failed",
            )
        return publication

    def connector_allowed(
        self, *, publication_id: str, direction: str, connector_id: str
    ) -> bool:
        return connector_id in self.repository.publication_connectors(
            publication_id, direction
        )

    def publications(self, agent_code: str) -> list[dict[str, Any]]:
        definition = self.repository.get_definition(agent_code)
        return self.repository.list_publications(str(definition["id"]))

    def allowed_tools(
        self, *, publication_id: str, user_id: str, project_code: str
    ) -> list[str]:
        del project_code
        assigned = self.repository.publication_tools(publication_id)
        enabled = self.repository.enabled_tools()
        result: list[str] = []
        for tool_name in sorted(ToolRegistry.READONLY_TOOLS & assigned & enabled):
            decision = self.authorization.decide(
                user_id=user_id,
                resource_type="tool",
                resource_code=tool_name,
                action="use",
            )
            if decision.allowed:
                result.append(tool_name)
        return result

    def _normalize(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "business_role": str(config.get("business_role") or "").strip(),
            "business_instructions": str(
                config.get("business_instructions") or ""
            ).strip(),
            "model_policy": dict(config.get("model_policy") or {}),
            "execution": dict(config.get("execution") or {}),
            "tools": sorted({str(item) for item in (config.get("tools") or [])}),
            "skills": sorted({str(item) for item in (config.get("skills") or [])}),
            "routing": dict(config.get("routing") or {}),
            "channels": dict(config.get("channels") or {}),
        }
        return normalized

    def _validate_shape(self, config: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for key in sorted(set(config) - ALLOWED_CONFIG_KEYS):
            errors.append({"field": key, "message": "Field is not configurable"})
        nested = {
            "model_policy": {"model"},
            "execution": {"max_turns", "timeout_seconds"},
            "routing": {"project_code"},
            "channels": {"ingress", "delivery"},
        }
        for field, allowed in nested.items():
            value = config.get(field) or {}
            if not isinstance(value, dict):
                errors.append({"field": field, "message": "Must be an object"})
                continue
            for key in sorted(set(value) - allowed):
                errors.append(
                    {"field": f"{field}.{key}", "message": "Field is not configurable"}
                )
        return errors

    def _validate_config(self, config: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        serialized = json.dumps(config, ensure_ascii=False).lower()
        for key in FORBIDDEN_CONFIG_KEYS:
            if f'"{key}"' in serialized:
                errors.append(
                    {"field": key, "message": "Field is controlled by platform security"}
                )
        instructions = str(config.get("business_instructions") or "").lower()
        for pattern in FORBIDDEN_INSTRUCTION_PATTERNS:
            if pattern in instructions:
                errors.append(
                    {
                        "field": "business_instructions",
                        "message": "Business instructions conflict with platform safety",
                    }
                )
                break
        model_policy = config.get("model_policy") or {}
        model = str(model_policy.get("model") or "") if isinstance(model_policy, dict) else ""
        # The catalog is the allowlist. Provider-compatible model identifiers may
        # legitimately contain brackets or other punctuation, so a second,
        # narrower character regex would make the catalog and validator disagree.
        if model not in self.allowed_models:
            errors.append(
                {"field": "model_policy.model", "message": "Model is not registered"}
            )
        enabled_tools = self.repository.enabled_tools()
        for tool_name in config.get("tools") or []:
            if str(tool_name) not in ToolRegistry.READONLY_TOOLS or str(
                tool_name
            ) not in enabled_tools:
                errors.append(
                    {
                        "field": "tools",
                        "message": f"Tool {tool_name} is not registered and read-only",
                    }
                )
        available_skills = set(self.skill_loader.load())
        for skill_code in config.get("skills") or []:
            if str(skill_code) not in available_skills:
                errors.append(
                    {
                        "field": "skills",
                        "message": f"Skill {skill_code} is not registered",
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
                                "message": f"Connector {connector_id} is unavailable",
                            }
                        )
        execution = config.get("execution") or {}
        if isinstance(execution, dict):
            try:
                max_turns = int(execution.get("max_turns") or 12)
                timeout = int(execution.get("timeout_seconds") or 300)
            except (TypeError, ValueError):
                errors.append(
                    {"field": "execution", "message": "Execution limits must be integers"}
                )
                return errors
            if not 1 <= max_turns <= 100:
                errors.append(
                    {"field": "execution.max_turns", "message": "Must be between 1 and 100"}
                )
            if not 10 <= timeout <= 3600:
                errors.append(
                    {
                        "field": "execution.timeout_seconds",
                        "message": "Must be between 10 and 3600",
                    }
                )
        return errors


def _hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
