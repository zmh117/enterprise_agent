from __future__ import annotations

from app.shared.dingtalk_tool_contracts import (
    DINGTALK_CREATE_TODO_TOOL_IDENTIFIER,
    DINGTALK_TOOL_CONTRACTS,
    DingTalkToolContract,
    require_dingtalk_tool_contract,
)
from app.shared.mcp_server_policy import DINGTALK_MCP_SERVER_CODE


SERVER_CODE = DINGTALK_MCP_SERVER_CODE
SERVER_VERSION = "0.2.0"
TOOL_CONTRACTS = DINGTALK_TOOL_CONTRACTS


def require_tool_contract(identifier: str) -> DingTalkToolContract:
    return require_dingtalk_tool_contract(identifier)


# Compatibility aliases for the existing create-todo implementation. New code
# resolves the invoked Tool contract by identifier instead of using these aliases.
TOOL_IDENTIFIER = DINGTALK_CREATE_TODO_TOOL_IDENTIFIER
TOOL_CONTRACT = DINGTALK_TOOL_CONTRACTS[TOOL_IDENTIFIER]
TOOL_INPUT_SCHEMA = TOOL_CONTRACT.input_schema
TOOL_OUTPUT_SCHEMA = TOOL_CONTRACT.output_schema
REQUIRED_SCOPE = TOOL_CONTRACT.required_scope
OPERATION_CODE = TOOL_CONTRACT.operation_code
