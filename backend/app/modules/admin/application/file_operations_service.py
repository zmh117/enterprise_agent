from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
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
        file_processing_queue: str,
        file_processing_retry_queue: str,
        file_processing_dead_queue: str,
        file_service_base_url: str,
        file_service_allowed_hosts: tuple[str, ...],
        file_processing_worker_base_url: str,
        file_processing_worker_allowed_hosts: tuple[str, ...],
        file_service_probe: Callable[[], dict[str, Any]] | None = None,
        file_processing_worker_probe: Callable[[], dict[str, Any]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.queues = queues
        self.attachment_queue = attachment_queue
        self.file_processing_queue = file_processing_queue
        self.file_processing_retry_queue = file_processing_retry_queue
        self.file_processing_dead_queue = file_processing_dead_queue
        self.file_service_base_url = file_service_base_url
        self.file_service_allowed_hosts = file_service_allowed_hosts
        self.file_processing_worker_base_url = file_processing_worker_base_url
        self.file_processing_worker_allowed_hosts = file_processing_worker_allowed_hosts
        self.file_service_probe = file_service_probe or self._probe_file_service
        self.file_processing_worker_probe = (
            file_processing_worker_probe or self._probe_file_processing_worker
        )
        self.now = now or (lambda: datetime.now(timezone.utc))

    def query(self) -> dict[str, Any]:
        file_service = self.file_service_probe()
        file_processing_worker = self.file_processing_worker_probe()
        queue_result = self.queues.collect()
        attachment_queue = self._find_queue(queue_result, self.attachment_queue)
        processing_queue = self._find_queue(queue_result, self.file_processing_queue)
        processing_retry_queue = self._find_queue(queue_result, self.file_processing_retry_queue)
        processing_dead_queue = self._find_queue(queue_result, self.file_processing_dead_queue)
        attachment_queue_ready = self._queue_ready(attachment_queue)
        processing_queue_ready = self._queue_ready(processing_queue)
        document_processing_ready = bool(
            file_service.get("ready")
            and file_processing_worker.get("ready")
            and processing_queue_ready
        )
        if document_processing_ready:
            document_processing_reason_code = "ready"
        elif not file_service.get("ready"):
            document_processing_reason_code = "file_service_unavailable"
        elif not file_processing_worker.get("ready"):
            document_processing_reason_code = str(
                file_processing_worker.get("reason_code") or "file_processing_worker_unavailable"
            )
        else:
            document_processing_reason_code = "file_processing_queue_unavailable"
        metrics = self._metrics()
        return {
            "file_service": file_service,
            "file_worker": {
                "configured": True,
                "ready": bool(file_service.get("ready")) and attachment_queue_ready,
                "reason_code": (
                    "ready"
                    if bool(file_service.get("ready")) and attachment_queue_ready
                    else "file_worker_unavailable"
                ),
                "attachment_queue": self._queue_projection(attachment_queue),
            },
            "document_processing": {
                "configured": bool(file_processing_worker.get("configured")),
                "ready": document_processing_ready,
                "reason_code": document_processing_reason_code,
                "file_processing_worker": file_processing_worker,
                "queues": {
                    "processing": self._queue_projection(processing_queue),
                    "retry": self._queue_projection(processing_retry_queue),
                    "dead": self._queue_projection(processing_dead_queue),
                },
            },
            "backlog": metrics["backlog"],
            "earliest_due": metrics["earliest_due"],
            "domain_outbox_earliest_created_at": metrics["domain_outbox_earliest_created_at"],
            "domain_outbox_failure_code": metrics["domain_outbox_failure_code"],
            "recent_cleanup": metrics["recent_cleanup"],
        }

    @staticmethod
    def _find_queue(queue_result: dict[str, Any], name: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in queue_result.get("items") or []
                if isinstance(item, dict) and item.get("name") == name
            ),
            None,
        )

    @staticmethod
    def _queue_ready(queue: dict[str, Any] | None) -> bool:
        return bool(
            queue and queue.get("availability") == "available" and queue.get("consumers") == 1
        )

    @staticmethod
    def _queue_projection(queue: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "availability": (str(queue.get("availability")) if queue else "unavailable"),
            "ready": queue.get("ready") if queue else None,
            "unacked": queue.get("unacked") if queue else None,
            "consumers": queue.get("consumers") if queue else None,
        }

    def _metrics(self) -> dict[str, Any]:
        counts = (
            self.database.execute_one(
                """
            select
              sum(case when status in ('PENDING', 'RETRY') then 1 else 0 end) as cleanup,
              sum(case when resource_type = 'STAGING_OBJECT' and status in ('PENDING', 'RETRY') then 1 else 0 end) as staging,
              sum(case when resource_type = 'ATTACHMENT_CONTENT' and status in ('PENDING', 'RETRY') then 1 else 0 end) as attachment,
              min(case when status in ('PENDING', 'RETRY') then next_attempt_at end) as earliest_due
            from file_cleanup_fact
            """
            )
            or {}
        )
        workspaces = (
            self.database.execute_one(
                "select count(*) as value from task_workspace where status in ('EXPIRED', 'CLEANING')"
            )
            or {}
        )
        retained = (
            self.database.execute_one(
                "select count(*) as value from file_retention_fact where expires_at <= ?",
                (self.now().isoformat(),),
            )
            or {}
        )
        conflicts = (
            self.database.execute_one(
                "select count(*) as value from file_conflict_candidate where status = 'OPEN'"
            )
            or {}
        )
        domain_outbox = (
            self.database.execute_one(
                """
            select
              sum(case when status in ('PENDING', 'FAILED') then 1 else 0 end)
                as backlog,
              min(case when status in ('PENDING', 'FAILED') then created_at end)
                as earliest_created_at
              from file_domain_outbox
            """
            )
            or {}
        )
        domain_outbox_failure = (
            self.database.execute_one(
                """
            select failure_code from file_domain_outbox
             where status = 'FAILED'
             order by updated_at desc, id desc
             limit 1
            """
            )
            or {}
        )
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
                "domain_outbox": int(domain_outbox.get("backlog") or 0),
            },
            "earliest_due": str(counts.get("earliest_due") or ""),
            "domain_outbox_earliest_created_at": str(
                domain_outbox.get("earliest_created_at") or ""
            ),
            "domain_outbox_failure_code": str(domain_outbox_failure.get("failure_code") or ""),
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
        return self._probe_internal_readiness(
            self.file_service_base_url,
            self.file_service_allowed_hosts,
            operation="admin.file_service_readiness",
            not_configured_reason="file_service_not_configured",
            unavailable_reason="file_service_unavailable",
        )

    def _probe_file_processing_worker(self) -> dict[str, Any]:
        return self._probe_internal_readiness(
            self.file_processing_worker_base_url,
            self.file_processing_worker_allowed_hosts,
            operation="admin.file_processing_worker_readiness",
            not_configured_reason="file_processing_worker_not_configured",
            unavailable_reason="file_processing_worker_unavailable",
            include_components=True,
        )

    @staticmethod
    def _probe_internal_readiness(
        base_url: str,
        allowed_hosts: tuple[str, ...],
        *,
        operation: str,
        not_configured_reason: str,
        unavailable_reason: str,
        include_components: bool = False,
    ) -> dict[str, Any]:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return {
                "configured": False,
                "ready": False,
                "reason_code": not_configured_reason,
                **(
                    {
                        "components": {
                            "rabbitmq": "unavailable",
                            "file_service": "unavailable",
                            "docling": "unavailable",
                        }
                    }
                    if include_components
                    else {}
                ),
            }
        request = urllib.request.Request(
            base_url.rstrip("/") + "/ready",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            assert_external_io_allowed(operation)
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = response.read(64 * 1024 + 1)
            if len(payload) > 64 * 1024:
                raise ValueError("Internal readiness response is too large")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("Internal readiness response is invalid")
            ready = value.get("status") == "ok" and value.get("ready", True) is True
            result: dict[str, Any] = {
                "configured": True,
                "ready": ready,
                "reason_code": (
                    "ready" if ready else str(value.get("reason_code") or unavailable_reason)
                ),
            }
            if include_components:
                components = value.get("components")
                result["components"] = {
                    name: (
                        "ready"
                        if isinstance(components, dict) and components.get(name) == "ready"
                        else "unavailable"
                    )
                    for name in ("rabbitmq", "file_service", "docling")
                }
            return result
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
                "reason_code": unavailable_reason,
                **(
                    {
                        "components": {
                            "rabbitmq": "unavailable",
                            "file_service": "unavailable",
                            "docling": "unavailable",
                        }
                    }
                    if include_components
                    else {}
                ),
            }
