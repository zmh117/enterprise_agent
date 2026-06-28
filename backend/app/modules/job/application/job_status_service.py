from __future__ import annotations

from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository


class JobStatusService:
    def __init__(self, repository: AgentRepository) -> None:
        self.repository = repository

    def claim(self, job_id: str, worker_id: str) -> AgentJob | None:
        return self.repository.claim_job(job_id, worker_id)

    def succeed(self, job_id: str, result: str) -> AgentJob:
        return self.repository.transition_job(
            job_id=job_id,
            target=JobStatus.SUCCEEDED,
            result=result,
        )

    def fail(self, job_id: str, error_message: str) -> AgentJob:
        return self.repository.transition_job(
            job_id=job_id,
            target=JobStatus.FAILED,
            error_message=error_message,
        )

    def timeout(self, job_id: str, error_message: str) -> AgentJob:
        return self.repository.transition_job(
            job_id=job_id,
            target=JobStatus.TIMEOUT,
            error_message=error_message,
        )
