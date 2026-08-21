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
from app.modules.document_processing import (
    DocumentProcessingProfileCode,
    document_processing_profile_snapshot,
    normalize_document_processing_profile_code,
)
from app.modules.file_workspace.text_format_policy import (
    FileFormatPolicyVersion,
    normalize_file_format_policy_version,
)
from app.shared.exceptions import NonRetryableExecutionError

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
ENVIRONMENTS = {"local"}
TASK_WORKSPACE_RETENTION_PERIODS = {"DAY", "WEEK", "MONTH"}
FILE_FORMAT_POLICY_VERSIONS = {item.value for item in FileFormatPolicyVersion}
TASK_FILE_FEATURE_FIELDS = {
    "workspace_enabled",
    "file_mcp_enabled",
    "runtime_file_edit_enabled",
    "default_file_delivery_enabled",
}
DEFAULT_TASK_FILE_FEATURES = {
    "workspace_enabled": False,
    "file_mcp_enabled": False,
    "runtime_file_edit_enabled": False,
    "default_file_delivery_enabled": False,
}
FILE_MCP_READ_TOOLS = frozenset(
    {
        "task_workspace_get",
        "task_workspace_list_files",
        "file_get_metadata",
        "file_prepare_materialization",
    }
)
FILE_MCP_EDIT_TOOLS = frozenset({"file_create_commit_intent"})
FILE_MCP_DELIVERY_TOOLS = frozenset({"file_deliver_version"})
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
            "仅支持业务应用的 local 环境",
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


def validate_task_workspace_retention_period(value: object) -> str:
    normalized = str(value or "WEEK").strip().upper()
    if normalized not in TASK_WORKSPACE_RETENTION_PERIODS:
        raise validation_error(
            "task_workspace_retention_period",
            "只允许 DAY、WEEK 或 MONTH",
        )
    return normalized


def validate_file_format_policy_version(value: object) -> str:
    try:
        return normalize_file_format_policy_version(value).value
    except NonRetryableExecutionError as exc:
        raise validation_error(
            "file_format_policy_version",
            "只允许 text-v1 或 text-v2",
        ) from exc


def validate_document_processing_profile_code(value: object) -> str:
    return normalize_document_processing_profile_code(value).value


def validate_task_file_features(value: object) -> dict[str, bool]:
    if value is None:
        return dict(DEFAULT_TASK_FILE_FEATURES)
    if not isinstance(value, dict):
        raise validation_error("task_file_features", "必须是功能开关对象")
    _reject_unknown(value, TASK_FILE_FEATURE_FIELDS, "task_file_features")
    normalized = {key: bool(value.get(key, False)) for key in sorted(TASK_FILE_FEATURE_FIELDS)}
    if any(key in value and not isinstance(value[key], bool) for key in TASK_FILE_FEATURE_FIELDS):
        raise validation_error("task_file_features", "功能开关必须是布尔值")
    if normalized["file_mcp_enabled"] and not normalized["workspace_enabled"]:
        raise validation_error(
            "task_file_features.file_mcp_enabled", "启用 File MCP 前必须启用工作区"
        )
    if normalized["runtime_file_edit_enabled"] and not normalized["file_mcp_enabled"]:
        raise validation_error(
            "task_file_features.runtime_file_edit_enabled",
            "启用 Runtime 文件编辑前必须启用 File MCP",
        )
    if normalized["default_file_delivery_enabled"] and not normalized["runtime_file_edit_enabled"]:
        raise validation_error(
            "task_file_features.default_file_delivery_enabled",
            "启用默认文件交付前必须启用 Runtime 文件编辑",
        )
    return normalized


def required_file_mcp_tools(task_file_features: dict[str, bool]) -> frozenset[str]:
    required: set[str] = set()
    if task_file_features.get("file_mcp_enabled"):
        required.update(FILE_MCP_READ_TOOLS)
    if task_file_features.get("runtime_file_edit_enabled"):
        required.update(FILE_MCP_EDIT_TOOLS)
    if task_file_features.get("default_file_delivery_enabled"):
        required.update(FILE_MCP_DELIVERY_TOOLS)
    return frozenset(required)


def validate_task_file_attachment_dependency(
    *,
    session_policy: dict[str, Any],
    task_file_features: dict[str, bool],
) -> None:
    if task_file_features["workspace_enabled"] and not session_policy["attachments_enabled"]:
        raise validation_error(
            "session_policy.attachments_enabled",
            "启用任务工作区前必须允许消息附件",
        )
    if (
        task_file_features["workspace_enabled"]
        and not session_policy["continuous_conversation_enabled"]
    ):
        raise validation_error(
            "session_policy.continuous_conversation_enabled",
            "启用任务工作区前必须启用连续会话",
        )


def publication_task_file_features(snapshot: dict[str, Any]) -> tuple[dict[str, bool], str]:
    if "task_file_features" not in snapshot:
        return dict(DEFAULT_TASK_FILE_FEATURES), "legacy_default"
    return validate_task_file_features(snapshot.get("task_file_features")), "publication_snapshot"


def publication_workspace_retention(snapshot: dict[str, Any]) -> tuple[str, str]:
    """Resolve legacy policy without mutating the immutable snapshot or its hash."""
    if "task_workspace_retention_period" not in snapshot:
        return "WEEK", "legacy_default"
    return (
        validate_task_workspace_retention_period(snapshot.get("task_workspace_retention_period")),
        "publication_snapshot",
    )


def publication_file_format_policy(snapshot: dict[str, Any]) -> tuple[str, str]:
    """Resolve immutable legacy publications without rewriting their hash."""
    if "file_format_policy_version" not in snapshot:
        return FileFormatPolicyVersion.TEXT_V1.value, "legacy_default"
    return (
        validate_file_format_policy_version(snapshot.get("file_format_policy_version")),
        "publication_snapshot",
    )


def publication_document_processing_profile(
    snapshot: dict[str, Any],
) -> tuple[dict[str, str], str]:
    value = snapshot.get("document_processing_profile")
    if value is None:
        return document_processing_profile_snapshot(None), "legacy_default"
    if not isinstance(value, dict):
        raise validation_error(
            "document_processing_profile",
            "发布快照中的文档处理Profile无效",
        )
    expected = document_processing_profile_snapshot(value.get("code"))
    if value != expected:
        raise validation_error(
            "document_processing_profile",
            "发布快照中的文档处理Profile与代码注册版本不一致",
        )
    return expected, "publication_snapshot"


def verify_publication_snapshot(
    snapshot: dict[str, Any],
    *,
    schema_version: int,
    expected_hash: str,
) -> bool:
    if schema_version not in {1, 2, 3, 4, 5} or not verify_snapshot(
        snapshot, expected_hash
    ):
        return False
    if schema_version == 1:
        return True
    if schema_version == 2:
        return (
            snapshot.get("schema_version") == 2
            and snapshot.get("task_workspace_retention_period") in TASK_WORKSPACE_RETENTION_PERIODS
        )
    try:
        features_valid = validate_task_file_features(
            snapshot.get("task_file_features")
        ) == snapshot.get("task_file_features")
    except NonRetryableExecutionError:
        return False
    if schema_version == 3:
        return (
            snapshot.get("schema_version") == 3
            and snapshot.get("task_workspace_retention_period") in TASK_WORKSPACE_RETENTION_PERIODS
            and features_valid
        )
    v4_valid = (
        snapshot.get("task_workspace_retention_period") in TASK_WORKSPACE_RETENTION_PERIODS
        and snapshot.get("file_format_policy_version") in FILE_FORMAT_POLICY_VERSIONS
        and features_valid
    )
    if schema_version == 4:
        return snapshot.get("schema_version") == 4 and v4_valid
    try:
        profile, profile_source = publication_document_processing_profile(snapshot)
    except NonRetryableExecutionError:
        return False
    return (
        snapshot.get("schema_version") == 5
        and v4_valid
        and profile_source == "publication_snapshot"
        and profile["code"]
        in {
            DocumentProcessingProfileCode.NONE.value,
            DocumentProcessingProfileCode.DOCLING_TEXT_V1.value,
            DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V1.value,
            DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V2.value,
        }
    )


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
