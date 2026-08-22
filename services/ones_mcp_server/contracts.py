from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final

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
TOOL_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "keyword": {"type": "string", "minLength": 1, "maxLength": 200},
        "issue_type": {"type": "string", "enum": list(ISSUE_TYPES)},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
    "required": ["keyword", "issue_type", "limit"],
    "additionalProperties": False,
}
TOOL_OUTPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "name": {"type": "string", "maxLength": 500},
                    "type": {"type": "string", "enum": list(ISSUE_TYPES)},
                },
                "required": ["number", "name", "type"],
                "additionalProperties": False,
            },
        },
        "total": {"type": "integer", "minimum": 0},
        "truncated": {"type": "boolean"},
        "untrusted_data": {"const": True},
    },
    "required": ["items", "total", "truncated", "untrusted_data"],
    "additionalProperties": False,
}

PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER: Final = "ones_list_project_role_members"
PROJECT_ROLE_MEMBERS_REQUIRED_SCOPE: Final = mcp_invoke_scope(
    SERVER_CODE,
    PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
)
PROJECT_ROLE_MEMBER_LIMITS: Final = MappingProxyType(
    {
        "project_uuid": 64,
        "role_uuid": 128,
        "role_name": 200,
        "member_uuid": 128,
        "member_name": 200,
        "roles": 100,
        "members_per_role": 500,
        "unique_members": 2000,
    }
)
PROJECT_ROLE_MEMBERS_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "project_uuid": {
            "type": "string",
            "minLength": 1,
            "maxLength": PROJECT_ROLE_MEMBER_LIMITS["project_uuid"],
            "pattern": r"^[A-Za-z0-9_-]+$",
        }
    },
    "required": ["project_uuid"],
    "additionalProperties": False,
}
PROJECT_ROLE_MEMBERS_OUTPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "roles": {
            "type": "array",
            "maxItems": PROJECT_ROLE_MEMBER_LIMITS["roles"],
            "items": {
                "type": "object",
                "properties": {
                    "role_uuid": {
                        "type": "string",
                        "maxLength": PROJECT_ROLE_MEMBER_LIMITS["role_uuid"],
                    },
                    "role_name": {
                        "type": "string",
                        "maxLength": PROJECT_ROLE_MEMBER_LIMITS["role_name"],
                    },
                    "members": {
                        "type": "array",
                        "maxItems": PROJECT_ROLE_MEMBER_LIMITS["members_per_role"],
                        "items": {
                            "type": "object",
                            "properties": {
                                "uuid": {
                                    "type": "string",
                                    "maxLength": PROJECT_ROLE_MEMBER_LIMITS["member_uuid"],
                                },
                                "name": {
                                    "type": "string",
                                    "maxLength": PROJECT_ROLE_MEMBER_LIMITS["member_name"],
                                },
                            },
                            "required": ["uuid", "name"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["role_uuid", "role_name", "members"],
                "additionalProperties": False,
            },
        },
        "untrusted_data": {"const": True},
    },
    "required": ["roles", "untrusted_data"],
    "additionalProperties": False,
}

PROVIDER_HEADERS: Final = MappingProxyType(
    {
        "token": "Ones-Auth-Token",
        "user": "Ones-User-Id",
    }
)
