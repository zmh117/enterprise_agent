from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.file_workspace.lifecycle import WORKSPACE_TIMEZONE

AGENT_FILE_TIMEZONE = WORKSPACE_TIMEZONE


def to_shanghai_rfc3339(value: datetime | str | None) -> str | None:
    """Project a stored instant to Asia/Shanghai RFC 3339 for Agent-visible surfaces."""

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
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(AGENT_FILE_TIMEZONE).isoformat()


def project_file_time_fields(item: dict[str, Any]) -> dict[str, Any]:
    projected = dict(item)
    if projected.get("source_received_at"):
        projected["source_received_at"] = to_shanghai_rfc3339(
            projected["source_received_at"]
        )
    if projected.get("version_created_at"):
        projected["version_created_at"] = (
            to_shanghai_rfc3339(projected["version_created_at"]) or ""
        )
    if projected.get("representation_created_at"):
        projected["representation_created_at"] = to_shanghai_rfc3339(
            projected["representation_created_at"]
        )
    return projected
