from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

def to_utc_rfc3339(value: datetime | str | None) -> str | None:
    """Normalize a stored instant to the canonical machine-protocol UTC form."""

    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("file timestamp must be RFC 3339") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def canonicalize_file_time_fields(item: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(item)
    if canonical.get("source_received_at"):
        canonical["source_received_at"] = to_utc_rfc3339(
            canonical["source_received_at"]
        )
    if canonical.get("version_created_at"):
        canonical["version_created_at"] = (
            to_utc_rfc3339(canonical["version_created_at"]) or ""
        )
    if canonical.get("representation_created_at"):
        canonical["representation_created_at"] = to_utc_rfc3339(
            canonical["representation_created_at"]
        )
    return canonical
