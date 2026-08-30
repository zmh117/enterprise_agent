from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.mcp_server_policy import McpServerPolicy, mcp_sdk_server_alias


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
RUNTIME_DERIVED_TOOL_ALIASES = {
    "mcp__file_service__select_sandbox_output": "select_sandbox_output",
    "mcp__file_service__scan_log_evidence": "scan_log_evidence",
}
FORBIDDEN_TOOL_INPUT_FIELDS = frozenset(
    {
        "authorization",
        "headers",
        "user_id",
        "app_user_id",
        "actor_id",
        "sub",
        "credential",
        "credential_id",
        "resource_deployment_id",
        "resource_revision_id",
    }
)


def contains_forbidden_tool_input(
    value: object,
    depth: int = 0,
    *,
    declared_root_fields: frozenset[str] = frozenset(),
) -> bool:
    if depth >= 8:
        return False
    if isinstance(value, list):
        return any(contains_forbidden_tool_input(item, depth + 1) for item in value)
    if not isinstance(value, dict):
        return False
    for key, child in value.items():
        field = str(key)
        # A trusted, frozen Tool schema owns the semantics of its declared
        # top-level fields. Once declared, the MCP server performs the exact
        # nested validation and Principal/target injection for that field.
        if depth == 0 and field in declared_root_fields:
            continue
        if field.lower() in FORBIDDEN_TOOL_INPUT_FIELDS or contains_forbidden_tool_input(
            child, depth + 1
        ):
            return True
    return False


def normalize_tool_events(
    events: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    server_policies: Mapping[str, McpServerPolicy] | None = None,
) -> tuple[dict[str, Any], ...]:
    published = {
        (
            f"mcp__{mcp_sdk_server_alias(str(server['server_code']), policies=server_policies)}"
            f"__{tool['tool_name']}"
        ): (
            str(server["server_code"]),
            str(tool["tool_name"]),
        )
        for server in request.get("mcp_servers") or []
        for tool in server.get("tools") or []
    }
    normalized: list[dict[str, Any]] = []
    for event in events[:128]:
        full_tool_name = str(event.get("tool_name") or "unknown_tool")
        published_tool = published.get(full_tool_name)
        derived_tool = _authorized_runtime_derived_tool(full_tool_name, request)
        if published_tool:
            tool_origin = "mcp"
            server_code: str | None = published_tool[0]
            tool_name = published_tool[1]
        elif full_tool_name in SDK_BUILTIN_TOOLS:
            tool_origin = "sdk_builtin"
            server_code = None
            tool_name = full_tool_name
        elif derived_tool is not None:
            tool_origin = "sdk_custom"
            server_code = None
            tool_name = derived_tool
        elif full_tool_name in PLATFORM_SDK_TOOLS:
            tool_origin = "sdk_custom"
            server_code = None
            tool_name = full_tool_name
        else:
            tool_origin = "unknown"
            server_code = None
            tool_name = full_tool_name
        protocol_version = str(request.get("protocol_version") or "")
        if protocol_version != "1.4":
            raise ValueError("only runtime protocol 1.4 is supported")
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


def _file_commit_flow_is_frozen(request: dict[str, Any]) -> bool:
    return any(
        str(server.get("server_code") or "") == "file-service"
        and any(
            str(tool.get("tool_name") or "") == "file_create_commit_intent"
            for tool in server.get("tools") or []
            if isinstance(tool, dict)
        )
        for server in request.get("mcp_servers") or []
        if isinstance(server, dict)
    )


def _file_materialization_is_frozen(request: dict[str, Any]) -> bool:
    return any(
        str(server.get("server_code") or "") == "file-service"
        and any(
            str(tool.get("tool_name") or "") == "file_prepare_materialization"
            for tool in server.get("tools") or []
            if isinstance(tool, dict)
        )
        for server in request.get("mcp_servers") or []
        if isinstance(server, dict)
    )


def _authorized_runtime_derived_tool(
    full_tool_name: str,
    request: dict[str, Any],
) -> str | None:
    derived = RUNTIME_DERIVED_TOOL_ALIASES.get(full_tool_name)
    if derived == "select_sandbox_output" and _file_commit_flow_is_frozen(request):
        return derived
    if derived == "scan_log_evidence" and _file_materialization_is_frozen(request):
        return derived
    return None
