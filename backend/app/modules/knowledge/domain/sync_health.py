"""只基于持久安全时间与状态判断停采，不把容器存活当同步成功。"""

from datetime import datetime
from typing import Any


def sync_health(
    binding: dict[str, Any],
    latest: dict[str, Any] | None,
    success: dict[str, Any] | None,
    active: dict[str, Any] | None,
    at: datetime,
) -> dict[str, Any]:
    def age(value: Any) -> float | None:
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
            if not isinstance(parsed, datetime) or parsed.tzinfo is None:
                return None
            return max(0.0, (at - parsed).total_seconds())
        except (ValueError, TypeError):
            return None

    threshold = binding["interval_seconds"] * 2
    success_at = success["updated_at"] if success else None
    success_age = age(success_at or binding["created_at"])
    progress_age = age(active["updated_at"]) if active else None
    reasons = []
    enabled = binding["enabled"] == 1
    error = latest.get("error_code") if latest else None
    safe_error = (
        error
        if isinstance(error, str)
        and error.startswith("knowledge_")
        and len(error) <= 128
        and all(c.isascii() and (c.isalnum() or c == "_") for c in error)
        else "knowledge_sync_failed"
        if error
        else None
    )
    if enabled:
        if success_age is None or success_age > threshold:
            reasons.append("knowledge_sync_success_stale")
        if active and (progress_age is None or progress_age > threshold):
            reasons.append("knowledge_sync_progress_stale")
        if latest and latest["error_code"]:
            reasons.append("knowledge_sync_run_failed")
    return {
        "healthy": not reasons,
        "enabled": enabled,
        "state": "disabled" if not enabled else "unhealthy" if reasons else "healthy",
        "reasons": reasons,
        "last_success_at": success_at,
        "last_success_age_seconds": int(success_age) if success_age is not None else None,
        "progress_age_seconds": int(progress_age) if progress_age is not None else None,
        "latest_run_id": latest["id"] if latest else None,
        "latest_phase": latest["phase"] if latest else None,
        "latest_error_code": safe_error,
        "latest_failed_at": latest.get("updated_at") if latest and error else None,
    }
