from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError


class TriggerSchema(StrEnum):
    GRAFANA_ALERTMANAGER_V1 = "grafana_alertmanager_v1"
    GENERIC_JSON_V1 = "generic_json_v1"


class AuthenticationType(StrEnum):
    BEARER_V1 = "bearer_v1"


class WebhookEventStatus(StrEnum):
    REJECTED_AUTH = "REJECTED_AUTH"
    REJECTED = "REJECTED"
    IGNORED = "IGNORED"
    ACCEPTED = "ACCEPTED"
    DISPATCH_PENDING = "DISPATCH_PENDING"
    JOB_CREATED = "JOB_CREATED"
    DISPATCH_FAILED = "DISPATCH_FAILED"


WEBHOOK_ERROR_CODES = frozenset(
    {
        "webhook_not_found",
        "webhook_disabled",
        "webhook_not_published",
        "webhook_invalid_content_type",
        "webhook_payload_too_large",
        "webhook_payload_invalid",
        "webhook_auth_required",
        "webhook_auth_failed",
        "webhook_rate_limited",
        "webhook_mapping_failed",
        "webhook_scope_denied",
        "webhook_dispatch_failed",
    }
)


TRIGGER_ACTIONS = frozenset({"read", "edit", "publish", "rotate", "manage_service_account"})
PUBLIC_ID_RE = re.compile(r"^wh_[A-Za-z0-9_-]{32,96}$")
CODE_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
SECRET_REF_PREFIXES = ("secret://platform/",)
ALLOWED_CONFIG_KEYS = frozenset({"schema_version", "adapter", "authentication", "role_ids"})
DEFAULT_LIMITS = {"requests_per_minute": 60, "max_in_flight": 10, "max_alerts": 20}
DEFAULT_COOLDOWN_SECONDS = 300


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """The public Webhook contract has no Agent, delivery or custom mapping."""
    ensure_no_secret_values(config)
    authentication = _object(config.get("authentication"))
    roles = config.get("role_ids", [])
    if (
        config.get("schema_version", 2) != 2
        or not isinstance(roles, list)
        or len(roles) > 20
        or any(not isinstance(role, str) or not role.strip() for role in roles)
        or set(authentication) - {"type", "secret_ref"}
    ):
        raise NonRetryableExecutionError(
            "Invalid Webhook configuration",
            safe_message="请使用简化 Webhook 配置重新保存",
            error_code="validation_failed",
        )
    return {
        "schema_version": 2,
        "adapter": str(config.get("adapter") or ""),
        "authentication": {
            "type": str(authentication.get("type") or ""),
            "secret_ref": str(authentication.get("secret_ref") or ""),
        },
        "role_ids": sorted(set(role.strip() for role in roles)),
    }


def is_strong_bearer_token(value: str) -> bool:
    encoded = value.encode("utf-8")
    return (
        32 <= len(encoded) <= 4096
        and value == value.strip()
        and all(33 <= ord(character) <= 126 for character in value)
    )


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(config).encode()).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ensure_no_secret_values(config: dict[str, Any]) -> None:
    serialized = canonical_json(config).lower()
    forbidden = ('"token":', '"password":', '"secret":', '"api_key":')
    if any(marker in serialized for marker in forbidden):
        raise NonRetryableExecutionError(
            "Trigger config contains a secret value field",
            safe_message="触发器配置只能包含凭据引用",
            error_code="validation_failed",
        )
    unknown = sorted(set(config) - ALLOWED_CONFIG_KEYS)
    if unknown:
        raise NonRetryableExecutionError(
            "Trigger config contains unsupported top-level fields",
            safe_message="触发器配置包含不支持的字段",
            error_code="validation_failed",
            field_errors=[{"field": str(field), "message": "此字段不可配置"} for field in unknown],
        )
    prohibited_keys: list[str] = []

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                field = f"{path}.{key}".strip(".")
                lowered = str(key).lower()
                if any(
                    token in lowered
                    for token in ("script", "javascript", "python", "shell", "function")
                ):
                    prohibited_keys.append(field)
                walk(item, field)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}.{index}".strip("."))

    walk(config)
    if prohibited_keys:
        raise NonRetryableExecutionError(
            "Trigger config contains executable fields",
            safe_message="不支持可执行映射字段",
            error_code="validation_failed",
            field_errors=[
                {"field": field, "message": "禁止使用脚本和函数"} for field in prohibited_keys
            ],
        )


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
