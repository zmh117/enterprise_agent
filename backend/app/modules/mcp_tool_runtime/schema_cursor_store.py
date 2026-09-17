from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError

from .pagination import ToolPaginationCursorCodec


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SchemaPaginationCursorStore:
    """Job-scoped references, never a substitute for the original cursor checks."""

    PREFIX = "pg_"
    TTL = timedelta(hours=24)

    def __init__(
        self, database: Database, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self.database = database
        self.clock = clock

    @staticmethod
    def unavailable() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Schema pagination storage is unavailable",
            safe_message="分页状态存储暂时不可用，请稍后从第一页重新查询",
            error_code="mcp_pagination_store_unavailable",
        )

    def issue(self, *, job_id: str, original_cursor: str) -> str:
        if not original_cursor or len(original_cursor) > ToolPaginationCursorCodec.MAX_CURSOR_CHARS:
            raise ToolPaginationCursorCodec._invalid("Stored cursor length is invalid")
        now = self.clock().astimezone(UTC)
        try:
            for _ in range(3):
                reference = self.PREFIX + secrets.token_hex(8)
                row = self.database.execute_one(
                    """
                    insert into mcp_schema_pagination_cursor
                        (job_id, reference, original_cursor, created_at, expires_at)
                    select ?, ?, ?, ?, ?
                     where exists (select 1 from agent_job where id = ? and status = 'RUNNING')
                    on conflict (job_id, reference) do nothing
                    returning reference
                    """,
                    (job_id, reference, original_cursor, now.isoformat(),
                     (now + self.TTL).isoformat(), job_id),
                )
                if row:
                    return str(row["reference"])
        except Exception as exc:
            raise self.unavailable() from exc
        raise self.unavailable()

    def resolve(self, *, job_id: str, reference: str) -> str:
        if re.fullmatch(r"pg_[0-9a-f]{16}", reference) is None:
            raise ToolPaginationCursorCodec._invalid("Pagination reference is malformed")
        try:
            row = self.database.execute_one(
                """
                select c.original_cursor
                  from mcp_schema_pagination_cursor c
                  join agent_job j on j.id = c.job_id
                 where c.job_id = ? and c.reference = ? and c.expires_at > ?
                   and j.status = 'RUNNING'
                """,
                (job_id, reference, self.clock().astimezone(UTC).isoformat()),
            )
        except Exception as exc:
            raise self.unavailable() from exc
        if not row:
            raise ToolPaginationCursorCodec._invalid("Pagination reference is unavailable")
        original = row["original_cursor"]
        if not isinstance(original, str) or not 1 <= len(original) <= ToolPaginationCursorCodec.MAX_CURSOR_CHARS:
            raise ToolPaginationCursorCodec._invalid("Stored pagination cursor is invalid")
        return original

    def purge_expired(self, *, batch_size: int = 500) -> int:
        if type(batch_size) is not int or not 1 <= batch_size <= 500:
            raise ValueError("Schema cursor cleanup batch must be between 1 and 500")
        try:
            rows = self.database.execute(
                """
                delete from mcp_schema_pagination_cursor
                 where (job_id, reference) in (
                    select job_id, reference from mcp_schema_pagination_cursor
                     where expires_at <= ? order by expires_at, job_id, reference limit ?
                 ) returning reference
                """,
                (self.clock().astimezone(UTC).isoformat(), batch_size),
            )
        except Exception as exc:
            raise self.unavailable() from exc
        return len(rows)
