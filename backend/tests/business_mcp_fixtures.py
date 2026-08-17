from __future__ import annotations

from app.modules.mcp_tool_runtime.manifest import (
    MCP_TOOL_MANIFEST,
    McpToolDefinition,
    mcp_tool_schema_hash,
)
from app.shared.mcp_server_policy import (
    MCP_SERVER_POLICIES,
    McpServerAuthMode,
    McpServerPolicy,
)


TEST_BUSINESS_SERVER_CODE = "test-business-mcp"
TEST_BUSINESS_TOOL_IDENTIFIER = "test_business_lookup"
TEST_BUSINESS_SECOND_TOOL_IDENTIFIER = "test_business_list"
TEST_BUSINESS_TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 64}},
}


def business_mcp_test_policies() -> dict[str, McpServerPolicy]:
    return {
        **MCP_SERVER_POLICIES,
        TEST_BUSINESS_SERVER_CODE: McpServerPolicy(
            server_code=TEST_BUSINESS_SERVER_CODE,
            auth_mode=McpServerAuthMode.BUSINESS_PRINCIPAL_JWT,
        ),
    }


def business_mcp_test_manifest() -> dict[str, McpToolDefinition]:
    return {
        **MCP_TOOL_MANIFEST,
        TEST_BUSINESS_TOOL_IDENTIFIER: McpToolDefinition(
            server_code=TEST_BUSINESS_SERVER_CODE,
            identifier=TEST_BUSINESS_TOOL_IDENTIFIER,
            description="仅用于验证多业务 MCP Principal 隔离的测试 Tool。",
            input_schema=dict(TEST_BUSINESS_TOOL_SCHEMA),
            schema_hash=mcp_tool_schema_hash(TEST_BUSINESS_TOOL_SCHEMA),
        ),
        TEST_BUSINESS_SECOND_TOOL_IDENTIFIER: McpToolDefinition(
            server_code=TEST_BUSINESS_SERVER_CODE,
            identifier=TEST_BUSINESS_SECOND_TOOL_IDENTIFIER,
            description="仅用于验证完整 scope 集合的第二个测试 Tool。",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            schema_hash=mcp_tool_schema_hash(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                }
            ),
        ),
    }
