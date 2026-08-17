from __future__ import annotations

from typing import Any


SDK_BUILTIN_TOOLS = frozenset(
    {
        "Agent",
        "Task",
        "Bash",
        "Read",
        "Glob",
        "Grep",
        "LS",
        "Write",
        "Edit",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "TodoRead",
        "TodoWrite",
        "AskUserQuestion",
        "Skill",
    }
)
PLATFORM_SDK_TOOLS: frozenset[str] = frozenset()
FORBIDDEN_TOOL_INPUT_FIELDS = frozenset(
    {
        "authorization",
        "headers",
        "user_id",
        "app_user_id",
        "actor_id",
        "subject",
        "sub",
        "credential",
        "credential_id",
        "resource_deployment_id",
        "resource_revision_id",
    }
)


def contains_forbidden_tool_input(value: object, depth: int = 0) -> bool:
    if depth >= 8:
        return False
    if isinstance(value, list):
        return any(contains_forbidden_tool_input(item, depth + 1) for item in value)
    if not isinstance(value, dict):
        return False
    return any(
        str(key).lower() in FORBIDDEN_TOOL_INPUT_FIELDS
        or contains_forbidden_tool_input(child, depth + 1)
        for key, child in value.items()
    )


def normalize_tool_events(
    events: list[dict[str, Any]],
    request: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    published = {
        (
            f"mcp__{'ones_mcp' if server['server_code'] == 'ones-mcp' else 'file_service' if server['server_code'] == 'file-service' else 'tool_mcp'}"
            f"__{tool['tool_name']}"
        ): (str(server["server_code"]), str(tool["tool_name"]))
        for server in request.get("mcp_servers") or []
        for tool in server.get("tools") or []
    }
    normalized: list[dict[str, Any]] = []
    for event in events[:128]:
        full_tool_name = str(event.get("tool_name") or "unknown_tool")
        published_tool = published.get(full_tool_name)
        if published_tool:
            tool_origin = "mcp"
            server_code: str | None = published_tool[0]
            tool_name = published_tool[1]
        elif full_tool_name in SDK_BUILTIN_TOOLS:
            tool_origin = "sdk_builtin"
            server_code = None
            tool_name = full_tool_name
        elif full_tool_name in PLATFORM_SDK_TOOLS:
            tool_origin = "sdk_custom"
            server_code = None
            tool_name = full_tool_name
        else:
            tool_origin = "unknown"
            server_code = None
            tool_name = full_tool_name
        protocol_version = str(request.get("protocol_version") or "1.0")
        if protocol_version == "1.0" and tool_origin != "mcp":
            continue
        tool_call_id = str(event.get("tool_call_id") or "")
        if not tool_call_id:
            continue
        raw_status = str(event.get("status") or "FAILED").upper()
        status = {
            "REJECTED": "DENIED",
            "STARTED": "STARTED",
            "SUCCEEDED": "SUCCEEDED",
            "FAILED": "FAILED",
        }.get(raw_status, "FAILED")
        item: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "server_code": server_code,
            "tool_name": tool_name,
            "status": status,
            "request_summary": {"available": bool(event.get("request_payload"))},
            "response_summary": {"available": bool(event.get("response_summary"))},
            "duration_ms": max(0, int(event.get("duration_ms") or 0)),
        }
        if protocol_version in {"1.1", "1.2", "1.3"}:
            item.update(
                {
                    "tool_origin": tool_origin,
                    "mcp_call_id": (
                        str(event["mcp_call_id"])
                        if tool_origin == "mcp" and event.get("mcp_call_id")
                        else None
                    ),
                    "persisted_tool_call_id": (
                        str(event["persisted_tool_call_id"])
                        if tool_origin == "mcp" and event.get("persisted_tool_call_id")
                        else None
                    ),
                }
            )
        if status in {"FAILED", "DENIED"}:
            item["failure"] = {
                "code": str(event.get("error_code") or "runtime_tool_failed"),
                "retry_class": "NEVER" if status == "DENIED" else "TRANSIENT",
                "safe_message": "工具调用未获授权" if status == "DENIED" else "工具调用失败",
            }
        normalized.append(item)
    return tuple(normalized)

