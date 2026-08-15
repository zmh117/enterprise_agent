from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.file_workspace.domain import RetentionPeriod


WORKSPACE_TIMEZONE = ZoneInfo("Asia/Shanghai")


def task_workspace_expires_at(
    created_at: datetime,
    retention_period: RetentionPeriod | str,
) -> datetime:
    """Return the fixed next natural-period boundary in Asia/Shanghai."""
    if created_at.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    period = RetentionPeriod(retention_period)
    local = created_at.astimezone(WORKSPACE_TIMEZONE)
    if period is RetentionPeriod.DAY:
        expiry_date = local.date() + timedelta(days=1)
    elif period is RetentionPeriod.WEEK:
        expiry_date = local.date() + timedelta(days=7 - local.weekday())
    else:
        if local.month == 12:
            expiry_date = local.date().replace(
                year=local.year + 1, month=1, day=1
            )
        else:
            expiry_date = local.date().replace(month=local.month + 1, day=1)
    return datetime.combine(expiry_date, time.min, tzinfo=WORKSPACE_TIMEZONE)


def task_workspace_expiry_iso(
    created_at: datetime,
    retention_period: RetentionPeriod | str,
) -> str:
    return task_workspace_expires_at(created_at, retention_period).isoformat()


def task_workspace_expiry_utc(
    created_at: datetime,
    retention_period: RetentionPeriod | str,
) -> datetime:
    return task_workspace_expires_at(created_at, retention_period).astimezone(UTC)
