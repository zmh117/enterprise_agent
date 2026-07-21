from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.shared.exceptions import NonRetryableExecutionError


DEFAULT_PAGE_LIMIT = 25
MAX_PAGE_LIMIT = 100
DEFAULT_WINDOW_HOURS = 24
MAX_WINDOW_DAYS = 31


@dataclass(frozen=True)
class PageWindow:
    limit: int = DEFAULT_PAGE_LIMIT
    cursor: str = ""

    @classmethod
    def parse(cls, *, limit: int = DEFAULT_PAGE_LIMIT, cursor: str = "") -> "PageWindow":
        if limit < 1 or limit > MAX_PAGE_LIMIT:
            raise NonRetryableExecutionError(
                "Page limit is outside the supported range",
                safe_message=f"limit must be between 1 and {MAX_PAGE_LIMIT}",
                error_code="invalid_page",
                field_errors=[{"field": "limit", "message": "Invalid page size"}],
            )
        if cursor:
            try:
                base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
            except Exception as exc:
                raise NonRetryableExecutionError(
                    "Pagination cursor is malformed",
                    safe_message="Pagination cursor is invalid",
                    error_code="invalid_cursor",
                    field_errors=[{"field": "cursor", "message": "Invalid cursor"}],
                ) from exc
        return cls(limit=limit, cursor=cursor)

    @staticmethod
    def encode(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")

    @staticmethod
    def decode(value: str) -> str:
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    @classmethod
    def parse(cls, *, start: str = "", end: str = "", now: datetime | None = None) -> "TimeWindow":
        current = now or datetime.now(timezone.utc)
        end_at = _parse_timestamp(end, "end") if end else current
        start_at = (
            _parse_timestamp(start, "start")
            if start
            else end_at - timedelta(hours=DEFAULT_WINDOW_HOURS)
        )
        if start_at >= end_at:
            raise _window_error("start must be before end", "start")
        if end_at - start_at > timedelta(days=MAX_WINDOW_DAYS):
            raise _window_error(f"time window cannot exceed {MAX_WINDOW_DAYS} days", "start")
        if end_at > current + timedelta(minutes=5):
            raise _window_error("end cannot be in the future", "end")
        return cls(start=start_at, end=end_at)

    def as_iso(self) -> tuple[str, str]:
        return self.start.isoformat(), self.end.isoformat()


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _window_error(f"{field} must be ISO-8601", field) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _window_error(message: str, field: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Invalid administration time window",
        safe_message=message,
        error_code="invalid_time_window",
        field_errors=[{"field": field, "message": message}],
    )
