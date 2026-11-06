from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.modules.webhook.domain.models import DEFAULT_LIMITS
from app.shared.exceptions import NonRetryableExecutionError


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
        if config.get("schema_version") != 2:
            raise NonRetryableExecutionError(
                "Legacy Webhook config",
                safe_message="请重新保存简化 Webhook 配置",
                error_code="webhook_mapping_failed",
            )
        adapter = str(config.get("adapter") or "")
        if adapter == "grafana_alertmanager_v1":
            return self._grafana(config=config, payload=payload)
        if adapter == "generic_json_v1":
            return self._generic(config=config, payload=payload)
        raise NonRetryableExecutionError(
            "Unsupported Webhook adapter",
            safe_message="不支持此 Webhook 适配器",
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
        alerts = payload.get("alerts", [])
        if (
            payload.get("status") not in {"firing", "resolved"}
            or not isinstance(alerts, list)
            or len(alerts) > DEFAULT_LIMITS["max_alerts"]
            or any(not isinstance(alert, dict) for alert in alerts)
        ):
            raise NonRetryableExecutionError(
                "Invalid Grafana payload",
                safe_message="请使用 Grafana 标准告警报文，单次最多20条告警",
                error_code="webhook_mapping_failed",
            )
        status = str(payload.get("status") or "").lower()
        event_id = _grafana_event_id(payload)
        summary = _grafana_summary(payload, max_alerts=DEFAULT_LIMITS["max_alerts"])
        ignored = status != "firing"
        message = "" if ignored else _grafana_message(payload)[: self.max_message_chars]
        return MappingResult(
            ignored=ignored,
            reason="not_firing" if ignored else "",
            external_event_id=event_id,
            dedup_key=f"grafana:{event_id}:{status or 'unknown'}",
            message=message,
            variables={},
            routing={},
            safe_summary=summary,
        )

    def _generic(self, *, config: dict[str, Any], payload: dict[str, Any]) -> MappingResult:
        event_id = payload.get("id")
        message = payload.get("message")
        if (
            set(payload) != {"id", "message"}
            or not isinstance(event_id, str)
            or not event_id.strip()
            or len(event_id) > 512
            or not isinstance(message, str)
            or not message.strip()
            or len(message) > self.max_message_chars
        ):
            raise NonRetryableExecutionError(
                "Invalid generic Webhook payload",
                safe_message=f"通用 JSON 只接受非空字符串 id（最多512字符）和 message（最多{self.max_message_chars}字符）",
                error_code="webhook_mapping_failed",
            )
        event_id = event_id.strip()
        return MappingResult(
            ignored=False,
            reason="",
            external_event_id=event_id,
            dedup_key=f"generic:{event_id}",
            message=message,
            variables={},
            routing={},
            safe_summary={"event_id": event_id, "message_chars": len(message)},
        )


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
    return (
        "payload:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
    )


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
                "labels": _mask(
                    alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
                ),
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
        if lowered.startswith(("http://", "https://", "bearer ")) or "-----begin " in lowered:
            return "***"
        return value[:1000]
    return value
