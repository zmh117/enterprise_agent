from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.modules.channel.domain.channel_event import safe_payload_summary
from app.modules.webhook.domain.models import CONDITION_OPERATORS, ROUTING_FIELDS
from app.shared.exceptions import NonRetryableExecutionError


_VARIABLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SENSITIVE_KEY_RE = re.compile(
    r"token|secret|password|signature|authorization|cookie|credential|webhook|url",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MappingResult:
    ignored: bool
    reason: str
    external_event_id: str
    dedup_key: str
    message: str
    variables: dict[str, Any]
    routing: dict[str, str]
    safe_summary: dict[str, Any]

    def normalized_event(self, *, delivery: dict[str, Any]) -> dict[str, Any]:
        return {
            "external_event_id": self.external_event_id,
            "dedup_key": self.dedup_key,
            "message": self.message,
            "variables": _mask(self.variables),
            "routing": self.routing,
            "delivery": delivery,
        }


class WebhookMapper:
    def __init__(self, *, max_message_chars: int = 4000, max_summary_chars: int = 4000) -> None:
        self.max_message_chars = max_message_chars
        self.max_summary_chars = max_summary_chars

    def map(self, *, config: dict[str, Any], payload: dict[str, Any]) -> MappingResult:
        adapter = str(config.get("adapter") or "")
        if adapter == "grafana_alertmanager_v1":
            return self._grafana(config=config, payload=payload)
        if adapter == "generic_json_v1":
            return self._generic(config=config, payload=payload)
        raise NonRetryableExecutionError(
            "Unsupported Webhook adapter",
            safe_message="Webhook adapter is unsupported",
            error_code="webhook_mapping_failed",
        )

    def preview(self, *, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        result = self.map(config=config, payload=payload)
        return {
            "ignored": result.ignored,
            "reason": result.reason,
            "external_event_id": result.external_event_id,
            "dedup_key": result.dedup_key,
            "message": result.message,
            "variables": _mask(result.variables),
            "routing": result.routing,
            "safe_summary": result.safe_summary,
        }

    def _grafana(self, *, config: dict[str, Any], payload: dict[str, Any]) -> MappingResult:
        status = str(payload.get("status") or "").lower()
        event_id = _grafana_event_id(payload)
        variables = self._extract_variables(config, payload)
        summary = _grafana_summary(payload, max_alerts=int(config["limits"]["max_alerts"]))
        if status != "firing":
            return MappingResult(
                ignored=True,
                reason="not_firing",
                external_event_id=event_id,
                dedup_key=f"grafana:{event_id}:{status or 'unknown'}",
                message="",
                variables=variables,
                routing={
                    field: str(config["routing"][field].get("value") or "")
                    if config["routing"][field].get("mode") == "fixed"
                    else ""
                    for field in ROUTING_FIELDS
                },
                safe_summary=summary,
            )
        message = self._render_message(config, variables, fallback=_grafana_message(payload))
        routing = self._routing(config, payload)
        return MappingResult(
            ignored=False,
            reason="",
            external_event_id=event_id,
            dedup_key=f"grafana:{event_id}:firing",
            message=message,
            variables=variables,
            routing=routing,
            safe_summary=summary,
        )

    def _generic(self, *, config: dict[str, Any], payload: dict[str, Any]) -> MappingResult:
        mapping = config["mapping"]
        variables = self._extract_variables(config, payload)
        event_pointer = str(mapping.get("event_id_pointer") or "")
        event_id = str(json_pointer(payload, event_pointer) if event_pointer else "").strip()
        if not event_id:
            raise NonRetryableExecutionError(
                "Generic Webhook event ID is missing",
                safe_message="Webhook event ID is missing",
                error_code="webhook_mapping_failed",
                field_errors=[{"field": "mapping.event_id_pointer", "message": "Value is missing"}],
            )
        if not self._filters_match(mapping.get("filters") or [], payload):
            return MappingResult(
                ignored=True,
                reason="filter_not_matched",
                external_event_id=event_id,
                dedup_key=f"generic:{event_id}:ignored",
                message="",
                variables=variables,
                routing=self._routing(config, payload),
                safe_summary=safe_payload_summary(_mask(payload), max_chars=self.max_summary_chars),
            )
        message = self._render_message(config, variables, fallback="")
        if not message:
            raise NonRetryableExecutionError(
                "Generic Webhook message is empty",
                safe_message="Webhook message is empty",
                error_code="webhook_mapping_failed",
            )
        return MappingResult(
            ignored=False,
            reason="",
            external_event_id=event_id,
            dedup_key=f"generic:{event_id}",
            message=message,
            variables=variables,
            routing=self._routing(config, payload),
            safe_summary=safe_payload_summary(_mask(payload), max_chars=self.max_summary_chars),
        )

    def _extract_variables(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            name: _bounded_scalar(json_pointer(payload, pointer))
            for name, pointer in config["mapping"]["variables"].items()
        }

    def _filters_match(self, filters: list[Any], payload: dict[str, Any]) -> bool:
        for condition in filters:
            if not isinstance(condition, dict):
                return False
            pointer = str(condition.get("pointer") or "")
            operator = str(condition.get("operator") or "")
            if operator not in CONDITION_OPERATORS:
                return False
            exists, actual = try_json_pointer(payload, pointer)
            expected = condition.get("value")
            if operator == "exists" and exists is not bool(expected if expected is not None else True):
                return False
            if operator == "equals" and actual != expected:
                return False
            if operator == "not_equals" and actual == expected:
                return False
            if operator == "in" and (
                not isinstance(expected, list) or actual not in expected
            ):
                return False
        return True

    def _routing(self, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for field in ROUTING_FIELDS:
            rule = config["routing"][field]
            mode = str(rule.get("mode") or "fixed")
            if mode == "fixed":
                value = str(rule.get("value") or "")
            else:
                value = str(json_pointer(payload, str(rule.get("pointer") or "")) or "")
                if value not in set(rule.get("allowed_values") or []):
                    raise NonRetryableExecutionError(
                        f"Webhook routing value is not allowed for {field}",
                        safe_message="Webhook routing value is not allowed",
                        error_code="webhook_scope_denied",
                        field_errors=[{"field": f"routing.{field}", "message": "Value is outside allowlist"}],
                    )
            result[field] = value
        if not result["project_code"]:
            raise NonRetryableExecutionError(
                "Webhook project routing is empty",
                safe_message="Webhook project routing is required",
                error_code="webhook_scope_denied",
            )
        return result

    def _render_message(
        self, config: dict[str, Any], variables: dict[str, Any], *, fallback: str
    ) -> str:
        template = str(config["mapping"].get("message_template") or "")
        if not template:
            return fallback[: self.max_message_chars]
        rendered = _VARIABLE_RE.sub(
            lambda match: str(variables.get(match.group(1), "")), template
        )
        return rendered[: self.max_message_chars]


def validate_pointer(pointer: str) -> bool:
    if pointer == "":
        return True
    if not pointer.startswith("/") or len(pointer) > 512:
        return False
    parts = pointer[1:].split("/")
    return len(parts) <= 32 and all(len(part) <= 128 for part in parts)


def json_pointer(value: Any, pointer: str) -> Any:
    exists, result = try_json_pointer(value, pointer)
    if not exists:
        return None
    return result


def try_json_pointer(value: Any, pointer: str) -> tuple[bool, Any]:
    if not validate_pointer(pointer):
        return False, None
    if pointer == "":
        return True, value
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _grafana_event_id(payload: dict[str, Any]) -> str:
    group_key = str(payload.get("groupKey") or "").strip()
    if group_key:
        return group_key[:512]
    fingerprints = sorted(
        str(alert.get("fingerprint") or "")
        for alert in (payload.get("alerts") or [])
        if isinstance(alert, dict) and alert.get("fingerprint")
    )
    if fingerprints:
        return "fingerprints:" + hashlib.sha256("|".join(fingerprints).encode()).hexdigest()
    return "payload:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _grafana_message(payload: dict[str, Any]) -> str:
    annotations = payload.get("commonAnnotations")
    if isinstance(annotations, dict):
        summary = annotations.get("summary") or annotations.get("description")
        if summary:
            return str(summary)
    return str(payload.get("title") or "Grafana firing alert")


def _grafana_summary(payload: dict[str, Any], *, max_alerts: int) -> dict[str, Any]:
    alerts_value = payload.get("alerts")
    alerts: list[Any] = alerts_value if isinstance(alerts_value, list) else []
    bounded_alerts: list[dict[str, Any]] = []
    for alert in alerts[:max_alerts]:
        if not isinstance(alert, dict):
            continue
        bounded_alerts.append(
            {
                "status": str(alert.get("status") or "")[:40],
                "fingerprint": str(alert.get("fingerprint") or "")[:128],
                "labels": _mask(alert.get("labels") if isinstance(alert.get("labels"), dict) else {}),
                "annotations": _mask(
                    alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}
                ),
            }
        )
    return {
        "status": str(payload.get("status") or "")[:40],
        "group_key": str(payload.get("groupKey") or "")[:512],
        "common_labels": _mask(
            payload.get("commonLabels") if isinstance(payload.get("commonLabels"), dict) else {}
        ),
        "common_annotations": _mask(
            payload.get("commonAnnotations")
            if isinstance(payload.get("commonAnnotations"), dict)
            else {}
        ),
        "alerts": bounded_alerts,
        "alert_count": len(alerts),
        "alerts_truncated": len(alerts) > len(bounded_alerts),
    }


def _bounded_scalar(value: Any, max_chars: int = 1000) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)[:max_chars] if isinstance(value, str) else value
    return json.dumps(_mask(value), ensure_ascii=False, sort_keys=True, default=str)[:max_chars]


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "***" if _SENSITIVE_KEY_RE.search(str(key)) else _mask(item)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [_mask(item) for item in value[:100]]
    if isinstance(value, str):
        lowered = value.lower()
        if (
            lowered.startswith(("http://", "https://", "bearer "))
            or "-----begin " in lowered
        ):
            return "***"
        return value[:1000]
    return value
