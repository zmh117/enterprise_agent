from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping


DINGTALK_CREATE_TODO_TOOL_IDENTIFIER: Final = "dingtalk_create_todo"
DINGTALK_CONFIRMATION_POLICY: Final = "external_action_card_v1"


@dataclass(frozen=True, slots=True)
class DingTalkToolContract:
    identifier: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


_CREATE_TODO_INPUT: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "minLength": 1, "maxLength": 200},
        "description": {"type": "string", "maxLength": 2000},
        "due_time": {"type": "string", "format": "date-time", "maxLength": 64},
    },
    "required": ["subject"],
    "additionalProperties": False,
}

_CREATE_TODO_OUTPUT: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "status": {"const": "confirmation_required"},
        "action_intent_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "revision": {"type": "integer", "minimum": 1},
        "expires_at": {"type": "string", "format": "date-time", "maxLength": 64},
        "summary": {
            "type": "object",
            "properties": {
                "operation": {"const": "创建钉钉待办"},
                "subject": {"type": "string", "maxLength": 200},
                "due_time": {"type": "string", "maxLength": 64},
            },
            "required": ["operation", "subject", "due_time"],
            "additionalProperties": False,
        },
    },
    "required": ["status", "action_intent_id", "revision", "expires_at", "summary"],
    "additionalProperties": False,
}


DINGTALK_TOOL_CONTRACTS: Final[Mapping[str, DingTalkToolContract]] = MappingProxyType(
    {
        DINGTALK_CREATE_TODO_TOOL_IDENTIFIER: DingTalkToolContract(
            identifier=DINGTALK_CREATE_TODO_TOOL_IDENTIFIER,
            description=(
                "为当前钉钉用户准备一个本人待办。此操作不会立即执行；"
                "必须由原用户在确认卡片中同意后才会创建。"
            ),
            input_schema=_CREATE_TODO_INPUT,
            output_schema=_CREATE_TODO_OUTPUT,
        )
    }
)


def require_dingtalk_tool_contract(identifier: str) -> DingTalkToolContract:
    try:
        return DINGTALK_TOOL_CONTRACTS[identifier]
    except KeyError as exc:
        raise KeyError(f"Unknown DingTalk MCP Tool: {identifier}") from exc
