from __future__ import annotations

from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.shared.config import QueueSettings
from app.shared.exceptions import (
    ExecutionTimeout,
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
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.queue_settings = queue_settings

    def is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, (PermissionDenied, ToolPolicyError, NonRetryableExecutionError)):
            return False
        return isinstance(
            exc, (RetryableExecutionError, ExecutionTimeout, TimeoutError, ConnectionError)
        )

    def handle_failure(self, job: AgentJob, exc: Exception, correlation_id: str) -> str:
        safe_message = getattr(exc, "safe_message", str(exc))
        if self.is_retryable(exc) and job.retry_count < job.max_retry_count:
            self.repository.increment_retry(job.id, safe_message)
            self.publisher.publish_retry(
                job.id,
                correlation_id,
                self.queue_settings.retry_delay_seconds,
            )
            return "retry"
        self.repository.transition_job(
            job_id=job.id,
            target=JobStatus.FAILED,
            error_message=safe_message,
        )
        self.publisher.publish_dead_letter(job.id, correlation_id, safe_message)
        return "dead"
