from __future__ import annotations

import re
from typing import Any

from app.modules.agent_config.application.service import AgentConfigService
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.webhook.application.mapping import WebhookMapper, validate_pointer
from app.modules.webhook.domain.models import (
    AuthenticationType,
    CODE_RE,
    CONDITION_OPERATORS,
    ROUTING_FIELDS,
    SECRET_REF_PREFIXES,
    SERVICE_CODE_RE,
    TriggerSchema,
    config_hash,
    ensure_no_secret_values,
    normalize_config,
)
from app.modules.webhook.infrastructure import WebhookTriggerRepository
from app.shared.exceptions import NonRetryableExecutionError


_TEMPLATE_VARIABLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SAFE_TARGET_KEYS = frozenset(
    {"webhook_id", "open_conversation_id", "robot_code", "conversation_id"}
)


class TriggerValidator:
    def __init__(
        self,
        *,
        repository: WebhookTriggerRepository,
        identity_repository: IdentityRepository,
        connector_registry: ConnectorRegistry,
        agent_config_service: AgentConfigService,
        authorization: AuthorizationEvaluator,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.connector_registry = connector_registry
        self.agent_config_service = agent_config_service
        self.authorization = authorization

    def validate(
        self, *, definition: dict[str, Any], config: dict[str, Any]
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        errors: list[dict[str, str]] = []
        if int(config.get("schema_version") or 0) != 1:
            errors.append({"field": "schema_version", "message": "Only schema version 1 is supported"})
        if str(config.get("adapter") or "") not in {item.value for item in TriggerSchema}:
            errors.append({"field": "adapter", "message": "Unsupported adapter"})
        expected_adapter = {
            "grafana": TriggerSchema.GRAFANA_ALERTMANAGER_V1.value,
            "generic": TriggerSchema.GENERIC_JSON_V1.value,
        }.get(str(definition.get("trigger_type") or ""))
        if expected_adapter and str(config.get("adapter") or "") != expected_adapter:
            errors.append(
                {
                    "field": "adapter",
                    "message": "Adapter does not match the Trigger type",
                }
            )
        account = self.identity_repository.get_user(str(definition["service_account_id"]))
        if str(account.get("account_type")) != "service":
            errors.append({"field": "service_account", "message": "A service account is required"})
        if str(account.get("status")) != "enabled":
            errors.append({"field": "service_account", "message": "Service account is disabled"})
        try:
            source = self.connector_registry.require_ingress(str(definition["connector_id"]))
        except Exception as exc:
            errors.append({"field": "connector_id", "message": getattr(exc, "safe_message", "Ingress connector is unavailable")})
            source = None

        auth = config.get("authentication") or {}
        auth_type = str(auth.get("type") or "")
        if auth_type not in {item.value for item in AuthenticationType}:
            errors.append({"field": "authentication.type", "message": "Unsupported authentication type"})
        secret_ref = str(auth.get("secret_ref") or "")
        if not secret_ref.startswith(SECRET_REF_PREFIXES):
            errors.append({"field": "authentication.secret_ref", "message": "A managed secret reference is required"})
        elif not self.connector_registry.resolve_reference(secret_ref):
            errors.append({"field": "authentication.secret_ref", "message": "Secret reference cannot be resolved"})
        if not 30 <= int(auth.get("window_seconds") or 0) <= 900:
            errors.append({"field": "authentication.window_seconds", "message": "Must be between 30 and 900"})

        mapping = config.get("mapping") or {}
        variables = mapping.get("variables") or {}
        if not isinstance(variables, dict) or len(variables) > 50:
            errors.append({"field": "mapping.variables", "message": "At most 50 variables are allowed"})
            variables = {}
        for name, pointer in variables.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", str(name)):
                errors.append({"field": "mapping.variables", "message": "Variable name is invalid"})
            if not validate_pointer(str(pointer)):
                errors.append({"field": f"mapping.variables.{name}", "message": "JSON Pointer is invalid"})
        template = str(mapping.get("message_template") or "")
        unknown_variables = sorted(set(_TEMPLATE_VARIABLE_RE.findall(template)) - set(variables))
        if unknown_variables:
            errors.append({"field": "mapping.message_template", "message": f"Unknown variables: {', '.join(unknown_variables)}"})
        for index, condition in enumerate(mapping.get("filters") or []):
            if not isinstance(condition, dict):
                errors.append({"field": f"mapping.filters.{index}", "message": "Condition must be an object"})
                continue
            if str(condition.get("operator") or "") not in CONDITION_OPERATORS:
                errors.append({"field": f"mapping.filters.{index}.operator", "message": "Operator is not allowed"})
            if not validate_pointer(str(condition.get("pointer") or "")):
                errors.append({"field": f"mapping.filters.{index}.pointer", "message": "JSON Pointer is invalid"})
        if config.get("adapter") == TriggerSchema.GENERIC_JSON_V1 and not validate_pointer(
            str(mapping.get("event_id_pointer") or "")
        ):
            errors.append({"field": "mapping.event_id_pointer", "message": "JSON Pointer is invalid"})

        for field in ROUTING_FIELDS:
            rule = (config.get("routing") or {}).get(field) or {}
            mode = str(rule.get("mode") or "")
            if mode not in {"fixed", "extract"}:
                errors.append({"field": f"routing.{field}.mode", "message": "Mode must be fixed or extract"})
                continue
            if mode == "fixed" and field == "project_code" and not str(rule.get("value") or ""):
                errors.append({"field": f"routing.{field}.value", "message": "Project code is required"})
            if mode == "extract":
                if not validate_pointer(str(rule.get("pointer") or "")):
                    errors.append({"field": f"routing.{field}.pointer", "message": "JSON Pointer is invalid"})
                if not rule.get("allowed_values"):
                    errors.append({"field": f"routing.{field}.allowed_values", "message": "Extract routing requires an allowlist"})
            if field == "service":
                for value in [str(rule.get("value") or ""), *[str(item) for item in rule.get("allowed_values") or []]]:
                    if value and not SERVICE_CODE_RE.fullmatch(value):
                        errors.append({"field": "routing.service", "message": "Service code is invalid"})

        limits = config.get("limits") or {}
        for limit_name, minimum, maximum in (
            ("requests_per_minute", 1, 10000),
            ("max_in_flight", 1, 1000),
            ("max_alerts", 1, 100),
        ):
            limit_value = int(limits.get(limit_name) or 0)
            if not minimum <= limit_value <= maximum:
                errors.append({"field": f"limits.{limit_name}", "message": f"Must be between {minimum} and {maximum}"})

        delivery = config.get("delivery") or {}
        delivery_id = str(delivery.get("connector_id") or "")
        try:
            self.connector_registry.require_delivery(delivery_id)
        except Exception as exc:
            errors.append({"field": "delivery.connector_id", "message": getattr(exc, "safe_message", "Delivery connector is unavailable")})
        target = delivery.get("target") or {}
        if not isinstance(target, dict) or set(target) - _SAFE_TARGET_KEYS:
            errors.append({"field": "delivery.target", "message": "Delivery target contains unsupported fields"})

        agent = config.get("agent") or {}
        agent_code = str(agent.get("code") or "")
        agent_publication_id = str(agent.get("publication_id") or "")
        agent_publication: dict[str, Any] | None = None
        try:
            agent_publication = self.agent_config_service.publication(agent_publication_id)
            agent_definition = self.agent_config_service.repository.get_definition_by_id(
                str(agent_publication["agent_id"])
            )
            if str(agent_definition["code"]) != agent_code:
                errors.append({"field": "agent", "message": "Agent publication does not match Agent code"})
            if source and not self.agent_config_service.connector_allowed(
                publication_id=agent_publication_id,
                direction="ingress",
                connector_id=source.id,
            ):
                errors.append({"field": "connector_id", "message": "Ingress connector is not assigned to Agent publication"})
            if delivery_id and not self.agent_config_service.connector_allowed(
                publication_id=agent_publication_id,
                direction="delivery",
                connector_id=delivery_id,
            ):
                errors.append({"field": "delivery.connector_id", "message": "Delivery connector is not assigned to Agent publication"})
        except Exception as exc:
            errors.append({"field": "agent.publication_id", "message": getattr(exc, "safe_message", "Agent publication is unavailable")})

        project_rule = (config.get("routing") or {}).get("project_code") or {}
        project_values = (
            [str(project_rule.get("value") or "")]
            if project_rule.get("mode") == "fixed"
            else [str(item) for item in project_rule.get("allowed_values") or []]
        )
        if agent_code and not self.authorization.decide(
            user_id=str(account["id"]), resource_type="agent", resource_code=agent_code, action="use"
        ).allowed:
            errors.append({"field": "service_account", "message": "Service account cannot use the Agent"})
        for project_code in project_values:
            if project_code and not self.authorization.decide(
                user_id=str(account["id"]), resource_type="project", resource_code=project_code, action="use"
            ).allowed:
                errors.append({"field": "routing.project_code", "message": f"Service account cannot use project {project_code}"})

        assigned_tools = sorted(
            self.agent_config_service.repository.publication_tools(agent_publication_id)
        ) if agent_publication else []
        enabled_read_only_tools = (
            self.agent_config_service.repository.enabled_tools() & ToolRegistry.READONLY_TOOLS
        )
        invalid_tools = sorted(set(assigned_tools) - enabled_read_only_tools)
        if invalid_tools:
            errors.append(
                {
                    "field": "agent.publication_id",
                    "message": f"Agent publication contains invalid tools: {', '.join(invalid_tools)}",
                }
            )
        allowed_tools = self.agent_config_service.allowed_tools(
            publication_id=agent_publication_id,
            user_id=str(account["id"]),
            project_code=project_values[0] if project_values else "",
        ) if agent_publication else []
        if assigned_tools and not allowed_tools:
            errors.append(
                {
                    "field": "service_account",
                    "message": "Service account cannot use any assigned read-only Agent tool",
                }
            )
        summary = {
            "agent_publication_id": agent_publication_id,
            "agent_revision": int(agent_publication["revision"]) if agent_publication else 0,
            "agent_config_hash": str(agent_publication["config_hash"]) if agent_publication else "",
            "assigned_read_only_tools": assigned_tools,
            "effective_read_only_tools": allowed_tools,
        }
        return errors, summary


class WebhookTriggerService:
    def __init__(
        self,
        *,
        repository: WebhookTriggerRepository,
        identity_repository: IdentityRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        validator: TriggerValidator,
        mapper: WebhookMapper,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.validator = validator
        self.mapper = mapper

    def list(self, *, actor_id: str) -> list[dict[str, Any]]:
        self._require(actor_id, "read")
        return self.repository.list_definitions()

    def get(self, *, actor_id: str, code: str) -> dict[str, Any]:
        self._require(actor_id, "read", code)
        definition = self.repository.get_definition(code)
        latest = self.repository.latest_revision(str(definition["id"]))
        current = None
        if definition.get("current_publication_id"):
            current = self.repository.get_publication(str(definition["current_publication_id"]))
        return {
            "definition": definition,
            "draft": latest,
            "current_publication": current,
            "publications": self.repository.list_publications(str(definition["id"])),
        }

    def create(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        trigger_type: str,
        connector_id: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require(actor_id, "edit")
        if not CODE_RE.fullmatch(code):
            raise NonRetryableExecutionError(
                "Webhook Trigger code is invalid",
                safe_message="Webhook Trigger code is invalid",
                error_code="validation_failed",
                field_errors=[{"field": "code", "message": "Use lower-case letters, digits and hyphens"}],
            )
        self.validator.connector_registry.require_ingress(connector_id)
        with self.repository.database.transaction():
            service = self.identity_repository.create_user(
                username=f"svc-webhook-{code}",
                display_name=f"Webhook: {name}",
                account_type="service",
            )
            definition = self.repository.create_definition(
                code=code,
                name=name.strip(),
                trigger_type=trigger_type,
                connector_id=connector_id,
                service_account_id=str(service["id"]),
                actor_id=actor_id,
            )
            draft = None
            if config is not None:
                normalized = self._normalize(config)
                draft = self.repository.save_draft(
                    trigger_id=str(definition["id"]),
                    expected_revision=0,
                    config=normalized,
                    config_hash=config_hash(normalized),
                    actor_id=actor_id,
                )
        self._audit(
            "webhook.trigger.created",
            actor_id=actor_id,
            code=code,
            after_hash=config_hash(draft["config"]) if draft else "",
            extra={"service_account_id": service["id"]},
        )
        return {"definition": definition, "draft": draft, "service_account": service}

    def save_draft(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        definition = self.repository.get_definition(code)
        normalized = self._normalize(config)
        revision = self.repository.save_draft(
            trigger_id=str(definition["id"]),
            expected_revision=expected_revision,
            config=normalized,
            config_hash=config_hash(normalized),
            actor_id=actor_id,
        )
        self._audit(
            "webhook.trigger.draft_saved",
            actor_id=actor_id,
            code=code,
            after_hash=str(revision["config_hash"]),
            extra={"revision": revision["revision"]},
        )
        return revision

    def validate_revision(
        self, *, actor_id: str, code: str, revision_id: str
    ) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        definition = self.repository.get_definition(code)
        revision = self.repository.get_revision(revision_id)
        self._assert_revision_owner(definition, revision)
        errors, summary = self.validator.validate(definition=definition, config=revision["config"])
        result = self.repository.set_validation(revision_id, errors=errors, summary=summary)
        self._audit(
            "webhook.trigger.validated",
            actor_id=actor_id,
            code=code,
            after_hash=str(revision["config_hash"]),
            extra={"revision": revision["revision"], "valid": not errors},
        )
        return result

    def preview(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str,
        sample_payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        definition = self.repository.get_definition(code)
        revision = self.repository.get_revision(revision_id)
        self._assert_revision_owner(definition, revision)
        errors, summary = self.validator.validate(definition=definition, config=revision["config"])
        if errors:
            raise NonRetryableExecutionError(
                "Webhook Trigger validation failed",
                safe_message="Webhook Trigger configuration is invalid",
                error_code="validation_failed",
                field_errors=errors,
            )
        return {
            **self.mapper.preview(config=revision["config"], payload=sample_payload),
            "agent": summary,
            "delivery": revision["config"]["delivery"],
            "side_effects": False,
        }

    def publish(
        self, *, actor_id: str, code: str, revision_id: str
    ) -> dict[str, Any]:
        self._require(actor_id, "publish", code)
        definition = self.repository.get_definition(code)
        revision = self.repository.get_revision(revision_id)
        self._assert_revision_owner(definition, revision)
        errors, summary = self.validator.validate(definition=definition, config=revision["config"])
        if errors:
            self.repository.set_validation(revision_id, errors=errors, summary=summary)
            raise NonRetryableExecutionError(
                "Webhook Trigger validation failed",
                safe_message="Webhook Trigger configuration is invalid",
                error_code="validation_failed",
                field_errors=errors,
            )
        agent_publication = self.validator.agent_config_service.publication(
            str(revision["config"]["agent"]["publication_id"])
        )
        snapshot = {
            **revision["config"],
            "service_account_id": definition["service_account_id"],
            "source_connector_id": definition["connector_id"],
            "agent": {
                **revision["config"]["agent"],
                "revision": agent_publication["revision"],
                "config_hash": agent_publication["config_hash"],
                "read_only_tools": summary["effective_read_only_tools"],
            },
        }
        with self.repository.database.transaction():
            self.repository.set_validation(revision_id, errors=[], summary=summary)
            publication = self.repository.create_publication(
                trigger_id=str(definition["id"]),
                revision_id=revision_id,
                revision=int(revision["revision"]),
                snapshot=snapshot,
                config_hash=config_hash(revision["config"]),
                agent_publication=agent_publication,
                actor_id=actor_id,
            )
        self._audit(
            "webhook.trigger.published",
            actor_id=actor_id,
            code=code,
            after_hash=str(publication["config_hash"]),
            extra={"publication_id": publication["id"], "revision": publication["revision"]},
        )
        return publication

    def update_definition(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        name: str,
        connector_id: str,
        status: str,
    ) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        before = self.repository.get_definition(code)
        self.validator.connector_registry.require_ingress(connector_id)
        updated = self.repository.update_definition(
            code=code,
            expected_revision=expected_revision,
            name=name.strip(),
            connector_id=connector_id,
            status=status,
        )
        self._audit(
            "webhook.trigger.updated",
            actor_id=actor_id,
            code=code,
            before_hash=config_hash({"name": before["name"], "connector_id": before["connector_id"], "status": before["status"]}),
            after_hash=config_hash({"name": updated["name"], "connector_id": updated["connector_id"], "status": updated["status"]}),
        )
        return updated

    def rollback(
        self,
        *,
        actor_id: str,
        code: str,
        publication_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        self._require(actor_id, "publish", code)
        before = self.repository.get_definition(code)
        publication = self.repository.set_current_publication(
            code=code,
            publication_id=publication_id,
            expected_revision=expected_revision,
        )
        self._audit(
            "webhook.trigger.rolled_back",
            actor_id=actor_id,
            code=code,
            before_hash=str(before.get("current_publication_id") or ""),
            after_hash=publication_id,
        )
        return publication

    def rotate_public_id(
        self, *, actor_id: str, code: str, expected_revision: int, confirm: bool
    ) -> dict[str, Any]:
        self._require(actor_id, "rotate", code)
        if not confirm:
            raise NonRetryableExecutionError(
                "Public ID rotation requires confirmation",
                safe_message="Confirm public ID rotation",
                error_code="confirmation_required",
            )
        before = self.repository.get_definition(code)
        updated = self.repository.rotate_public_id(code=code, expected_revision=expected_revision)
        self._audit(
            "webhook.trigger.public_id_rotated",
            actor_id=actor_id,
            code=code,
            before_hash=config_hash({"public_id": before["public_id"]}),
            after_hash=config_hash({"public_id": updated["public_id"]}),
        )
        return updated

    def set_service_account_enabled(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        enabled: bool,
    ) -> dict[str, Any]:
        self._require(actor_id, "manage_service_account", code)
        updated = self.repository.set_service_account_status(
            code=code, expected_revision=expected_revision, enabled=enabled
        )
        self._audit(
            "webhook.trigger.service_account_status_changed",
            actor_id=actor_id,
            code=code,
            after_hash=config_hash({"enabled": enabled}),
            extra={"service_account_id": updated["service_account_id"]},
        )
        return updated

    def _normalize(self, config: dict[str, Any]) -> dict[str, Any]:
        ensure_no_secret_values(config)
        return normalize_config(config)

    def _assert_revision_owner(
        self, definition: dict[str, Any], revision: dict[str, Any]
    ) -> None:
        if str(revision["trigger_id"]) != str(definition["id"]):
            raise NonRetryableExecutionError(
                "Revision belongs to another Trigger",
                safe_message="Revision does not belong to this Trigger",
            )

    def _require(self, actor_id: str, action: str, code: str = "*") -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="webhook_trigger",
            resource_code=code,
            action=action,
        )

    def _audit(
        self,
        event_type: str,
        *,
        actor_id: str,
        code: str,
        before_hash: str = "",
        after_hash: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.audit_service.record(
            event_type,
            status="SUCCEEDED",
            summary=event_type.replace(".", " "),
            actor_id=actor_id,
            payload={
                "trigger_code": code,
                "before_hash": before_hash,
                "after_hash": after_hash,
                **(extra or {}),
            },
        )
