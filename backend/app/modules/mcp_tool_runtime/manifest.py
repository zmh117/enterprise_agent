from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.modules.agent.infrastructure.tool_manifest import TOOL_DEFINITIONS
from app.modules.file_workspace.contracts import FILE_TOOL_MANIFEST
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_CONFIRMATION_POLICY,
    DINGTALK_TOOL_CONTRACTS,
)
from app.shared.ones_tool_contracts import ONES_TOOL_CONTRACTS
from app.shared.mcp_server_policy import (
    DINGTALK_MCP_SERVER_CODE,
    FILE_MCP_SERVER_CODE,
    MCP_SERVER_POLICIES,
    ONES_MCP_SERVER_CODE,
    TOOL_MCP_SERVER_CODE,
    McpServerPolicy,
    require_mcp_server_policy,
    validate_mcp_server_policies,
)
from app.shared.tool_contract import tool_schema_hash


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
    effect: str = "read"
    confirmation_policy: str = "none"
    required_scope: str = ""
    operation_code: str = ""
    risk_level: str = "low"
    target_policy: str = ""
    destructive: bool = False
    idempotent: bool = False
    open_world: bool = False


def mcp_tool_schema_hash(input_schema: dict[str, Any]) -> str:
    return tool_schema_hash(input_schema)


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

for _ones_contract in ONES_TOOL_CONTRACTS.values():
    MCP_TOOL_MANIFEST[_ones_contract.identifier] = McpToolDefinition(
        server_code=ONES_MCP_SERVER_CODE,
        identifier=_ones_contract.identifier,
        description=_ones_contract.description,
        input_schema=_ones_contract.input_schema,
        schema_hash=mcp_tool_schema_hash(_ones_contract.input_schema),
        resource_kind="",
        read_only=True,
    )

for _dingtalk_contract in DINGTALK_TOOL_CONTRACTS.values():
    MCP_TOOL_MANIFEST[_dingtalk_contract.identifier] = McpToolDefinition(
        server_code=DINGTALK_MCP_SERVER_CODE,
        identifier=_dingtalk_contract.identifier,
        description=_dingtalk_contract.description,
        input_schema=_dingtalk_contract.input_schema,
        schema_hash=mcp_tool_schema_hash(_dingtalk_contract.input_schema),
        resource_kind="",
        read_only=_dingtalk_contract.read_only,
        effect=_dingtalk_contract.effect,
        confirmation_policy=_dingtalk_contract.confirmation_policy,
        required_scope=_dingtalk_contract.required_scope,
        operation_code=_dingtalk_contract.operation_code,
        risk_level=_dingtalk_contract.risk_level,
        target_policy=_dingtalk_contract.target_policy,
        destructive=_dingtalk_contract.destructive,
        idempotent=_dingtalk_contract.idempotent,
        open_world=_dingtalk_contract.open_world,
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
        effect="mutation" if _file_tool.mutating else "read",
        confirmation_policy="file_workspace_intent" if _file_tool.mutating else "none",
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
        if definition.effect not in {"read", "mutation"}:
            raise ValueError("MCP Tool effect is invalid")
        if definition.risk_level not in {"low", "medium", "high"}:
            raise ValueError("MCP Tool risk level is invalid")
        if definition.read_only != (definition.effect == "read"):
            raise ValueError("MCP Tool read_only and effect are inconsistent")
        if definition.effect == "read" and definition.confirmation_policy != "none":
            raise ValueError("Read-only MCP Tool cannot declare mutation confirmation")
        if definition.effect == "mutation" and definition.confirmation_policy not in {
            DINGTALK_CONFIRMATION_POLICY,
            "file_workspace_intent",
        }:
            raise ValueError("Mutation MCP Tool requires a supported confirmation policy")
        if definition.server_code == DINGTALK_MCP_SERVER_CODE:
            contract = DINGTALK_TOOL_CONTRACTS.get(identifier)
            if (
                contract is None
                or definition.required_scope != contract.required_scope
                or definition.operation_code != contract.operation_code
                or definition.risk_level != contract.risk_level
                or definition.target_policy != contract.target_policy
                or definition.destructive != contract.destructive
                or definition.idempotent != contract.idempotent
                or definition.open_world != contract.open_world
            ):
                raise ValueError("DingTalk MCP Tool execution metadata is inconsistent")


validate_mcp_server_policies()
validate_mcp_tool_manifest()
