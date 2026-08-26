from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final

from app.shared.ones_tool_contracts import (
    require_ones_tool_contract,
)
from app.shared.mcp_server_policy import ONES_MCP_SERVER_CODE, mcp_invoke_scope
from services.ones_mcp_server.provider.graphql.operations.work_item_search import (
    ISSUE_TYPES,
    WORK_ITEM_SEARCH_DOCUMENT,
    WORK_ITEM_SEARCH_PATH,
)
from services.ones_mcp_server.provider.target import (
    ProviderContractError,
    ProviderTarget,
    validate_provider_target,
)


__all__ = [
    "ISSUE_TYPES",
    "LOGIN_PATH",
    "PROJECT_ROLE_MEMBER_LIMITS",
    "PROJECT_ROLE_MEMBERS_INPUT_SCHEMA",
    "PROJECT_ROLE_MEMBERS_OUTPUT_SCHEMA",
    "PROJECT_ROLE_MEMBERS_REQUIRED_SCOPE",
    "PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER",
    "PROVIDER_HEADERS",
    "ProviderContractError",
    "ProviderTarget",
    "REQUIRED_SCOPE",
    "SERVER_CODE",
    "SERVER_VERSION",
    "TOOL_IDENTIFIER",
    "TOOL_INPUT_SCHEMA",
    "TOOL_OUTPUT_SCHEMA",
    "WORK_ITEM_SEARCH_DOCUMENT",
    "WORK_ITEM_SEARCH_PATH",
    "validate_provider_target",
]


SERVER_CODE: Final = ONES_MCP_SERVER_CODE
SERVER_VERSION: Final = "0.1.0"
TOOL_IDENTIFIER: Final = "ones_work_item_search"
REQUIRED_SCOPE: Final = mcp_invoke_scope(SERVER_CODE, TOOL_IDENTIFIER)

LOGIN_PATH: Final = "/project/api/project/auth/login"
TOOL_INPUT_SCHEMA: Final[dict[str, Any]] = require_ones_tool_contract(
    TOOL_IDENTIFIER
).input_schema
TOOL_OUTPUT_SCHEMA: Final[dict[str, Any]] = require_ones_tool_contract(
    TOOL_IDENTIFIER
).output_schema

PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER: Final = "ones_list_project_role_members"
PROJECT_ROLE_MEMBERS_REQUIRED_SCOPE: Final = mcp_invoke_scope(
    SERVER_CODE,
    PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
)
PROJECT_ROLE_MEMBER_LIMITS: Final = {
    "project_uuid": 64,
    "role_uuid": 128,
    "role_name": 200,
    "member_uuid": 128,
    "member_name": 200,
    "roles": 100,
    "members_per_role": 500,
    "unique_members": 2000,
}
PROJECT_ROLE_MEMBERS_INPUT_SCHEMA: Final[dict[str, Any]] = require_ones_tool_contract(
    PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER
).input_schema
PROJECT_ROLE_MEMBERS_OUTPUT_SCHEMA: Final[dict[str, Any]] = require_ones_tool_contract(
    PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER
).output_schema

PROVIDER_HEADERS: Final = MappingProxyType(
    {
        "token": "Ones-Auth-Token",
        "user": "Ones-User-Id",
    }
)

def ones_tool_required_scope(identifier: str) -> str:
    require_ones_tool_contract(identifier)
    return mcp_invoke_scope(SERVER_CODE, identifier)
