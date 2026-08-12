from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import urlsplit


SERVER_CODE: Final = "ones-mcp"
SERVER_VERSION: Final = "0.1.0"
TOOL_IDENTIFIER: Final = "ones_work_item_search"
REQUIRED_SCOPE: Final = "ones:work-item:read"

LOGIN_PATH: Final = "/project/api/project/auth/login"
WORK_ITEM_SEARCH_PATH: Final = "/project/api/project/items/graphql"
WORK_ITEM_SEARCH_DOCUMENT: Final = (
    "query SearchWorkItems($keyword: String!, $issue_type: String!, $limit: Int!, "
    "$user_id: String!, $team_id: String!) { "
    "workItems(keyword: $keyword, issueType: $issue_type, limit: $limit, "
    "userId: $user_id, teamId: $team_id) { "
    "items { number name type } total truncated } }"
)

ISSUE_TYPES: Final = ("demand", "task", "defect")
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


class ProviderContractError(ValueError):
    """Raised when deployment configuration violates the fixed ONES contract."""


@dataclass(frozen=True, slots=True)
class ProviderTarget:
    base_url: str
    host: str
    allow_insecure_local: bool


def validate_provider_target(
    base_url: str,
    *,
    allowed_hosts: tuple[str, ...],
    app_env: str,
    allow_insecure_local: bool,
) -> ProviderTarget:
    candidate = base_url.strip()
    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").lower().rstrip(".")
    hosts = {item.strip().lower().rstrip(".") for item in allowed_hosts if item.strip()}
    if not candidate or not host or host not in hosts:
        raise ProviderContractError("ONES Provider host is not allowlisted")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderContractError("ONES Provider URL must be an origin without credentials")
    if parsed.path not in {"", "/"}:
        raise ProviderContractError("ONES Provider URL must not include an API path")
    if parsed.scheme == "https":
        return ProviderTarget(candidate.rstrip("/"), host, False)
    local_http = (
        parsed.scheme == "http"
        and allow_insecure_local
        and app_env.strip().lower() in {"local", "test"}
    )
    if not local_http:
        raise ProviderContractError("ONES Provider must use HTTPS")
    return ProviderTarget(candidate.rstrip("/"), host, True)

