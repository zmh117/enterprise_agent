from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final

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


SERVER_CODE: Final = "ones-mcp"
SERVER_VERSION: Final = "0.1.0"
TOOL_IDENTIFIER: Final = "ones_work_item_search"
REQUIRED_SCOPE: Final = "mcp:ones-mcp:ones_work_item_search:invoke"

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

PROVIDER_HEADERS: Final = MappingProxyType(
    {
        "token": "Ones-Auth-Token",
        "user": "Ones-User-Id",
    }
)
