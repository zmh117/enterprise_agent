from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.shared.config import QueueSettings


class RetryRecoveryService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        publisher: MessagePublisher,
        audit_service: AuditService,
        queue_settings: QueueSettings,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.audit_service = audit_service
        self.queue_settings = queue_settings

    def reconcile(
        self,
        *,
        apply: bool = False,
        job_ids: list[str] | None = None,
        actor_id: str = "retry-recovery-cli",
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        lock_stale_before = (
            now
            - timedelta(
                seconds=max(self.queue_settings.consumer_heartbeat_seconds * 2, 300)
            )
        ).isoformat()
        legacy = self.repository.list_stranded_retry_jobs(
            job_ids, lock_stale_before=lock_stale_before
        )
        overdue = self.repository.list_overdue_retry_wait_jobs(
            before=now.isoformat(), job_ids=job_ids
        )
        candidates = [(job, "legacy_pending") for job in legacy] + [
            (job, "overdue_retry_wait") for job in overdue
        ]
        rows: list[dict[str, Any]] = []
        for job, candidate_type in candidates:
            row = self._safe_summary(job, candidate_type)
            if apply:
                row.update(self._apply(job, candidate_type, actor_id, now))
            rows.append(row)
        return {
            "mode": "apply" if apply else "dry-run",
            "candidate_count": len(rows),
            "current_retry_queue": self.queue_settings.retry_queue,
            "legacy_retry_queue": self.queue_settings.legacy_retry_queue,
            "legacy_queue_action": "report-only; never consumed, purged, or deleted",
            "jobs": rows,
        }

    def _apply(
        self,
        job: AgentJob,
        candidate_type: str,
        actor_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        delay = max(self.queue_settings.retry_delay_seconds, 1)
        next_retry_at = (now + timedelta(seconds=delay)).isoformat()
        recovered = job
        if candidate_type == "legacy_pending":
            updated = self.repository.recover_stranded_retry(
                job.id,
                next_retry_at=next_retry_at,
                lock_stale_before=(
                    now
                    - timedelta(
                        seconds=max(
                            self.queue_settings.consumer_heartbeat_seconds * 2,
                            300,
                        )
                    )
                ).isoformat(),
            )
            if updated is None:
                return {"apply_status": "skipped_state_changed"}
            recovered = updated
        try:
            self.publisher.publish_retry(job.id, f"recovery:{job.id}", delay)
        except Exception as exc:
            self.audit_service.record(
                "job.retry.recovery_publish_failed",
                status="FAILED",
                summary="Retry recovery publish failed",
                job_id=job.id,
                actor_id=actor_id,
                payload={
                    "before_status": job.status.value,
                    "after_status": recovered.status.value,
                    "queue": self.queue_settings.retry_queue,
                    "publish_error_type": exc.__class__.__name__,
                },
            )
            return {"apply_status": "publish_failed", "status": recovered.status.value}
        self.audit_service.record(
            "job.retry.recovered",
            status="SUCCEEDED",
            summary="Stranded Agent retry recovered",
            job_id=job.id,
            actor_id=actor_id,
            payload={
                "before_status": job.status.value,
                "after_status": recovered.status.value,
                "queue": self.queue_settings.retry_queue,
            },
        )
        return {"apply_status": "published", "status": recovered.status.value}

    def _safe_summary(self, job: AgentJob, candidate_type: str) -> dict[str, Any]:
        route = job.reply_route or {}
        raw_target = route.get("target")
        target: dict[str, Any] = raw_target if isinstance(raw_target, dict) else {}
        return {
            "job_id": job.id,
            "candidate_type": candidate_type,
            "status": job.status.value,
            "retry_count": job.retry_count,
            "max_retry_count": job.max_retry_count,
            "last_error_code": job.last_error_code,
            "last_error_at": job.last_error_at,
            "next_retry_at": job.next_retry_at,
            "route_type": str(route.get("type") or "none"),
            "connector_id": str(route.get("connector_id") or ""),
            "has_session_webhook": bool(
                target.get("session_webhook") or target.get("sessionWebhook")
            ),
        }
