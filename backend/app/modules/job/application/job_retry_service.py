from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.audit.application.audit_service import AuditService
from app.modules.delivery.application.result_delivery_service import (
    ResultDeliveryService,
)
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.job.application.builtin_tool_snapshot import (
    JobBuiltinToolSnapshotService,
)
from app.shared.config import QueueSettings
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import (
    ExecutionTimeout,
    DiagnosticLoopExhausted,
    NonRetryableExecutionError,
    PermissionDenied,
    RetryableExecutionError,
    ToolPolicyError,
)


class JobRetryService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        queue_settings: QueueSettings,
        audit_service: AuditService,
        delivery_service: ResultDeliveryService,
        builtin_tool_snapshot_service: JobBuiltinToolSnapshotService | None = None,
    ) -> None:
        self.repository = repository
        self.queue_settings = queue_settings
        self.audit_service = audit_service
        self.delivery_service = delivery_service
        self.builtin_tool_snapshot_service = builtin_tool_snapshot_service

    def is_retryable(self, exc: Exception) -> bool:
        if isinstance(
            exc,
            (
                PermissionDenied,
                ToolPolicyError,
                NonRetryableExecutionError,
                DiagnosticLoopExhausted,
            ),
        ):
            return False
        return isinstance(
            exc, (RetryableExecutionError, ExecutionTimeout, TimeoutError, ConnectionError)
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def handle_failure(self, job: AgentJob, exc: Exception, correlation_id: str) -> str:
        if self.builtin_tool_snapshot_service is not None:
            try:
                self.builtin_tool_snapshot_service.verify(job.id)
            except NonRetryableExecutionError as snapshot_error:
                exc = snapshot_error
        safe_message = getattr(exc, "safe_message", str(exc))
        error_code = getattr(exc, "error_code", "") or "agent_runtime_error"
        diagnostics = getattr(exc, "diagnostics", {})
        if self.is_retryable(exc) and job.retry_count < job.max_retry_count:
            delay_seconds = max(self.queue_settings.retry_delay_seconds, 1)
            next_retry_at = (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
            scheduled = self.repository.schedule_retry(
                job.id,
                error_message=safe_message,
                error_code=error_code,
                next_retry_at=next_retry_at,
            )
            dispatch_event = self.repository.rearm_dispatch_for_retry(
                job_id=job.id,
                next_attempt_at=next_retry_at,
            )
            self.audit_service.record(
                "job.retry.scheduled",
                status="SUCCEEDED",
                summary="Agent job retry scheduled",
                job_id=job.id,
                payload={
                    "correlation_id": correlation_id,
                    "retry_count": scheduled.retry_count,
                    "next_retry_at": scheduled.next_retry_at,
                    "dispatch_event_id": dispatch_event.id,
                    "error_code": error_code,
                    "diagnostics": diagnostics,
                    **_business_application_context(job),
                },
            )
            return "retry"
        terminal_status = (
            JobStatus.TIMEOUT
            if isinstance(exc, (ExecutionTimeout, TimeoutError))
            else JobStatus.FAILED
        )
        terminal = self.repository.transition_job(
            job_id=job.id,
            target=terminal_status,
            error_message=safe_message,
            error_code=error_code,
        )
        delivery_id = self.delivery_service.enqueue_job_failure(
            job_id=job.id,
            reason=safe_message,
            error_code=error_code,
            correlation_id=correlation_id,
        )
        self.audit_service.record(
            "job.dead.persisted",
            status="SUCCEEDED",
            summary="Terminal Agent job failure persisted without broker replay",
            job_id=job.id,
            payload={
                "correlation_id": correlation_id,
                "error_code": error_code,
                "delivery_id": delivery_id,
                **_business_application_context(job),
            },
        )
        return "timeout" if terminal.status == JobStatus.TIMEOUT else "dead"

    def reschedule_if_early(self, job: AgentJob, correlation_id: str) -> bool:
        if job.status != JobStatus.RETRY_WAIT or not job.next_retry_at:
            return False
        due_at = datetime.fromisoformat(job.next_retry_at)
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=UTC)
        remaining = (due_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            return False
        self.audit_service.record(
            "job.retry.early_duplicate_ignored",
            status="SUCCEEDED",
            summary="Early duplicate retry message ignored; Outbox remains authoritative",
            job_id=job.id,
            payload={
                "correlation_id": correlation_id,
                "remaining_seconds": max(int(remaining), 1),
                **_business_application_context(job),
            },
        )
        return True


def _business_application_context(job: AgentJob) -> dict[str, str]:
    return {
        "business_application_code": job.business_application_code,
        "business_application_publication_id": (job.business_application_publication_id),
        "business_application_deployment_id": (job.business_application_deployment_id),
        "business_application_route_id": job.business_application_route_id,
    }
