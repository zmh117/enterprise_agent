from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..infrastructure.repository import PlatformConfigRepository
from .validation import (
    PlatformConfigValidationError,
    coerce_runtime_value,
    validate_config_value_type,
    validate_runtime_scope_type,
)


BOOTSTRAP_ONLY_KEYS = {
    "DATABASE_DSN",
    "APP_CONFIG_MASTER_KEY",
    "APP_ENV",
    "APP_STARTUP_MIGRATE",
    "SEED_LOCAL_CONFIG",
}


@dataclass(frozen=True)
class RuntimeConfigDefinitionSpec:
    key: str
    value_type: str
    default: Any
    sensitive: bool = False
    bootstrap_only: bool = False
    service_names: tuple[str, ...] = ()
    description: str = ""


RUNTIME_CONFIG_DEFINITIONS: tuple[RuntimeConfigDefinitionSpec, ...] = (
    RuntimeConfigDefinitionSpec("DATABASE_DSN", "string", "", bootstrap_only=True),
    RuntimeConfigDefinitionSpec("APP_CONFIG_MASTER_KEY", "secret_ref", "", sensitive=True, bootstrap_only=True),
    RuntimeConfigDefinitionSpec("APP_ENV", "string", "local", bootstrap_only=True),
    RuntimeConfigDefinitionSpec("APP_STARTUP_MIGRATE", "bool", True, bootstrap_only=True),
    RuntimeConfigDefinitionSpec("SEED_LOCAL_CONFIG", "bool", False, bootstrap_only=True),
    RuntimeConfigDefinitionSpec("FEATURE_REAL_CLAUDE", "bool", False, service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("FEATURE_REAL_INTERNAL_TOOLS", "bool", False, service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("INTERNAL_API_BASE_URL", "url", "http://internal-api-platform.local", service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("INTERNAL_API_AUTH_TOKEN", "secret_ref", "", sensitive=True, service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("INTERNAL_API_TIMEOUT_SECONDS", "int", 10, service_names=("api-server", "agent-worker", "internal-api-platform")),
    RuntimeConfigDefinitionSpec("INTERNAL_API_MAX_RESPONSE_CHARS", "int", 4000, service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("INTERNAL_PLATFORM_MAX_ROWS", "int", 100, service_names=("internal-api-platform",)),
    RuntimeConfigDefinitionSpec("ANTHROPIC_BASE_URL", "url", "", service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("ANTHROPIC_MODEL", "string", "claude-sonnet-4-20250514", service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("CLAUDE_MODEL", "string", "claude-sonnet-4-20250514", service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("ANTHROPIC_API_KEY", "secret_ref", "", sensitive=True, service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("ANTHROPIC_AUTH_TOKEN", "secret_ref", "", sensitive=True, service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("CLAUDE_CODE_EFFORT_LEVEL", "string", "max", service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("AGENT_MAX_TURNS", "int", 12, service_names=("agent-worker", "api-server")),
    RuntimeConfigDefinitionSpec("AGENT_TIMEOUT_SECONDS", "int", 300, service_names=("agent-worker",)),
    RuntimeConfigDefinitionSpec("MAX_TOOL_RESPONSE_CHARS", "int", 4000, service_names=("agent-worker",)),
    RuntimeConfigDefinitionSpec("MAX_LOKI_MINUTES", "int", 60, service_names=("agent-worker", "internal-api-platform")),
    RuntimeConfigDefinitionSpec("MAX_LOKI_LINES", "int", 500, service_names=("agent-worker", "internal-api-platform")),
    RuntimeConfigDefinitionSpec("REDIS_SCAN_LIMIT", "int", 200, service_names=("agent-worker", "internal-api-platform")),
    RuntimeConfigDefinitionSpec("LOKI_BASE_URL", "url", "http://host.docker.internal:3100", service_names=("local-internal-api-platform", "internal-api-platform")),
    RuntimeConfigDefinitionSpec("LOKI_MAX_MINUTES", "int", 60, service_names=("internal-api-platform",)),
    RuntimeConfigDefinitionSpec("LOKI_MAX_LINES", "int", 500, service_names=("internal-api-platform",)),
    RuntimeConfigDefinitionSpec("LOKI_MAX_RESPONSE_CHARS", "int", 4000, service_names=("internal-api-platform",)),
    RuntimeConfigDefinitionSpec("LOKI_TENANT_ID", "string", "", service_names=("internal-api-platform",)),
    RuntimeConfigDefinitionSpec("DINGTALK_CLIENT_ID", "string", "", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_CLIENT_SECRET", "secret_ref", "", sensitive=True, service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_STREAM_ENABLED", "bool", False, service_names=("dingtalk-stream-ingress",)),
    RuntimeConfigDefinitionSpec("DINGTALK_STREAM_CONNECTOR_ID", "string", "connector-dingtalk-stream-default", service_names=("dingtalk-stream-ingress",)),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_DELIVERY_TYPE", "string", "dingtalk_enterprise_robot", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_DELIVERY_CONNECTOR_ID", "string", "connector-dingtalk-enterprise-default", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_SOURCE_CONNECTOR_ID", "string", "connector-dingtalk-stream-default", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_PROJECT_CODE", "string", "default", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_ENVIRONMENT", "string", "", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_BASE", "string", "", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_WORKSHOP", "string", "", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_SERVICE", "string", "", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_OPEN_CONVERSATION_ID", "string", "", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("DINGTALK_DEFAULT_ROBOT_CODE", "string", "", service_names=("api-server", "dingtalk-stream-ingress")),
    RuntimeConfigDefinitionSpec("RABBITMQ_CONSUMER_HEARTBEAT_SECONDS", "int", 900, service_names=("agent-worker",)),
    RuntimeConfigDefinitionSpec("RABBITMQ_CONSUMER_RECONNECT_SECONDS", "int", 5, service_names=("agent-worker",)),
    RuntimeConfigDefinitionSpec("AGENT_MAX_RETRY_COUNT", "int", 3, service_names=("api-server", "agent-worker")),
    RuntimeConfigDefinitionSpec("AGENT_RETRY_DELAY_SECONDS", "int", 30, service_names=("api-server", "agent-worker")),
)


class RuntimeConfigRegistry:
    def __init__(self, repository: PlatformConfigRepository) -> None:
        self.repository = repository

    def ensure_builtin_definitions(self) -> None:
        for definition in RUNTIME_CONFIG_DEFINITIONS:
            self.repository.upsert_runtime_config_definition(
                key=definition.key,
                value_type=definition.value_type,
                default=definition.default,
                sensitive=definition.sensitive,
                bootstrap_only=definition.bootstrap_only,
                service_names=list(definition.service_names),
                description=definition.description,
            )

    def env_migration_list(self) -> list[dict[str, Any]]:
        return [
            {
                "key": item.key,
                "value_type": item.value_type,
                "default": item.default,
                "sensitive": item.sensitive,
                "bootstrap_only": item.bootstrap_only,
                "service_names": list(item.service_names),
                "target": "bootstrap-env"
                if item.bootstrap_only
                else ("secret-management" if item.sensitive else "runtime-config"),
            }
            for item in RUNTIME_CONFIG_DEFINITIONS
        ]


class RuntimeConfigSnapshotBuilder:
    def __init__(self, repository: PlatformConfigRepository) -> None:
        self.repository = repository

    def build_snapshot(
        self,
        *,
        service_name: str = "",
        scopes: dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> dict[str, Any]:
        definitions = {
            item["key"]: item
            for item in self.repository.list_runtime_config_definitions(
                include_disabled=include_disabled
            )
        }
        values = self.repository.list_runtime_config_values(include_disabled=include_disabled)
        selected: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        scopes = scopes or {}
        for value in values:
            if value["status"] != "enabled":
                continue
            definition = definitions.get(str(value["key"]))
            if not definition or definition.get("status") != "enabled":
                continue
            if not _matches(value, service_name=service_name, scopes=scopes):
                continue
            previous = selected.get(str(value["key"]))
            if previous is None or _priority(value) >= _priority(previous):
                selected[str(value["key"])] = value

        effective: dict[str, Any] = {}
        for key, definition in definitions.items():
            if definition.get("status") != "enabled":
                continue
            chosen = selected.get(key)
            if chosen:
                source = f"db:{chosen['scope_type']}:{chosen['scope_code']}:{chosen['service_name']}"
                if chosen.get("secret_ref"):
                    effective[key] = {
                        "value": None,
                        "secret_ref": chosen["secret_ref"],
                        "configured": True,
                        "source": source,
                        "sensitive": True,
                        "revision": chosen["revision"],
                    }
                else:
                    value_type = validate_config_value_type(str(definition["value_type"]))
                    try:
                        value = coerce_runtime_value(chosen.get("value"), value_type)
                    except PlatformConfigValidationError as exc:
                        errors.append(exc.safe_message)
                        continue
                    effective[key] = {
                        "value": value,
                        "secret_ref": "",
                        "configured": value is not None,
                        "source": source,
                        "sensitive": bool(definition.get("sensitive")),
                        "revision": chosen["revision"],
                    }
            else:
                effective[key] = {
                    "value": definition.get("default"),
                    "secret_ref": "",
                    "configured": definition.get("default") not in (None, ""),
                    "source": "definition-default",
                    "sensitive": bool(definition.get("sensitive")),
                    "revision": definition["revision"],
                }
        payload = {
            "source": "database" if not errors else "database-invalid",
            "service_name": service_name,
            "revision": self.repository.runtime_config_revision(),
            "effective": effective,
            "errors": errors,
        }
        payload["config_hash"] = hashlib.sha256(
            json.dumps(_masked_effective(effective), ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        payload["effective_masked"] = _masked_effective(effective)
        return payload


def validate_runtime_config_definition_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value_type = validate_config_value_type(str(payload.get("value_type") or "string"))
    default = payload.get("default")
    if default is not None and default != "":
        coerce_runtime_value(default, value_type, field="default")
    return {
        "key": str(payload.get("key") or "").strip(),
        "value_type": value_type.value,
        "default": default,
        "sensitive": bool(payload.get("sensitive", value_type.value == "secret_ref")),
        "bootstrap_only": bool(payload.get("bootstrap_only")),
        "service_names": [str(item) for item in (payload.get("service_names") or [])],
        "description": str(payload.get("description") or ""),
        "status": str(payload.get("status") or "enabled"),
    }


def _matches(value: dict[str, Any], *, service_name: str, scopes: dict[str, str]) -> bool:
    value_service = str(value.get("service_name") or "")
    if value_service and value_service != service_name:
        return False
    scope_type = str(value.get("scope_type") or "global")
    scope_code = str(value.get("scope_code") or "*")
    if scope_type == "global":
        return scope_code in {"", "*"}
    if scope_type == "service":
        return scope_code in {"", "*", service_name} or value_service == service_name
    return scopes.get(scope_type) == scope_code


def _priority(value: dict[str, Any]) -> int:
    scope_type = validate_runtime_scope_type(str(value.get("scope_type") or "global")).value
    base = {
        "global": 10,
        "service": 20,
        "project": 30,
        "environment": 40,
        "base": 50,
        "workshop": 60,
        "connector": 70,
    }[scope_type]
    if value.get("service_name"):
        base += 5
    return base


def _masked_effective(effective: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in effective.items():
        if item.get("sensitive"):
            result[key] = {
                "configured": bool(item.get("configured")),
                "secret_ref": item.get("secret_ref") or "",
                "source": item.get("source"),
                "revision": item.get("revision"),
            }
        else:
            result[key] = {
                "value": item.get("value"),
                "source": item.get("source"),
                "revision": item.get("revision"),
            }
    return result
