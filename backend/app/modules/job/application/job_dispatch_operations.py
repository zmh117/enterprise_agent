from __future__ import annotations

import hashlib

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.domain.job_dispatch import JobDispatchEvent
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class JobDispatchOperationsService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
        mcp_tool_snapshot_service: JobMcpToolSnapshotService | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.mcp_tool_snapshot_service = mcp_tool_snapshot_service

    def status(
        self,
        *,
        event_id: str = "",
        job_id: str = "",
    ) -> dict[str, object]:
        return _safe_event_status(self._resolve_exact(event_id=event_id, job_id=job_id))

    def metrics(self) -> dict[str, object]:
        return self.repository.dispatch_metrics()

    @operation_unit_of_work(lambda service: service.repository.database)
    def replay(
        self,
        *,
        event_id: str = "",
        job_id: str = "",
        actor_id: str,
        reason: str,
    ) -> dict[str, object]:
        normalized_actor = actor_id.strip()
        normalized_reason = reason.strip()
        if not normalized_actor:
            raise NonRetryableExecutionError(
                "Replay actor is required",
                safe_message="重放操作必须提供操作者标识",
                error_code="job_dispatch_replay_actor_required",
            )
        if not normalized_reason:
            raise NonRetryableExecutionError(
                "Replay reason is required",
                safe_message="重放操作必须提供原因",
                error_code="job_dispatch_replay_reason_required",
            )
        current = self._resolve_exact(event_id=event_id, job_id=job_id)
        if self.mcp_tool_snapshot_service is not None:
            self.mcp_tool_snapshot_service.verify(current.job_id)
        replayed = self.repository.replay_dead_dispatch(
            event_id=current.id,
            actor_id=normalized_actor,
        )
        reason_digest = hashlib.sha256(normalized_reason.encode("utf-8")).hexdigest()
        self.audit_service.record(
            "job.dispatch.replayed",
            status="SUCCEEDED",
            summary="DEAD Agent job dispatch was rearmed for bounded replay",
            job_id=replayed.job_id,
            actor_id=normalized_actor,
            payload={
                "event_id": replayed.id,
                "replay_count": replayed.replay_count,
                "max_replay_count": replayed.max_replay_count,
                "reason_digest": reason_digest,
            },
        )
        return _safe_event_status(replayed)

    def _resolve_exact(
        self,
        *,
        event_id: str,
        job_id: str,
    ) -> JobDispatchEvent:
        normalized_event = event_id.strip()
        normalized_job = job_id.strip()
        if bool(normalized_event) == bool(normalized_job):
            raise NonRetryableExecutionError(
                "Exactly one dispatch event_id or job_id is required",
                safe_message="必须且只能指定一个 event_id 或 job_id",
                error_code="job_dispatch_exact_identifier_required",
            )
        if normalized_event:
            return self.repository.get_dispatch_event(normalized_event)
        event = self.repository.get_dispatch_event_for_job(normalized_job)
        if event is None:
            raise NotFound(
                f"Job dispatch event not found for job: {normalized_job}",
                safe_message="未找到该任务对应的调度事件",
                error_code="job_dispatch_event_not_found",
            )
        return event


def _safe_event_status(event: JobDispatchEvent) -> dict[str, object]:
    return {
        "event_id": event.id,
        "event_key": event.event_key,
        "job_id": event.job_id,
        "correlation_id": event.correlation_id,
        "status": event.status.value,
        "attempt_count": event.attempt_count,
        "max_attempts": event.max_attempts,
        "replay_count": event.replay_count,
        "max_replay_count": event.max_replay_count,
        "next_attempt_at": event.next_attempt_at,
        "claimed_by": event.claimed_by,
        "claimed_at": event.claimed_at,
        "published_at": event.published_at,
        "dead_at": event.dead_at,
        "last_replayed_at": event.last_replayed_at,
        "last_replayed_by": event.last_replayed_by,
        "last_error_code": event.last_error_code,
        "last_error_summary": event.last_error_summary,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }
