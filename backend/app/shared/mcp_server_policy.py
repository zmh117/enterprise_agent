from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class McpServerAuthMode(StrEnum):
    JOB_CONTEXT = "job-context"
    BUSINESS_PRINCIPAL_JWT = "business-principal-jwt"
    FILE_PRINCIPAL_JWT = "file-principal-jwt"


@dataclass(frozen=True, slots=True)
class McpServerPolicy:
    server_code: str
    auth_mode: McpServerAuthMode


TOOL_MCP_SERVER_CODE = "tool-mcp"
ONES_MCP_SERVER_CODE = "ones-mcp"
DINGTALK_MCP_SERVER_CODE = "dingtalk-mcp"
FILE_MCP_SERVER_CODE = "file-service"
BUSINESS_PRINCIPAL_HEADER_PREFIX = "x-mcp-principal-token-"
MAX_BUSINESS_PRINCIPAL_SERVERS = 8
MAX_MCP_PRINCIPAL_TOKEN_BYTES = 8 * 1024
MAX_BUSINESS_PRINCIPAL_HEADER_BYTES = 32 * 1024
_HEADER_SAFE_SERVER_CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


MCP_SERVER_POLICIES: Mapping[str, McpServerPolicy] = MappingProxyType(
    {
        TOOL_MCP_SERVER_CODE: McpServerPolicy(
            server_code=TOOL_MCP_SERVER_CODE,
            auth_mode=McpServerAuthMode.JOB_CONTEXT,
        ),
        ONES_MCP_SERVER_CODE: McpServerPolicy(
            server_code=ONES_MCP_SERVER_CODE,
            auth_mode=McpServerAuthMode.BUSINESS_PRINCIPAL_JWT,
        ),
        DINGTALK_MCP_SERVER_CODE: McpServerPolicy(
            server_code=DINGTALK_MCP_SERVER_CODE,
            auth_mode=McpServerAuthMode.BUSINESS_PRINCIPAL_JWT,
        ),
        FILE_MCP_SERVER_CODE: McpServerPolicy(
            server_code=FILE_MCP_SERVER_CODE,
            auth_mode=McpServerAuthMode.FILE_PRINCIPAL_JWT,
        ),
    }
)


def require_mcp_server_policy(
    server_code: str,
    *,
    policies: Mapping[str, McpServerPolicy] | None = None,
) -> McpServerPolicy:
    selected = MCP_SERVER_POLICIES if policies is None else policies
    policy = selected.get(server_code)
    if policy is None or policy.server_code != server_code:
        raise ValueError(f"Unknown MCP server policy: {server_code}")
    return policy


def require_business_principal_server(
    server_code: str,
    *,
    policies: Mapping[str, McpServerPolicy] | None = None,
) -> McpServerPolicy:
    if not _HEADER_SAFE_SERVER_CODE.fullmatch(server_code) or len(server_code) > 63:
        raise ValueError("Business MCP server code is not header-safe")
    policy = require_mcp_server_policy(server_code, policies=policies)
    if policy.auth_mode is not McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
        raise ValueError("MCP server does not use a Business Principal JWT")
    return policy


def validate_mcp_server_policies(
    policies: Mapping[str, McpServerPolicy] | None = None,
) -> None:
    selected = MCP_SERVER_POLICIES if policies is None else policies
    if not selected or any(code != policy.server_code for code, policy in selected.items()):
        raise ValueError("MCP Server policy keys are inconsistent")
    job_context_codes = {
        code
        for code, policy in selected.items()
        if policy.auth_mode is McpServerAuthMode.JOB_CONTEXT
    }
    file_principal_codes = {
        code
        for code, policy in selected.items()
        if policy.auth_mode is McpServerAuthMode.FILE_PRINCIPAL_JWT
    }
    if job_context_codes != {TOOL_MCP_SERVER_CODE}:
        raise ValueError("tool-mcp must be the only Job-context MCP Server")
    if file_principal_codes != {FILE_MCP_SERVER_CODE}:
        raise ValueError("file-service must be the only File Principal MCP Server")
    aliases: set[str] = set()
    for server_code, policy in selected.items():
        if policy.auth_mode is McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
            require_business_principal_server(server_code, policies=selected)
        alias = server_code.replace("-", "_")
        if alias in aliases:
            raise ValueError("MCP Server SDK aliases must be unique")
        aliases.add(alias)


def business_principal_header_name(
    server_code: str,
    *,
    policies: Mapping[str, McpServerPolicy] | None = None,
) -> str:
    require_business_principal_server(server_code, policies=policies)
    suffix = "-".join(part.capitalize() for part in server_code.split("-"))
    return f"X-MCP-Principal-Token-{suffix}"


def business_principal_server_code_from_header(
    header_name: str,
    *,
    policies: Mapping[str, McpServerPolicy] | None = None,
) -> str:
    normalized = header_name.strip().lower()
    if not normalized.startswith(BUSINESS_PRINCIPAL_HEADER_PREFIX):
        raise ValueError("Header is not a Business Principal Token header")
    server_code = normalized.removeprefix(BUSINESS_PRINCIPAL_HEADER_PREFIX)
    require_business_principal_server(server_code, policies=policies)
    if business_principal_header_name(server_code, policies=policies).lower() != normalized:
        raise ValueError("Business Principal Token header is not canonical")
    return server_code


def mcp_invoke_scope(server_code: str, tool_identifier: str) -> str:
    if not server_code or not tool_identifier:
        raise ValueError("MCP invoke scope requires a Server and Tool")
    return f"mcp:{server_code}:{tool_identifier}:invoke"


def mcp_sdk_server_alias(
    server_code: str,
    *,
    policies: Mapping[str, McpServerPolicy] | None = None,
) -> str:
    """Return the fixed Claude SDK alias for a code-owned MCP Server."""
    require_mcp_server_policy(server_code, policies=policies)
    return server_code.replace("-", "_")


validate_mcp_server_policies()
