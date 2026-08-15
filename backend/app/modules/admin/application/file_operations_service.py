from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.shared.database import Database, assert_external_io_allowed


class QueueStatusPort(Protocol):
    def collect(self) -> dict[str, Any]: ...


class FileOperationsStatusService:
    """Safe operational projection without file names, object keys, bodies or secrets."""

    def __init__(
        self,
        database: Database,
        queues: QueueStatusPort,
        *,
        attachment_queue: str,
        file_service_base_url: str,
        file_service_allowed_hosts: tuple[str, ...],
        probe: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.database = database
        self.queues = queues
        self.attachment_queue = attachment_queue
        self.file_service_base_url = file_service_base_url
        self.file_service_allowed_hosts = file_service_allowed_hosts
        self.probe = probe or self._probe_file_service

    def query(self) -> dict[str, Any]:
        file_service = self.probe()
        queue_result = self.queues.collect()
        queue = next(
            (
                item
                for item in queue_result.get("items") or []
                if item.get("name") == self.attachment_queue
            ),
            None,
        )
        queue_ready = bool(
            isinstance(queue, dict)
            and queue.get("availability") == "available"
            and queue.get("consumers") == 1
        )
        metrics = self._metrics()
        return {
            "file_service": file_service,
            "file_worker": {
                "configured": True,
                "ready": bool(file_service.get("ready")) and queue_ready,
                "reason_code": (
                    "ready"
                    if bool(file_service.get("ready")) and queue_ready
                    else "file_worker_unavailable"
                ),
                "attachment_queue": {
                    "availability": (
                        str(queue.get("availability"))
                        if isinstance(queue, dict)
                        else "unavailable"
                    ),
                    "ready": queue.get("ready") if isinstance(queue, dict) else None,
                    "unacked": queue.get("unacked") if isinstance(queue, dict) else None,
                    "consumers": queue.get("consumers") if isinstance(queue, dict) else None,
                },
            },
            "backlog": metrics["backlog"],
            "earliest_due": metrics["earliest_due"],
            "recent_cleanup": metrics["recent_cleanup"],
        }

    def _metrics(self) -> dict[str, Any]:
        counts = self.database.execute_one(
            """
            select
              sum(case when status in ('PENDING', 'RETRY') then 1 else 0 end) as cleanup,
              sum(case when resource_type = 'STAGING_OBJECT' and status in ('PENDING', 'RETRY') then 1 else 0 end) as staging,
              sum(case when resource_type = 'ATTACHMENT_CONTENT' and status in ('PENDING', 'RETRY') then 1 else 0 end) as attachment,
              min(case when status in ('PENDING', 'RETRY') then next_attempt_at end) as earliest_due
            from file_cleanup_fact
            """
        ) or {}
        workspaces = self.database.execute_one(
            "select count(*) as value from task_workspace where status in ('EXPIRED', 'CLEANING')"
        ) or {}
        retained = self.database.execute_one(
            "select count(*) as value from file_retention_fact where expires_at <= current_timestamp"
        ) or {}
        conflicts = self.database.execute_one(
            "select count(*) as value from file_conflict_candidate where status = 'OPEN'"
        ) or {}
        recent = self.database.execute_one(
            """
            select status, resource_type, reason,
                   coalesce(failure_code, '') as failure_code, updated_at
              from file_cleanup_fact
             order by updated_at desc, id desc limit 1
            """
        )
        return {
            "backlog": {
                "cleanup": int(counts.get("cleanup") or 0),
                "staging": int(counts.get("staging") or 0),
                "attachment": int(counts.get("attachment") or 0),
                "workspace": int(workspaces.get("value") or 0),
                "retained": int(retained.get("value") or 0),
                "conflict": int(conflicts.get("value") or 0),
            },
            "earliest_due": str(counts.get("earliest_due") or ""),
            "recent_cleanup": (
                {
                    "status": str(recent.get("status") or ""),
                    "resource_type": str(recent.get("resource_type") or ""),
                    "reason": str(recent.get("reason") or ""),
                    "failure_code": str(recent.get("failure_code") or ""),
                    "updated_at": str(recent.get("updated_at") or ""),
                }
                if recent is not None
                else None
            ),
        }

    def _probe_file_service(self) -> dict[str, Any]:
        parsed = urlsplit(self.file_service_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname not in self.file_service_allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return {
                "configured": False,
                "ready": False,
                "reason_code": "file_service_not_configured",
            }
        request = urllib.request.Request(
            self.file_service_base_url.rstrip("/") + "/ready",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            assert_external_io_allowed("admin.file_service_readiness")
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = response.read(64 * 1024 + 1)
            value = json.loads(payload)
            if len(payload) > 64 * 1024 or not isinstance(value, dict):
                raise ValueError("File Service readiness response is invalid")
            ready = value.get("status") == "ok"
            return {
                "configured": True,
                "ready": ready,
                "reason_code": "ready" if ready else "file_service_unavailable",
            }
        except (
            OSError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.URLError,
        ):
            return {
                "configured": True,
                "ready": False,
                "reason_code": "file_service_unavailable",
            }
