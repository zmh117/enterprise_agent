from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Protocol

from app.modules.admin.application.contracts import TimeWindow
from app.modules.admin.application.scope import AdminScope
from app.modules.admin.infrastructure import AdminReadRepository


class QueueStatusPort(Protocol):
    def collect(self) -> dict[str, Any]: ...


class DashboardQueryService:
    def __init__(self, repository: AdminReadRepository, queues: QueueStatusPort) -> None:
        self.repository = repository
        self.queues = queues

    def query(self, *, window: TimeWindow, scope: AdminScope) -> dict[str, Any]:
        start, end = window.as_iso()
        jobs = [item for item in self.repository.jobs_in_window(start, end) if scope.permits(item)]
        job_ids = {str(item["id"]) for item in jobs}
        deliveries = [
            item
            for item in self.repository.delivery_failures(start, end)
            if str(item["job_id"]) in job_ids
        ]
        sessions = [
            item
            for item in self.repository.recent_sessions(start, end, limit=50)
            if scope.permits(item)
        ][:10]
        webhook_events = [
            item
            for item in self.repository.recent_webhook_events(start, end, limit=50)
            if not item.get("job_id") or str(item["job_id"]) in job_ids
        ][:10]
        raw_counts = self.repository.counts()
        counts = {
            "users": raw_counts["users"] if scope.global_access else 1,
            "agents": raw_counts["agents"]
            if scope.global_access
            else len({item["agent_code"] for item in jobs}),
            "channels": raw_counts["channels"]
            if scope.global_access
            else len(
                {item["source_connector_id"] for item in jobs if item.get("source_connector_id")}
            ),
            "jobs": len(jobs),
            "exceptions": sum(1 for item in jobs if item["status"] in {"FAILED", "TIMEOUT"})
            + len(deliveries),
        }
        statuses = Counter(str(item["status"]) for item in jobs)
        return {
            "window": {"start": start, "end": end},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": counts,
            "jobs": {
                "counts": dict(sorted(statuses.items())),
                "retry_wait": statuses.get("RETRY_WAIT", 0),
                "failed": statuses.get("FAILED", 0),
                "timeout": statuses.get("TIMEOUT", 0),
                "delivery_failed": len(deliveries),
                "recent_exceptions": [
                    {
                        "id": item["id"],
                        "status": item["status"],
                        "project_code": item["project_code"],
                        "source_channel": item["source_channel"],
                        "error_summary": item["error_summary"],
                        "created_at": item["created_at"],
                    }
                    for item in jobs
                    if item["status"] in {"FAILED", "TIMEOUT"}
                ][:10],
            },
            "delivery": {"failed": deliveries[:10]},
            "queues": self.queues.collect(),
            "recent_webhooks": webhook_events,
            "recent_conversations": sessions,
        }
