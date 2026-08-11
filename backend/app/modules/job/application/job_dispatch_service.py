from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import time

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.domain.job_dispatch import JobDispatchStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.shared.config import QueueSettings


@dataclass(frozen=True)
class JobDispatchPublishResult:
    published: int = 0
    failed: int = 0
    dead: int = 0
    recovered: int = 0
    expired: int = 0


class JobDispatchOutboxDispatcher:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        publisher: MessagePublisher,
        audit_service: AuditService,
        settings: QueueSettings,
        worker_id: str = "job-dispatch-outbox",
        mcp_tool_snapshot_service: JobMcpToolSnapshotService | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.audit_service = audit_service
        self.settings = settings
        self.worker_id = worker_id
        self.mcp_tool_snapshot_service = mcp_tool_snapshot_service

    def publish_pending(self, *, limit: int = 100) -> JobDispatchPublishResult:
        stale_before = (
            datetime.now(UTC)
            - timedelta(
                seconds=max(
                    1,
                    self.settings.dispatch_outbox_claim_timeout_seconds,
                )
            )
        ).isoformat()
        recovered, recovered_dead = self.repository.recover_stale_dispatch_claims(
            stale_before=stale_before,
        )
        expired = self.repository.expire_terminal_job_dispatches()
        published = failed = dead = 0
        for _ in range(min(max(1, int(limit)), 1000)):
            event = self.repository.claim_dispatch_event(worker_id=self.worker_id)
            if event is None:
                break
            try:
                if self.mcp_tool_snapshot_service is not None:
                    self.mcp_tool_snapshot_service.verify(event.job_id)
                self.publisher.publish_agent_job(
                    event.id,
                    event.job_id,
                    event.correlation_id,
                )
            except Exception as exc:
                failed += 1
                state = self.repository.mark_dispatch_failed(
                    event_id=event.id,
                    worker_id=self.worker_id,
                    error_code=_safe_error_code(exc),
                    error_summary=_safe_error_summary(exc),
                    retry_base_seconds=(self.settings.dispatch_outbox_retry_base_seconds),
                )
                if state.status == JobDispatchStatus.DEAD:
                    dead += 1
                self.audit_service.record(
                    "job.dispatch.publish_failed",
                    status=state.status.value,
                    summary="Agent job dispatch publication failed",
                    job_id=event.job_id,
                    actor_id=self.worker_id,
                    payload={
                        "event_id": event.id,
                        "attempt_count": state.attempt_count,
                        "outbox_status": state.status.value,
                        "error_code": state.last_error_code,
                    },
                )
                continue
            if not self._confirm_published(
                event_id=event.id,
            ):
                raise RuntimeError(
                    "Job dispatch publisher confirm succeeded but claim ownership was lost"
                )
            published += 1
            self.audit_service.record(
                "queue.dispatched",
                status="SUCCEEDED",
                summary="Agent job dispatched to message bus",
                job_id=event.job_id,
                actor_id=self.worker_id,
                payload={
                    "event_id": event.id,
                    "event_key": event.event_key,
                    "correlation_id": event.correlation_id,
                    "attempt_count": event.attempt_count,
                },
            )
        return JobDispatchPublishResult(
            published=published,
            failed=failed,
            dead=dead + recovered_dead,
            recovered=recovered,
            expired=expired,
        )

    def _confirm_published(self, *, event_id: str) -> bool:
        """Persist broker confirmation without ever publishing the event again."""

        for attempt in range(50):
            try:
                return self.repository.mark_dispatch_published(
                    event_id=event_id,
                    worker_id=self.worker_id,
                )
            except Exception as exc:
                sqlite_locked = (
                    self.repository.database.engine == "sqlite" and "locked" in str(exc).lower()
                )
                if not sqlite_locked or attempt == 49:
                    raise
                time.sleep(0.01)
        return False

    def metrics(self) -> dict[str, object]:
        return self.repository.dispatch_metrics()


def _safe_error_code(exc: Exception) -> str:
    code = str(getattr(exc, "error_code", "") or "").strip()
    return code[:100] if code else f"publisher_{exc.__class__.__name__.lower()}"[:100]


def _safe_error_summary(exc: Exception) -> str:
    safe_message = str(getattr(exc, "safe_message", "") or "").strip()
    if safe_message:
        return safe_message[:500]
    return f"Message bus publish failed ({exc.__class__.__name__})"
