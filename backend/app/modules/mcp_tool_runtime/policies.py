from __future__ import annotations

import re

from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError
from app.shared.loki_contract import assert_loki_label as assert_loki_label
from app.shared.loki_contract import assert_loki_selector, assert_loki_query_limits

FORBIDDEN_SQL = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
    "call",
    "execute",
    "copy",
    "merge",
}

FORBIDDEN_REDIS = {
    "del",
    "delete",
    "set",
    "mset",
    "expire",
    "flushall",
    "flushdb",
    "eval",
    "script",
}


def assert_readonly_sql(sql: str) -> None:
    normalized = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    normalized = re.sub(r"--.*?$", " ", normalized, flags=re.M).strip().lower()
    first = normalized.split(None, 1)[0] if normalized else ""
    if first not in {"select", "with"}:
        raise ToolPolicyError(
            "Only SELECT or WITH queries are allowed",
            safe_message="只允许执行 SELECT 或 WITH 查询",
        )
    tokens = set(re.findall(r"[a-z_]+", normalized))
    blocked = tokens.intersection(FORBIDDEN_SQL)
    if blocked:
        raise ToolPolicyError(f"SQL contains forbidden operation: {sorted(blocked)[0]}")


def assert_redis_readonly(
    operation: str, *, limit: int | None, settings: ExecutionSettings
) -> None:
    op = operation.lower()
    if op in FORBIDDEN_REDIS:
        raise ToolPolicyError(f"Redis operation {operation} is not read-only")
    if op not in {"get", "scan"}:
        raise ToolPolicyError(f"Redis operation {operation} is not supported")
    if op == "scan" and (limit is None or limit > settings.redis_scan_limit):
        raise ToolPolicyError(
            "Redis scan limit exceeds configured maximum",
            safe_message="Redis 扫描数量超过配置上限",
        )


def assert_loki_bounds(
    *,
    selector: dict[str, str],
    minutes: int,
    limit: int,
    settings: ExecutionSettings,
) -> None:
    # Empty additions are safe only because the executor injects mandatory scope.
    assert_loki_selector(selector, allow_empty=True)
    assert_loki_query_limits(
        minutes=minutes, limit=limit,
        max_minutes=settings.max_loki_minutes, max_lines=settings.max_loki_lines,
    )
