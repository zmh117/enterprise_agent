from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast


@dataclass(frozen=True)
class ChannelSource:
    type: str
    connector_id: str
    event_id: str
    actor_id: str
    conversation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingContext:
    project_code: str = "default"
    environment: str = ""
    base: str = ""
    workshop: str = ""
    service: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "RoutingContext":
        value = value or {}
        return cls(
            project_code=str(value.get("project_code") or "default"),
            environment=str(value.get("environment") or ""),
            base=str(value.get("base") or ""),
            workshop=str(value.get("workshop") or ""),
            service=str(value.get("service") or ""),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "project_code": self.project_code,
            "environment": self.environment,
            "base": self.base,
            "workshop": self.workshop,
            "service": self.service,
        }


@dataclass(frozen=True)
class ReplyRoute:
    type: str = "none"
    connector_id: str = ""
    target: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ReplyRoute":
        value = value or {"type": "none"}
        route_type = str(value.get("type") or "none")
        return cls(
            type=route_type,
            connector_id=str(value.get("connector_id") or ""),
            target=_dict_value(value.get("target")),
            options=_dict_value(value.get("options")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "connector_id": self.connector_id,
            "target": self.target,
            "options": self.options,
        }


@dataclass(frozen=True)
class ChannelEvent:
    source: ChannelSource
    delivery: ReplyRoute
    routing: RoutingContext
    message: str
    raw_payload_summary: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    correlation_id: str | None = None

    @property
    def effective_idempotency_key(self) -> str:
        if self.idempotency_key:
            return self.idempotency_key
        return f"{self.source.type}:{self.source.connector_id}:{self.source.event_id}"


def safe_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def safe_payload_summary(payload: dict[str, Any], *, max_chars: int = 2000) -> dict[str, Any]:
    masked = _mask_sensitive(payload)
    text = json.dumps(masked, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) <= max_chars:
        return cast(dict[str, Any], masked)
    return {"truncated": True, "chars": len(text), "preview": text[:max_chars]}


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(
                token in lowered
                for token in ("token", "secret", "sign", "password", "webhook", "url", "mobile")
            ):
                result[str(key)] = "***"
            else:
                result[str(key)] = _mask_sensitive(item)
        return result
    if isinstance(value, list):
        return [_mask_sensitive(item) for item in value[:20]]
    return value
