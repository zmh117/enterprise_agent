from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.modules.business_application.domain.models import (
    ActorPolicy,
    ApplicationStatus,
    DeliveryType,
    TriggerType,
)
from app.shared.exceptions import NonRetryableExecutionError

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
ENVIRONMENTS = {"test", "production"}
SESSION_POLICY_FIELDS = {
    "conversation_mode",
    "recent_message_limit",
    "retention_days",
    "continuous_conversation_enabled",
    "attachments_enabled",
}
EXECUTION_POLICY_FIELDS = {"max_turns", "timeout_seconds", "max_tool_calls"}
TRIGGER_CONFIG_FIELDS = {"conversation_type", "require_mention", "webhook_definition_id"}
DELIVERY_CONFIG_FIELDS = {"target_reference", "reply_mode"}
FORBIDDEN_KEYS = {
    "url",
    "base_url",
    "endpoint",
    "dsn",
    "sql",
    "logql",
    "shell",
    "command",
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "database",
    "redis",
    "loki",
    "headers",
}
FORBIDDEN_VALUE_PATTERNS = (
    "://",
    "select ",
    "insert ",
    "update ",
    "delete ",
    "drop ",
    "alter ",
    "redis://",
    "jdbc:",
    "curl ",
    "bash ",
    "powershell ",
)


def validate_code(value: str, *, field: str = "code") -> str:
    normalized = value.strip().lower()
    if not 2 <= len(normalized) <= 120 or not CODE_PATTERN.fullmatch(normalized):
        raise validation_error(field, "必须使用稳定的小写编码")
    return normalized


def validate_environment(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ENVIRONMENTS:
        raise validation_error(
            "environment",
            "仅支持业务应用的 test 或 production 环境",
        )
    return normalized


def validate_status(value: str) -> str:
    try:
        return ApplicationStatus(value).value
    except ValueError as exc:
        raise validation_error("status", "不支持此业务应用状态") from exc


def normalize_routing_key(value: str) -> str:
    normalized = " ".join(value.strip().lower().split())
    if not normalized or len(normalized) > 240:
        raise validation_error("routing_key", "必须填写路由键且长度不能超出限制")
    return normalized


def validate_session_policy(value: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(value, SESSION_POLICY_FIELDS, "session_policy")
    normalized: dict[str, Any] = {
        "conversation_mode": str(value.get("conversation_mode") or "channel").strip(),
        "recent_message_limit": int(value.get("recent_message_limit") or 20),
        "retention_days": int(value.get("retention_days") or 30),
        "continuous_conversation_enabled": bool(
            value.get("continuous_conversation_enabled", False)
        ),
        "attachments_enabled": bool(value.get("attachments_enabled", False)),
    }
    if normalized["conversation_mode"] != "channel":
        raise validation_error(
            "session_policy.conversation_mode",
            "仅支持按渠道会话；旧按主体/按应用模式只可查看历史",
        )
    if not 1 <= normalized["recent_message_limit"] <= 100:
        raise validation_error("session_policy.recent_message_limit", "必须在 1 到 100 之间")
    if not 1 <= normalized["retention_days"] <= 3650:
        raise validation_error("session_policy.retention_days", "必须在 1 到 3650 之间")
    return normalized


def validate_execution_policy(value: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(value, EXECUTION_POLICY_FIELDS, "execution_policy")
    normalized: dict[str, int] = {
        "max_turns": int(value.get("max_turns") or 12),
        "timeout_seconds": int(value.get("timeout_seconds") or 300),
        "max_tool_calls": int(value.get("max_tool_calls") or 30),
    }
    ranges = {
        "max_turns": (1, 100),
        "timeout_seconds": (10, 3600),
        "max_tool_calls": (0, 200),
    }
    for key, (minimum, maximum) in ranges.items():
        if not minimum <= normalized[key] <= maximum:
            raise validation_error(f"execution_policy.{key}", f"必须在 {minimum} 到 {maximum} 之间")
    return normalized


def validate_trigger(value: dict[str, Any], index: int) -> dict[str, Any]:
    allowed = {
        "trigger_type",
        "connector_id",
        "routing_key",
        "actor_policy",
        "service_account_user_id",
        "enabled",
        "config",
    }
    _reject_unknown(value, allowed, f"triggers.{index}")
    try:
        trigger_type = TriggerType(str(value.get("trigger_type") or "")).value
        actor_policy = ActorPolicy(str(value.get("actor_policy") or "")).value
    except ValueError as exc:
        raise validation_error(f"triggers.{index}", "触发器或主体策略无效") from exc
    service_account = str(value.get("service_account_user_id") or "").strip()
    if trigger_type == TriggerType.WEBHOOK and actor_policy != ActorPolicy.SERVICE_ACCOUNT:
        raise validation_error(
            f"triggers.{index}.actor_policy",
            "Webhook 必须使用 SERVICE_ACCOUNT",
        )
    if trigger_type != TriggerType.WEBHOOK and actor_policy != ActorPolicy.CURRENT_SENDER:
        raise validation_error(
            f"triggers.{index}.actor_policy",
            "钉钉必须使用 CURRENT_SENDER",
        )
    if actor_policy == ActorPolicy.SERVICE_ACCOUNT and not service_account:
        raise validation_error(f"triggers.{index}.service_account_user_id", "必须选择服务账号")
    if actor_policy == ActorPolicy.CURRENT_SENDER and service_account:
        raise validation_error(
            f"triggers.{index}.service_account_user_id",
            "当前发送人触发器不能设置服务账号",
        )
    config = dict(value.get("config") or {})
    _reject_unknown(config, TRIGGER_CONFIG_FIELDS, f"triggers.{index}.config")
    reject_dangerous_content(config, field=f"triggers.{index}.config")
    connector_id = str(value.get("connector_id") or "").strip()
    if not connector_id or len(connector_id) > 200:
        raise validation_error(f"triggers.{index}.connector_id", "必须选择连接器")
    return {
        "trigger_type": trigger_type,
        "connector_id": connector_id,
        "routing_key": str(value.get("routing_key") or "").strip(),
        "normalized_routing_key": normalize_routing_key(str(value.get("routing_key") or "")),
        "actor_policy": actor_policy,
        "service_account_user_id": service_account,
        "enabled": bool(value.get("enabled", True)),
        "config": config,
    }


def validate_delivery(value: dict[str, Any], index: int) -> dict[str, Any]:
    allowed = {"delivery_type", "connector_id", "enabled", "config"}
    _reject_unknown(value, allowed, f"deliveries.{index}")
    try:
        delivery_type = DeliveryType(str(value.get("delivery_type") or "")).value
    except ValueError as exc:
        raise validation_error(f"deliveries.{index}.delivery_type", "投递类型无效") from exc
    connector_id = str(value.get("connector_id") or "").strip()
    if not connector_id or len(connector_id) > 200:
        raise validation_error(f"deliveries.{index}.connector_id", "必须选择连接器")
    config = dict(value.get("config") or {})
    _reject_unknown(config, DELIVERY_CONFIG_FIELDS, f"deliveries.{index}.config")
    reject_dangerous_content(config, field=f"deliveries.{index}.config")
    return {
        "delivery_type": delivery_type,
        "connector_id": connector_id,
        "enabled": bool(value.get("enabled", True)),
        "config": config,
    }


def reject_dangerous_content(value: Any, *, field: str = "config") -> None:
    errors: list[dict[str, str]] = []

    def walk(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
                if normalized in FORBIDDEN_KEYS:
                    errors.append({"field": f"{path}.{key}", "message": "不允许使用此字段"})
                    continue
                walk(child, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}.{index}")
        elif isinstance(item, str):
            lowered = item.lower()
            if any(pattern in lowered for pattern in FORBIDDEN_VALUE_PATTERNS):
                errors.append({"field": path, "message": "不允许使用不安全内容"})

    walk(value, field)
    if errors:
        raise NonRetryableExecutionError(
            "Unsafe Business Application configuration",
            safe_message="业务应用配置包含不安全字段",
            error_code="validation_failed",
            field_errors=errors,
        )


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def snapshot_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def verify_snapshot(value: Any, expected_hash: str) -> bool:
    return bool(expected_hash) and snapshot_hash(value) == expected_hash


def validation_error(field: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"{field}: {message}",
        safe_message="业务应用配置无效",
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )


def _reject_unknown(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise NonRetryableExecutionError(
            f"Unknown fields in {field}",
            safe_message="业务应用配置无效",
            error_code="validation_failed",
            field_errors=[{"field": f"{field}.{key}", "message": "未知字段"} for key in unknown],
        )
