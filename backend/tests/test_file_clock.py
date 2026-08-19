from __future__ import annotations

from datetime import UTC, datetime

from app.modules.file_workspace.clock import (
    project_file_time_fields,
    to_shanghai_rfc3339,
)


def test_to_shanghai_rfc3339_converts_utc_midnight() -> None:
    assert to_shanghai_rfc3339("2026-08-14T00:00:00+00:00") == "2026-08-14T08:00:00+08:00"


def test_to_shanghai_rfc3339_accepts_z_suffix_and_naive_utc() -> None:
    assert to_shanghai_rfc3339("2026-08-19T04:49:29Z") == "2026-08-19T12:49:29+08:00"
    assert to_shanghai_rfc3339("2026-08-19T04:49:29") == "2026-08-19T12:49:29+08:00"


def test_to_shanghai_rfc3339_is_idempotent_for_shanghai() -> None:
    value = "2026-08-19T12:49:29+08:00"
    assert to_shanghai_rfc3339(value) == value


def test_to_shanghai_rfc3339_preserves_none_and_blank() -> None:
    assert to_shanghai_rfc3339(None) is None
    assert to_shanghai_rfc3339("") is None
    assert to_shanghai_rfc3339("   ") is None


def test_to_shanghai_rfc3339_accepts_datetime() -> None:
    instant = datetime(2026, 8, 19, 4, 49, 29, tzinfo=UTC)
    assert to_shanghai_rfc3339(instant) == "2026-08-19T12:49:29+08:00"


def test_project_file_time_fields_converts_agent_visible_instants() -> None:
    projected = project_file_time_fields(
        {
            "source_received_at": "2026-08-19T04:49:29+00:00",
            "version_created_at": "2026-08-19T04:50:00Z",
            "representation_created_at": "2026-08-19T04:51:00+00:00",
            "display_name": "image-1.png",
        }
    )
    assert projected["source_received_at"] == "2026-08-19T12:49:29+08:00"
    assert projected["version_created_at"] == "2026-08-19T12:50:00+08:00"
    assert projected["representation_created_at"] == "2026-08-19T12:51:00+08:00"
    assert projected["display_name"] == "image-1.png"
