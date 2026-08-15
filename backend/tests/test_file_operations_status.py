from __future__ import annotations

import json
from typing import Any

from app.modules.admin.application.file_operations_service import (
    FileOperationsStatusService,
)


class _Database:
    def execute_one(self, sql: str, params: tuple[object, ...] = ()) -> dict[str, Any] | None:
        del params
        normalized = " ".join(sql.split())
        if "from file_cleanup_fact" in normalized and "sum(case" in normalized:
            return {
                "cleanup": 7,
                "staging": 2,
                "attachment": 3,
                "earliest_due": "2026-08-15T01:00:00+00:00",
            }
        if "from task_workspace" in normalized:
            return {"value": 1}
        if "from file_retention_fact" in normalized:
            return {"value": 4}
        if "from file_conflict_candidate" in normalized:
            return {"value": 2}
        if "order by updated_at desc" in normalized:
            return {
                "status": "RETRY",
                "resource_type": "STAGING_OBJECT",
                "reason": "STAGING_EXPIRED",
                "failure_code": "TimeoutError",
                "updated_at": "2026-08-15T02:00:00+00:00",
            }
        raise AssertionError(normalized)


class _Queues:
    def collect(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "name": "agent.attachment.queue",
                    "availability": "available",
                    "ready": 5,
                    "unacked": 1,
                    "consumers": 1,
                }
            ]
        }


def test_file_operations_projection_is_safe_bounded_and_worker_aware() -> None:
    status = FileOperationsStatusService(
        _Database(),  # type: ignore[arg-type]
        _Queues(),
        attachment_queue="agent.attachment.queue",
        file_service_base_url="http://file-service:9105",
        file_service_allowed_hosts=("file-service",),
        probe=lambda: {
            "configured": True,
            "ready": True,
            "reason_code": "ready",
        },
    ).query()

    assert status["file_service"]["ready"] is True
    assert status["file_worker"]["ready"] is True
    assert status["file_worker"]["attachment_queue"] == {
        "availability": "available",
        "ready": 5,
        "unacked": 1,
        "consumers": 1,
    }
    assert status["backlog"] == {
        "cleanup": 7,
        "staging": 2,
        "attachment": 3,
        "workspace": 1,
        "retained": 4,
        "conflict": 2,
    }
    serialized = json.dumps(status)
    for forbidden in (
        "display_name",
        "object_key",
        "secret",
        "access_key",
        "file body",
    ):
        assert forbidden not in serialized.lower()
