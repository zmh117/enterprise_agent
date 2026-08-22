from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from app.modules.agent.infrastructure.tool_manifest import TOOL_DEFINITIONS
from app.modules.file_workspace.contracts import FILE_TOOL_MANIFEST
from app.shared.mcp_server_policy import (
    FILE_MCP_SERVER_CODE,
    MCP_SERVER_POLICIES,
    ONES_MCP_SERVER_CODE,
    TOOL_MCP_SERVER_CODE,
    McpServerPolicy,
    require_mcp_server_policy,
    validate_mcp_server_policies,
)


_RESOURCE_KINDS = {
    "get_schema_directory": "database",
    "query_database": "database",
    "query_redis_get": "redis",
    "query_redis_scan": "redis",
    "query_loki": "loki",
    "diagnose_loki_labels": "loki",
    "diagnose_loki_label_values": "loki",
    "diagnose_loki_probe": "loki",
}


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    server_code: str
    identifier: str
    description: str
    input_schema: dict[str, Any]
    schema_hash: str
    resource_kind: str = ""
    read_only: bool = True


def mcp_tool_schema_hash(input_schema: dict[str, Any]) -> str:
    encoded = json.dumps(
        input_schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


MCP_TOOL_MANIFEST: dict[str, McpToolDefinition] = {
    identifier: McpToolDefinition(
        server_code=TOOL_MCP_SERVER_CODE,
        identifier=identifier,
        description=str(value["description"]),
        input_schema=dict(value["schema"]),
        schema_hash=mcp_tool_schema_hash(dict(value["schema"])),
        resource_kind=_RESOURCE_KINDS.get(identifier, ""),
    )
    for identifier, value in TOOL_DEFINITIONS.items()
}

_ONES_WORK_ITEM_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["keyword", "issue_type", "limit"],
    "properties": {
        "keyword": {"type": "string", "minLength": 1, "maxLength": 200},
        "issue_type": {"type": "string", "enum": ["demand", "task", "defect"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
}

MCP_TOOL_MANIFEST["ones_work_item_search"] = McpToolDefinition(
    server_code=ONES_MCP_SERVER_CODE,
    identifier="ones_work_item_search",
    description=(
        "按关键词和工作项类型查询当前平台用户有权访问的 ONES 工作项；"
        "只返回有界只读结果，不接受用户、Team、Token、URL 或 GraphQL 参数。"
    ),
    input_schema=_ONES_WORK_ITEM_SEARCH_SCHEMA,
    schema_hash=mcp_tool_schema_hash(_ONES_WORK_ITEM_SEARCH_SCHEMA),
    resource_kind="",
    read_only=True,
)

_ONES_PROJECT_ROLE_MEMBERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["project_uuid"],
    "properties": {
        "project_uuid": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": r"^[A-Za-z0-9_-]+$",
        }
    },
}

MCP_TOOL_MANIFEST["ones_list_project_role_members"] = McpToolDefinition(
    server_code=ONES_MCP_SERVER_CODE,
    identifier="ones_list_project_role_members",
    description=(
        "查询当前平台用户默认 Team 中指定 ONES 项目的角色及成员姓名；"
        "只接受 project_uuid，不接受 Team、用户、Token、URL、Header 或请求报文。"
    ),
    input_schema=_ONES_PROJECT_ROLE_MEMBERS_SCHEMA,
    schema_hash=mcp_tool_schema_hash(_ONES_PROJECT_ROLE_MEMBERS_SCHEMA),
    resource_kind="",
    read_only=True,
)

for _identifier, _file_tool in FILE_TOOL_MANIFEST.items():
    MCP_TOOL_MANIFEST[_identifier] = McpToolDefinition(
        server_code=FILE_MCP_SERVER_CODE,
        identifier=_identifier,
        description=_file_tool.description,
        input_schema=dict(_file_tool.input_schema),
        schema_hash=_file_tool.schema_hash,
        resource_kind="file",
        read_only=not _file_tool.mutating,
    )


def require_mcp_tool(identifier: str) -> McpToolDefinition:
    try:
        return MCP_TOOL_MANIFEST[identifier]
    except KeyError as exc:
        raise KeyError(f"Unknown MCP tool: {identifier}") from exc


def validate_mcp_tool_manifest(
    manifest: Mapping[str, McpToolDefinition] | None = None,
    *,
    policies: Mapping[str, McpServerPolicy] | None = None,
) -> None:
    selected_manifest = MCP_TOOL_MANIFEST if manifest is None else manifest
    selected_policies = MCP_SERVER_POLICIES if policies is None else policies
    validate_mcp_server_policies(selected_policies)
    for identifier, definition in selected_manifest.items():
        if identifier != definition.identifier:
            raise ValueError("MCP Tool Manifest identifier is inconsistent")
        require_mcp_server_policy(definition.server_code, policies=selected_policies)


validate_mcp_server_policies()
validate_mcp_tool_manifest()
