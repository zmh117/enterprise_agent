from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError


class ExternalActionStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    FAILED_UNCERTAIN = "FAILED_UNCERTAIN"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class NormalizedTodoArguments:
    subject: str
    description: str
    due_time: str
    due_time_ms: int | None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "subject": self.subject,
            "description": self.description,
            "due_time": self.due_time,
        }
        if self.due_time_ms is not None:
            value["due_time_ms"] = self.due_time_ms
        return value


def normalize_todo_arguments(arguments: dict[str, Any]) -> NormalizedTodoArguments:
    allowed = {"subject", "description", "due_time"}
    if set(arguments) - allowed:
        raise _invalid("钉钉待办参数包含未允许字段")
    subject = _bounded_text(arguments.get("subject"), minimum=1, maximum=200, field="subject")
    description = _bounded_text(
        arguments.get("description", ""), minimum=0, maximum=2000, field="description"
    )
    due_time = _bounded_text(
        arguments.get("due_time", ""), minimum=0, maximum=64, field="due_time"
    )
    due_time_ms: int | None = None
    if due_time:
        try:
            parsed = datetime.fromisoformat(due_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid("截止时间必须是带时区的 ISO-8601 时间") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise _invalid("截止时间必须包含时区")
        due_time_ms = int(parsed.astimezone(UTC).timestamp() * 1000)
        due_time = parsed.isoformat()
    return NormalizedTodoArguments(
        subject=subject,
        description=description,
        due_time=due_time,
        due_time_ms=due_time_ms,
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bounded_text(value: Any, *, minimum: int, maximum: int, field: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} 必须是字符串")
    normalized = " ".join(value.strip().split()) if field == "subject" else value.strip()
    if not minimum <= len(normalized) <= maximum:
        raise _invalid(f"{field} 长度无效")
    return normalized


def _invalid(message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        message,
        safe_message=message,
        error_code="external_action_arguments_invalid",
    )
