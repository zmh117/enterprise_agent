from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AccountingStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class ExecutionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ExecutionFailureStage(StrEnum):
    RUNTIME_START = "RUNTIME_START"
    RUNTIME_PROTOCOL = "RUNTIME_PROTOCOL"
    MCP_CONNECTION = "MCP_CONNECTION"
    MODEL_API = "MODEL_API"
    TOOL_PERMISSION = "TOOL_PERMISSION"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    UNKNOWN = "UNKNOWN"


TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    cache_creation_input_tokens: int | None
    cache_read_input_tokens: int | None

    @classmethod
    def from_payload(cls, payload: object) -> TokenUsage:
        source = payload if isinstance(payload, dict) else {}
        values = {field: _optional_counter(source.get(field)) for field in TOKEN_FIELDS}
        return cls(**values)

    def as_dict(self) -> dict[str, int | None]:
        return {field: getattr(self, field) for field in TOKEN_FIELDS}


def bounded_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:maximum] if text else None


def _optional_counter(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        candidate = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if candidate < 0 or candidate > 9_223_372_036_854_775_807:
        return None
    return candidate
