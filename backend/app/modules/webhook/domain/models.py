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
    HMAC_SHA256_V1 = "hmac_sha256_v1"


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
        "webhook_signature_expired",
        "webhook_replay_detected",
        "webhook_rate_limited",
        "webhook_mapping_failed",
        "webhook_scope_denied",
        "webhook_dispatch_failed",
    }
)


TRIGGER_ACTIONS = frozenset(
    {"read", "edit", "publish", "rotate", "manage_service_account"}
)
CONDITION_OPERATORS = frozenset({"exists", "equals", "in", "not_equals"})
ROUTING_FIELDS = ("project_code", "environment", "base", "workshop", "service")
PUBLIC_ID_RE = re.compile(r"^wh_[A-Za-z0-9_-]{32,96}$")
CODE_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
SERVICE_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{0,128}$")
SECRET_REF_PREFIXES = ("env:", "secret://", "vault:", "kms:")
ALLOWED_CONFIG_KEYS = frozenset(
    {
        "schema_version",
        "adapter",
        "authentication",
        "mapping",
        "routing",
        "agent",
        "delivery",
        "idempotency",
        "limits",
    }
)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return the typed, deterministic Trigger configuration persisted in revisions."""
    adapter = str(config.get("adapter") or "")
    authentication = _object(config.get("authentication"))
    mapping = _object(config.get("mapping"))
    routing = _object(config.get("routing"))
    agent = _object(config.get("agent"))
    delivery = _object(config.get("delivery"))
    idempotency = _object(config.get("idempotency"))
    limits = _object(config.get("limits"))
    variables = _object(mapping.get("variables"))
    filters = _list(mapping.get("filters"))
    normalized_routing: dict[str, dict[str, Any]] = {}
    for field in ROUTING_FIELDS:
        rule = _object(routing.get(field))
        normalized_routing[field] = {
            "mode": str(rule.get("mode") or "fixed"),
            "value": str(rule.get("value") or ""),
            "pointer": str(rule.get("pointer") or ""),
            "allowed_values": sorted(
                {str(value) for value in _list(rule.get("allowed_values")) if str(value)}
            ),
        }
    return {
        "schema_version": int(config.get("schema_version") or 1),
        "adapter": adapter,
        "authentication": {
            "type": str(authentication.get("type") or ""),
            "secret_ref": str(authentication.get("secret_ref") or ""),
            "timestamp_header": str(
                authentication.get("timestamp_header") or "x-webhook-timestamp"
            ).lower(),
            "nonce_header": str(
                authentication.get("nonce_header") or "x-webhook-nonce"
            ).lower(),
            "signature_header": str(
                authentication.get("signature_header") or "x-webhook-signature"
            ).lower(),
            "window_seconds": int(authentication.get("window_seconds") or 300),
        },
        "mapping": {
            "variables": {
                str(name): str(pointer)
                for name, pointer in sorted(variables.items(), key=lambda item: str(item[0]))
            },
            "filters": [
                {
                    "pointer": str(_object(item).get("pointer") or ""),
                    "operator": str(_object(item).get("operator") or ""),
                    "value": _object(item).get("value"),
                }
                for item in filters
                if isinstance(item, dict)
            ],
            "message_template": str(mapping.get("message_template") or "").strip(),
            "event_id_pointer": str(mapping.get("event_id_pointer") or ""),
            "status_pointer": str(mapping.get("status_pointer") or ""),
        },
        "routing": normalized_routing,
        "agent": {
            "code": str(agent.get("code") or "default-diagnostic-agent"),
            "publication_id": str(agent.get("publication_id") or ""),
        },
        "delivery": {
            "type": str(delivery.get("type") or "none"),
            "connector_id": str(delivery.get("connector_id") or ""),
            "target": _object(delivery.get("target")),
            "options": _object(delivery.get("options")),
        },
        "idempotency": {
            "cooldown_seconds": int(idempotency.get("cooldown_seconds") or 300),
        },
        "limits": {
            "requests_per_minute": int(limits.get("requests_per_minute") or 60),
            "max_in_flight": int(limits.get("max_in_flight") or 10),
            "max_alerts": int(limits.get("max_alerts") or 20),
        },
    }


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
            safe_message="Trigger configuration must contain secret references only",
            error_code="validation_failed",
        )
    unknown = sorted(set(config) - ALLOWED_CONFIG_KEYS)
    if unknown:
        raise NonRetryableExecutionError(
            "Trigger config contains unsupported top-level fields",
            safe_message="Trigger configuration contains unsupported fields",
            error_code="validation_failed",
            field_errors=[
                {"field": str(field), "message": "Field is not configurable"}
                for field in unknown
            ],
        )
    prohibited_keys: list[str] = []

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                field = f"{path}.{key}".strip(".")
                lowered = str(key).lower()
                if any(token in lowered for token in ("script", "javascript", "python", "shell", "function")):
                    prohibited_keys.append(field)
                walk(item, field)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}.{index}".strip("."))

    walk(config)
    if prohibited_keys:
        raise NonRetryableExecutionError(
            "Trigger config contains executable fields",
            safe_message="Executable mapping fields are not supported",
            error_code="validation_failed",
            field_errors=[
                {"field": field, "message": "Scripts and functions are forbidden"}
                for field in prohibited_keys
            ],
        )


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple, set)) else []
