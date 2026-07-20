from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.shared.config import QueueSettings
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
        publisher: MessagePublisher,
        queue_settings: QueueSettings,
        audit_service: AuditService,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.queue_settings = queue_settings
        self.audit_service = audit_service

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

    def handle_failure(self, job: AgentJob, exc: Exception, correlation_id: str) -> str:
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
            try:
                self.publisher.publish_retry(job.id, correlation_id, delay_seconds)
            except Exception as publish_exc:
                self.audit_service.record(
                    "job.retry.publish_failed",
                    status="FAILED",
                    summary="Retry dispatch failed; recovery is required",
                    job_id=job.id,
                    payload={
                        "correlation_id": correlation_id,
                        "retry_count": scheduled.retry_count,
                        "error_code": error_code,
                        "publish_error_type": publish_exc.__class__.__name__,
                    },
                )
                return "retry_dispatch_failed"
            self.audit_service.record(
                "job.retry.scheduled",
                status="SUCCEEDED",
                summary="Agent job retry scheduled",
                job_id=job.id,
                payload={
                    "correlation_id": correlation_id,
                    "retry_count": scheduled.retry_count,
                    "next_retry_at": scheduled.next_retry_at,
                    "error_code": error_code,
                    "diagnostics": diagnostics,
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
        try:
            self.publisher.publish_dead_letter(job.id, correlation_id, safe_message)
            self.audit_service.record(
                "job.dead_letter.published",
                status="SUCCEEDED",
                summary="Terminal Agent job published to dead-letter queue",
                job_id=job.id,
                payload={"correlation_id": correlation_id, "error_code": error_code},
            )
        except Exception as publish_exc:
            self.audit_service.record(
                "job.dead_letter.publish_failed",
                status="FAILED",
                summary="Terminal dead-letter publish failed",
                job_id=job.id,
                payload={
                    "correlation_id": correlation_id,
                    "error_code": error_code,
                    "publish_error_type": publish_exc.__class__.__name__,
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
        delay_seconds = max(math.ceil(remaining), 1)
        try:
            self.publisher.publish_retry(job.id, correlation_id, delay_seconds)
        except Exception as publish_exc:
            self.audit_service.record(
                "job.retry.early_reschedule_failed",
                status="FAILED",
                summary="Early retry message could not be rescheduled",
                job_id=job.id,
                payload={
                    "correlation_id": correlation_id,
                    "remaining_seconds": delay_seconds,
                    "publish_error_type": publish_exc.__class__.__name__,
                },
            )
            return True
        self.audit_service.record(
            "job.retry.early_rescheduled",
            status="SUCCEEDED",
            summary="Early retry message rescheduled for its remaining delay",
            job_id=job.id,
            payload={
                "correlation_id": correlation_id,
                "remaining_seconds": delay_seconds,
            },
        )
        return True
