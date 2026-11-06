"""Independent local-time daily schedule with explicit DST handling."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


def next_daily(after: datetime, local_time: str, timezone: str) -> str:
    try:
        if len(local_time) != 5 or local_time[2] != ":":
            raise ValueError
        hour, minute = map(int, local_time.split(":"))
        if not 0 <= hour < 24 or not 0 <= minute < 60 or after.tzinfo is None:
            raise ValueError
        zone = ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise CodeKnowledgeError("code_schedule_invalid") from None
    start = after.astimezone(zone).date()
    for day in range(3):
        wall = datetime.combine(start + timedelta(days=day), datetime.min.time()).replace(
            hour=hour, minute=minute
        )
        # A spring-forward gap runs at the first valid minute; a fall-back fold runs once.
        for shift in range(181):
            candidate = (wall + timedelta(minutes=shift)).replace(tzinfo=zone, fold=0)
            utc = candidate.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
                continue
            if utc > after.astimezone(UTC):
                return utc.isoformat()
            break
    raise CodeKnowledgeError("code_schedule_invalid")
