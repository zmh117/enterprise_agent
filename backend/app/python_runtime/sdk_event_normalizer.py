from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from typing import Any

from app.python_runtime.error_mapper import redact_sensitive_text
from app.shared.config import ExecutionSettings


class SdkEventNormalizer:
    """Projects only bounded SDK metadata; never message content or raw payloads."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.accounting: dict[str, Any] = unavailable_accounting()
        self._request_started_at: float | None = None
        self._request_started_wall: str | None = None
        self._observed_model_call_ids: set[str] = set()
        self._next_model_call_ordinal = 1

    def consume(self, message: Any) -> None:
        message_type = sdk_message_type(message)
        subtype = str(sdk_value(message, "subtype") or "")
        data = sdk_value(message, "data")
        source = data if isinstance(data, dict) else message
        if message_type == "system" and subtype == "status":
            if sdk_value(source, "status") == "requesting" and self._request_started_at is None:
                self._request_started_at = time.monotonic()
                self._request_started_wall = utc_now()
            return
        if message_type == "system" and subtype == "init":
            servers = []
            raw_servers = sdk_value(source, "mcp_servers") or []
            if isinstance(raw_servers, list):
                for item in raw_servers[:32]:
                    name = sdk_value(item, "name")
                    server_code = safe_server_code(name)
                    if server_code:
                        servers.append(
                            {
                                "server_code": server_code,
                                "status": safe_mcp_status(sdk_value(item, "status")),
                            }
                        )
            self.events.append(
                {
                    "event_type": "runtime_initialized",
                    "payload": {
                        "model_id": bounded_identifier_text(
                            sdk_value(source, "model") or "unknown-model", 200
                        ),
                        "mcp_servers": servers,
                    },
                }
            )
            return
        if message_type == "system" and subtype == "api_retry":
            self.events.append(
                {
                    "event_type": "api_retry",
                    "payload": {
                        "attempt": bounded_int(sdk_value(source, "attempt"), 1, 32, 1),
                        "max_retries": bounded_int(sdk_value(source, "max_retries"), 1, 32, 1),
                        "retry_delay_ms": bounded_int(
                            sdk_value(source, "retry_delay_ms"), 0, 1_800_000, 0
                        ),
                        "error_status": http_status_or_none(sdk_value(source, "error_status")),
                        "error_code": bounded_identifier_text(
                            sdk_value(source, "error") or "unknown", 128
                        ),
                    },
                }
            )
            return
        if message_type == "assistant":
            body = sdk_value(message, "message") or message
            completed_monotonic = time.monotonic()
            completed_wall = utc_now()
            started = self._request_started_at
            stable_message_id = identifier_or_none(
                sdk_value(body, "id") or sdk_value(body, "message_id") or sdk_value(message, "uuid")
            )
            if stable_message_id is not None:
                if stable_message_id in self._observed_model_call_ids:
                    self._request_started_at = None
                    self._request_started_wall = None
                    return
                self._observed_model_call_ids.add(stable_message_id)
                message_id = stable_message_id
            else:
                message_id = f"model-call-{self._next_model_call_ordinal}"
                self._next_model_call_ordinal += 1
            error_code = identifier_or_none(sdk_value(message, "error"))
            self.events.append(
                {
                    "event_type": "model_call",
                    "payload": {
                        "model_call_id": message_id,
                        "provider_request_id": bounded_optional_text(
                            sdk_value(message, "request_id"), 200
                        ),
                        "provider_message_id": bounded_optional_text(
                            sdk_value(body, "id") or sdk_value(body, "message_id"), 200
                        ),
                        "model_id": bounded_identifier_text(
                            sdk_value(body, "model") or "unknown-model", 200
                        ),
                        "status": "FAILED" if error_code else "SUCCEEDED",
                        "started_at": self._request_started_wall if started is not None else None,
                        "completed_at": completed_wall,
                        "duration_ms": (
                            max(0, int((completed_monotonic - started) * 1000))
                            if started is not None
                            else None
                        ),
                        "duration_source": (
                            "SDK_OBSERVED" if started is not None else "UNAVAILABLE"
                        ),
                        "usage": nullable_usage(sdk_value(body, "usage")),
                        "stop_reason": bounded_optional_text(sdk_value(body, "stop_reason"), 128),
                        "error_code": error_code,
                        "error_summary": ("模型响应失败" if error_code else None),
                    },
                }
            )
            self._request_started_at = None
            self._request_started_wall = None
            return
        if message_type == "result":
            self.accounting = result_accounting(message)


def sdk_message_type(message: Any) -> str:
    explicit = sdk_value(message, "type")
    if isinstance(explicit, str):
        return explicit
    name = type(message).__name__.lower()
    if name.endswith("message"):
        name = name.removesuffix("message")
    aliases: dict[str, str] = {
        "system": "system",
        "assistant": "assistant",
        "result": "result",
    }
    return aliases.get(name, name)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def bounded_optional_text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return redact_sensitive_text(value)[:maximum]


def bounded_identifier_text(value: Any, maximum: int) -> str:
    text = redact_sensitive_text(str(value or "unknown"))[:maximum]
    return text or "unknown"


def bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(number, maximum))


def non_negative_or_none(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number != number or number in {float("inf"), float("-inf")}:
        return None
    return int(number) if number.is_integer() else number


def token_or_none(source: dict[str, Any], *names: str) -> int | None:
    for name in names:
        if name in source:
            value = non_negative_or_none(source[name])
            return int(value) if value is not None else None
    return None


def nullable_usage(value: Any) -> dict[str, int | None]:
    source = value if isinstance(value, dict) else {}
    return {
        "input_tokens": token_or_none(source, "input_tokens", "inputTokens"),
        "output_tokens": token_or_none(source, "output_tokens", "outputTokens"),
        "cache_read_input_tokens": token_or_none(
            source, "cache_read_input_tokens", "cacheReadInputTokens"
        ),
        "cache_creation_input_tokens": token_or_none(
            source, "cache_creation_input_tokens", "cacheCreationInputTokens"
        ),
    }


def unavailable_accounting() -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "duration_ms": None,
        "duration_api_ms": None,
        "num_turns": None,
        "usage": nullable_usage(None),
        "model_usage": [],
        "estimated_cost_usd": None,
        "permission_denials_count": 0,
    }


def result_accounting(message: Any) -> dict[str, Any]:
    raw_models = sdk_value(message, "modelUsage") or sdk_value(message, "model_usage") or {}
    models: list[dict[str, Any]] = []
    if isinstance(raw_models, dict):
        for model_id, item in list(raw_models.items())[:64]:
            if not isinstance(item, dict):
                continue
            models.append(
                {
                    "model_id": bounded_identifier_text(model_id, 200),
                    "canonical_model": bounded_optional_text(
                        item.get("canonicalModel") or item.get("canonical_model"), 200
                    ),
                    "provider": bounded_optional_text(item.get("provider"), 64),
                    "usage": nullable_usage(item),
                    "estimated_cost_usd": non_negative_or_none(
                        item.get("costUSD", item.get("cost_usd"))
                    ),
                }
            )
    raw_usage = sdk_value(message, "usage")
    return {
        "status": "COMPLETE"
        if models
        else "PARTIAL"
        if isinstance(raw_usage, dict)
        else "UNAVAILABLE",
        "duration_ms": non_negative_or_none(sdk_value(message, "duration_ms")),
        "duration_api_ms": non_negative_or_none(sdk_value(message, "duration_api_ms")),
        "num_turns": non_negative_or_none(sdk_value(message, "num_turns")),
        "usage": nullable_usage(raw_usage),
        "model_usage": models,
        "estimated_cost_usd": non_negative_or_none(sdk_value(message, "total_cost_usd")),
        "permission_denials_count": min(len(sdk_value(message, "permission_denials") or []), 1024),
    }


def safe_server_code(value: Any) -> str | None:
    if value in {"tools", "tool_mcp"}:
        return "tool-mcp"
    if value in {"ones", "ones_mcp"}:
        return "ones-mcp"
    return identifier_or_none(value)


def safe_mcp_status(value: Any) -> str:
    return {
        "connected": "CONNECTED",
        "failed": "FAILED",
        "disconnected": "DISCONNECTED",
    }.get(str(value or "").lower(), "UNKNOWN")


def http_status_or_none(value: Any) -> int | None:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    return status if 100 <= status <= 599 else None


def extract_text_blocks(message: Any) -> list[str]:
    texts = []
    for block in content_blocks(message):
        block_type = sdk_block_type(block)
        text = sdk_value(block, "text")
        if block_type == "text" and isinstance(text, str):
            texts.append(text)
    return texts


def extract_result_text(message: Any) -> str:
    result = sdk_value(message, "result")
    if isinstance(result, str):
        return result
    if sdk_value(message, "type") == "result":
        content = sdk_value(message, "content")
        return content if isinstance(content, str) else ""
    return ""


def extract_tool_events(
    message: Any,
    limits: ExecutionSettings,
    calls: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    call_index = calls if calls is not None else {}
    events = []
    metadata = platform_tool_metadata(message)
    for block in content_blocks(message):
        block_type = sdk_block_type(block)
        if block_type not in {"tool_use", "tool_result"}:
            continue
        tool_call_id = str(sdk_value(block, "id") or sdk_value(block, "tool_use_id") or "")
        if not tool_call_id:
            continue
        if block_type == "tool_use":
            tool_name = str(
                sdk_value(block, "name") or sdk_value(block, "tool_name") or "unknown_tool"
            )
            request_payload = safe_file_tool_request(tool_name, sdk_value(block, "input") or {})
            call_index[tool_call_id] = {
                "tool_name": tool_name,
                "request_payload": request_payload,
            }
            status = "STARTED"
        else:
            started = call_index.pop(tool_call_id, {})
            tool_name = str(started.get("tool_name") or "unknown_tool")
            request_payload = started.get("request_payload") or {}
            status = "FAILED" if sdk_value(block, "is_error") is True else "SUCCEEDED"
        response = (
            {"file_tool_result": "omitted"}
            if tool_name in {"Read", "Grep", "Write", "Edit"}
            else sdk_value(block, "content") or sdk_value(block, "result") or {}
        )
        events.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "request_payload": bounded_payload(request_payload, limits.max_tool_response_chars),
                "response_summary": bounded_payload(response, limits.max_tool_response_chars),
                "status": status,
                "duration_ms": 0,
                "risk_level": risk_level(tool_name),
                "mcp_call_id": metadata["mcp_call_id"],
                "persisted_tool_call_id": metadata["persisted_tool_call_id"],
            }
        )
    return events


def safe_file_tool_request(tool_name: str, value: Any) -> Any:
    if tool_name not in {"Read", "Grep", "Write", "Edit"} or not isinstance(value, dict):
        return value
    path = value.get("file_path", value.get("path"))
    result: dict[str, Any] = {}
    if isinstance(path, str):
        result["relative_path"] = path[:240]
    if tool_name == "Write" and isinstance(value.get("content"), str):
        result["content_bytes"] = len(value["content"].encode("utf-8"))
    if tool_name == "Edit":
        if isinstance(value.get("old_string"), str):
            result["old_string_bytes"] = len(value["old_string"].encode("utf-8"))
        if isinstance(value.get("new_string"), str):
            result["new_string_bytes"] = len(value["new_string"].encode("utf-8"))
        if isinstance(value.get("replace_all"), bool):
            result["replace_all"] = value["replace_all"]
    if tool_name == "Read":
        for field in ("offset", "limit"):
            if isinstance(value.get(field), int) and not isinstance(value.get(field), bool):
                result[field] = value[field]
    if tool_name == "Grep" and isinstance(value.get("pattern"), str):
        result["pattern_chars"] = len(value["pattern"])
    return result


def platform_tool_metadata(message: Any) -> dict[str, str | None]:
    result = sdk_value(message, "tool_use_result")
    if not isinstance(result, dict):
        return {"mcp_call_id": None, "persisted_tool_call_id": None}
    metadata = result.get("_meta")
    if not isinstance(metadata, dict):
        return {"mcp_call_id": None, "persisted_tool_call_id": None}
    return {
        "mcp_call_id": identifier_or_none(metadata.get("enterprise-agent/mcp-call-id")),
        "persisted_tool_call_id": identifier_or_none(
            metadata.get("enterprise-agent/agent-tool-call-id")
        ),
    }


def identifier_or_none(value: Any) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        return None
    return value


def content_blocks(message: Any) -> list[Any]:
    content = sdk_value(message, "content")
    if not isinstance(content, list):
        nested = sdk_value(message, "message")
        content = sdk_value(nested, "content")
    if isinstance(content, list):
        return content
    return []


def sdk_block_type(block: Any) -> str:
    explicit = sdk_value(block, "type")
    if isinstance(explicit, str):
        return explicit
    return {
        "TextBlock": "text",
        "ThinkingBlock": "thinking",
        "ToolUseBlock": "tool_use",
        "ToolResultBlock": "tool_result",
        "ServerToolUseBlock": "server_tool_use",
        "ServerToolResultBlock": "server_tool_result",
    }.get(type(block).__name__, "")


def sdk_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def bounded_payload(payload: Any, max_chars: int) -> dict[str, Any]:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    truncated = len(serialized) > max_chars
    if truncated:
        serialized = serialized[:max_chars]
    return {"payload": serialized, "truncated": truncated}


def risk_level(tool_name: str) -> str:
    if tool_name.startswith("get_") or tool_name.startswith("diagnose_loki"):
        return "low"
    return "low" if tool_name == "query_loki" else "medium"
