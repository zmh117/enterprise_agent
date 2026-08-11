from __future__ import annotations

import re

from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError

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

ALLOWED_LOKI_SELECTOR_LABELS = {
    "cluster",
    "container",
    "region",
    "service",
    "service_name",
    "workshop",
}
LOKI_SELECTOR_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.:/-]+$")


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
    if not selector:
        raise ToolPolicyError("Loki selector is required", safe_message="必须填写 Loki 选择器")
    for label, value in selector.items():
        if label not in ALLOWED_LOKI_SELECTOR_LABELS:
            raise ToolPolicyError(f"Loki selector label is not allowed: {label}")
        if not value:
            raise ToolPolicyError(
                "Loki selector value is required",
                safe_message="必须填写 Loki 选择器值",
            )
        if not LOKI_SELECTOR_VALUE_PATTERN.fullmatch(value):
            raise ToolPolicyError(
                "Loki selector contains unsafe characters",
                safe_message="Loki 选择器包含不安全字符",
            )
    if minutes <= 0 or minutes > settings.max_loki_minutes:
        raise ToolPolicyError(
            "Loki time range exceeds configured maximum",
            safe_message="Loki 查询时间范围超过配置上限",
        )
    if limit <= 0 or limit > settings.max_loki_lines:
        raise ToolPolicyError(
            "Loki result size exceeds configured maximum",
            safe_message="Loki 查询结果数量超过配置上限",
        )


def assert_loki_label(label: str) -> None:
    if label not in ALLOWED_LOKI_SELECTOR_LABELS:
        raise ToolPolicyError(f"Loki selector label is not allowed: {label}")
