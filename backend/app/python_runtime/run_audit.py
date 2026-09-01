from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.agent.domain.runtime import AgentExecutionContext
from app.python_runtime.sdk_event_normalizer import (
    content_blocks,
    sdk_block_type,
    sdk_message_type,
    sdk_value,
)
from app.shared.agent_run_audit_codec import (
    AUDIT_CHUNK_BYTES as AUDIT_CHUNK_BYTES,
    MAX_AUDIT_CHUNKS as MAX_AUDIT_CHUNKS,
    decode_audit_chunks as decode_audit_chunks,
    encode_audit_chunks as encode_audit_chunks,
)


class RunAuditRecorder:
    """Capture the complete model-visible invocation without application redaction."""

    def __init__(
        self,
        context: AgentExecutionContext,
        *,
        system_prompt: str,
        raw_api_dir: Path,
        permission_snapshot: dict[str, Any],
    ) -> None:
        self.raw_api_dir = raw_api_dir
        self._seen_model_messages: set[str] = set()
        self._tool_call_index: dict[str, int] = {}
        self.audit: dict[str, Any] = {
            "started_at": _now_iso(),
            "finished_at": None,
            "status": "RUNNING",
            "context_manifest": _context_manifest(context),
            "system_prompt": system_prompt,
            "user_prompt": context.user_question,
            "tool_definitions": _tool_definitions(context),
            "permission_snapshot": _jsonable(permission_snapshot),
            "init_snapshot": {},
            "sdk_messages": [],
            "api_requests": [],
            "api_responses": [],
            "tool_executions": [],
            "model_requests": [],
            "usage": {},
            "summary": {},
            "raw_api_capture_status": "unavailable",
            "provider_thinking_disclosure": (
                "完整保存 Runtime/Provider 实际暴露的模型响应；上游隐藏或删减的 "
                "extended thinking 无法恢复，也不会被推断或伪造。"
            ),
            "error": {},
        }

    def observe_message(self, message: Any) -> None:
        data = _jsonable(message)
        message_type = sdk_message_type(message)
        self.audit["sdk_messages"].append(
            {
                "message_type": message_type,
                "python_type": type(message).__name__,
                "data": data,
            }
        )
        subtype = str(sdk_value(message, "subtype") or "")
        if message_type == "system" and subtype == "init":
            self.audit["init_snapshot"] = data

        self._observe_model_usage(message, message_type)
        self._observe_tool_blocks(message)

    def finalize(
        self,
        *,
        status: str,
        final_answer: str = "",
        error: BaseException | None = None,
    ) -> dict[str, Any]:
        _collect_raw_api_bodies(self.audit, self.raw_api_dir)
        self.audit["finished_at"] = _now_iso()
        self.audit["status"] = status
        if final_answer:
            self.audit["usage"]["final_answer_character_count"] = len(final_answer)
        if error is not None:
            safe_message = getattr(error, "safe_message", "")
            self.audit["error"] = {
                "exception_class": error.__class__.__name__,
                "safe_message": (str(safe_message) if isinstance(safe_message, str) else ""),
            }
        _finalize_summary(self.audit)
        return self.audit

    def _observe_model_usage(self, message: Any, message_type: str) -> None:
        nested = sdk_value(message, "message") or message
        usage = _jsonable(sdk_value(nested, "usage") or sdk_value(message, "usage"))
        if message_type == "result":
            self.audit["usage"]["result"] = usage if isinstance(usage, dict) else {}
            self.audit["usage"]["model_usage"] = _jsonable(
                sdk_value(message, "model_usage") or sdk_value(message, "modelUsage")
            )
            for key in (
                "total_cost_usd",
                "num_turns",
                "duration_ms",
                "duration_api_ms",
                "session_id",
                "is_error",
                "subtype",
            ):
                value = sdk_value(message, key)
                if value is not None:
                    self.audit["usage"][key] = _jsonable(value)
            return
        if message_type != "assistant" or not isinstance(usage, dict) or not usage:
            return
        if sdk_value(message, "parent_tool_use_id"):
            return
        message_id = str(
            sdk_value(nested, "id")
            or sdk_value(nested, "message_id")
            or sdk_value(message, "uuid")
            or f"assistant:{len(self.audit['model_requests']) + 1}"
        )
        if message_id in self._seen_model_messages:
            return
        self._seen_model_messages.add(message_id)
        self.audit["model_requests"].append(
            {
                "message_id": message_id,
                "model": _jsonable(sdk_value(nested, "model")),
                "usage": usage,
                "request_context_tokens": _request_context_tokens(usage),
            }
        )

    def _observe_tool_blocks(self, message: Any) -> None:
        for block in content_blocks(message):
            block_type = sdk_block_type(block)
            if block_type not in {
                "tool_use",
                "tool_result",
                "server_tool_use",
                "server_tool_result",
            }:
                continue
            tool_call_id = str(sdk_value(block, "id") or sdk_value(block, "tool_use_id") or "")
            if block_type in {"tool_use", "server_tool_use"}:
                item = {
                    "tool_call_id": tool_call_id,
                    "tool_name": str(
                        sdk_value(block, "name") or sdk_value(block, "tool_name") or "unknown_tool"
                    ),
                    "input": _jsonable(sdk_value(block, "input") or {}),
                    "output": None,
                    "status": "STARTED",
                    "block_type": block_type,
                }
                self.audit["tool_executions"].append(item)
                if tool_call_id:
                    self._tool_call_index[tool_call_id] = len(self.audit["tool_executions"]) - 1
                continue
            output = _jsonable(
                sdk_value(block, "content")
                if sdk_value(block, "content") is not None
                else sdk_value(block, "result")
            )
            index = self._tool_call_index.get(tool_call_id)
            if index is not None:
                item = self.audit["tool_executions"][index]
                item["output"] = output
                item["status"] = "FAILED" if sdk_value(block, "is_error") is True else "SUCCEEDED"
                item["result_block_type"] = block_type
            else:
                self.audit["tool_executions"].append(
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": "unknown_tool",
                        "input": None,
                        "output": output,
                        "status": (
                            "FAILED" if sdk_value(block, "is_error") is True else "SUCCEEDED"
                        ),
                        "block_type": block_type,
                    }
                )


def _context_manifest(context: AgentExecutionContext) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []

    def add(source_type: str, name: str, content: Any) -> None:
        normalized = _jsonable(content)
        rendered = content if isinstance(content, str) else _canonical_json(normalized)
        sources.append(
            {
                "source_type": source_type,
                "name": name,
                "content": normalized,
                "character_count": len(rendered),
                "estimated_tokens": (len(rendered) + 3) // 4,
                "upstream_truncated": (
                    bool(content.get("truncated")) if isinstance(content, dict) else False
                ),
            }
        )

    add("system_role", "system_role", context.system_role)
    if context.business_instructions:
        add("business_instructions", "business_instructions", context.business_instructions)
    add("safety_rules", "safety_rules", context.safety_rules)
    add("tool_restrictions", "tool_restrictions", context.tool_restrictions)
    add("effective_tools", "effective_tools", list(context.effective_tool_names))
    for name, body in sorted(context.skills.items()):
        add("skill", name, body)
    for name, content in context.retrieved_context.items():
        add("retrieved_context", str(name), content)
    add("conversation_summary", "conversation_summary", context.conversation_summary)
    add("user_prompt", "user_question", context.user_question)
    return {
        "sources": sources,
        "source_count": len(sources),
        "total_character_count": sum(item["character_count"] for item in sources),
        "estimated_tokens": sum(item["estimated_tokens"] for item in sources),
        "estimate_method": "ceil(Unicode character count / 4)",
        "publication_id": context.publication_id,
        "application_publication_id": context.application_publication_id,
        "config_hash": context.config_hash,
        "model": context.model,
        "runtime_protocol_version": context.runtime_protocol_version,
        "limits": {
            "max_turns": context.max_turns,
            "timeout_seconds": context.timeout_seconds,
            "max_tool_calls": context.max_tool_calls,
        },
    }


def _tool_definitions(context: AgentExecutionContext) -> list[dict[str, Any]]:
    bindings = [
        {
            "name": binding.tool_name,
            "server_code": binding.server_code,
            "required_scope": binding.required_scope,
            "tool_schema_hash": binding.tool_schema_hash,
            "resource_code": binding.resource_code,
            "resource_deployment_id": binding.resource_deployment_id,
            "resource_revision_id": binding.resource_revision_id,
        }
        for binding in context.mcp_bindings
    ]
    if bindings:
        return bindings
    return [{"name": name, "source": "runtime_effective"} for name in context.effective_tool_names]


def _collect_raw_api_bodies(audit: dict[str, Any], raw_api_dir: Path) -> None:
    request_files = _raw_files(raw_api_dir, "*.request.json")
    response_files = _raw_files(raw_api_dir, "*.response.json")
    audit["api_requests"] = [_read_raw_file(item) for item in request_files]
    audit["api_responses"] = [_read_raw_file(item) for item in response_files]
    if request_files or response_files:
        audit["raw_api_capture_status"] = "captured"
    metrics = []
    loaded_definitions: list[dict[str, Any]] = []
    for index, item in enumerate(audit["api_requests"], start=1):
        body = item.get("body")
        loaded_tools = body.get("tools") if isinstance(body, dict) else None
        if isinstance(loaded_tools, list):
            loaded_definitions.extend(
                {
                    "source": "raw_api_request",
                    "api_request_index": index,
                    "definition": _jsonable(definition),
                }
                for definition in loaded_tools
            )
        metrics.append(
            {
                "api_request_index": index,
                "file_name": item["file_name"],
                "loaded_tool_count": len(loaded_tools) if isinstance(loaded_tools, list) else 0,
                "request_character_count": len(_canonical_json(body)),
            }
        )
    audit["tool_definitions"] = [
        *list(audit.get("tool_definitions") or []),
        *loaded_definitions,
    ]
    audit["usage"]["raw_api_request_metrics"] = metrics


def _raw_files(directory: Path, pattern: str) -> list[Path]:
    try:
        return sorted(
            (item for item in directory.rglob(pattern) if item.is_file()),
            key=lambda item: (item.stat().st_mtime_ns, str(item)),
        )
    except OSError:
        return []


def _read_raw_file(path: Path) -> dict[str, Any]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {
            "file_name": path.name,
            "read_error": {
                "exception_class": exc.__class__.__name__,
                "message": str(exc),
            },
        }
    try:
        body: Any = json.loads(raw_text)
    except json.JSONDecodeError:
        body = {"raw_text": raw_text}
    return {"file_name": path.name, "body": body}


def _finalize_summary(audit: dict[str, Any]) -> None:
    model_requests = audit.get("model_requests") or []
    result_usage = audit.get("usage", {}).get("result") or {}
    request_usages = [item.get("usage") or {} for item in model_requests if isinstance(item, dict)]
    effective = result_usage if isinstance(result_usage, dict) and result_usage else {}

    def total(key: str) -> int:
        if effective:
            return _usage_int(effective, key)
        return sum(_usage_int(item, key) for item in request_usages)

    init = audit.get("init_snapshot") or {}
    init_tools = sdk_value(init, "tools")
    if not isinstance(init_tools, list):
        init_tools = sdk_value(sdk_value(init, "data") or {}, "tools")
    tool_names = {
        str(item.get("tool_name"))
        for item in audit.get("tool_executions") or []
        if isinstance(item, dict) and item.get("tool_name")
    }
    metrics = audit.get("usage", {}).get("raw_api_request_metrics") or []
    permission_snapshot = audit.get("permission_snapshot") or {}
    auto_approved_tools = (
        permission_snapshot.get("allowed_tools") if isinstance(permission_snapshot, dict) else []
    )
    frozen_tool_count = sum(
        1
        for item in audit.get("tool_definitions") or []
        if not isinstance(item, dict) or item.get("source") != "raw_api_request"
    )
    audit["summary"] = {
        "model_request_count": len(audit.get("api_requests") or []) or len(model_requests),
        "max_request_context_tokens": max(
            [int(item.get("request_context_tokens") or 0) for item in model_requests] or [0]
        ),
        "cumulative_input_tokens": total("input_tokens"),
        "cumulative_output_tokens": total("output_tokens"),
        "cache_creation_input_tokens": total("cache_creation_input_tokens"),
        "cache_read_input_tokens": total("cache_read_input_tokens"),
        "total_cost_usd": float(audit.get("usage", {}).get("total_cost_usd") or 0),
        "registered_tool_count": (
            len(init_tools) if isinstance(init_tools, list) else frozen_tool_count
        ),
        "max_loaded_tool_count": max(
            [int(item.get("loaded_tool_count") or 0) for item in metrics] or [0]
        ),
        "auto_approved_tool_count": (
            len(auto_approved_tools) if isinstance(auto_approved_tools, list) else 0
        ),
        "tool_call_count": len(audit.get("tool_executions") or []),
        "distinct_tool_count": len(tool_names),
    }


def _request_context_tokens(usage: dict[str, Any]) -> int:
    return sum(
        _usage_int(usage, key)
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )


def _usage_int(usage: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(usage.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, Path)):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return _jsonable(attributes)
    return str(value)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
