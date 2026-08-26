from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.shared.ones_tool_contracts import ONES_STATUS_CATEGORIES
from services.ones_mcp_server.errors import OnesMcpError


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")


def invalid_input(message: str = "ONES Tool input is invalid") -> OnesMcpError:
    return OnesMcpError(
        message,
        safe_message="ONES 查询参数无效",
        error_code="ones_tool_input_invalid",
    )


def require_fields(
    arguments: object,
    *,
    allowed: set[str],
    required: set[str],
) -> dict[str, Any]:
    if not isinstance(arguments, dict) or not required <= set(arguments) <= allowed:
        raise invalid_input()
    return arguments


def identifier(value: object, *, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise invalid_input()
    return value


def text(value: object, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value):
        raise invalid_input()
    return value


def integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise invalid_input()
    return value


def identifier_list(value: object, *, maximum_items: int) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum_items:
        raise invalid_input()
    normalized = [identifier(item) for item in value]
    if len(set(normalized)) != len(normalized):
        raise invalid_input()
    return normalized


def status_categories(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise invalid_input()
    normalized = [str(item) for item in value]
    if len(set(normalized)) != len(normalized) or any(
        item not in ONES_STATUS_CATEGORIES for item in normalized
    ):
        raise invalid_input()
    return normalized


def timestamp(value: object) -> str:
    raw = text(value, maximum=64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise invalid_input() from None
    if parsed.tzinfo is None:
        raise invalid_input()
    return raw

