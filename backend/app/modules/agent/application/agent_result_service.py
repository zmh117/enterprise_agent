from __future__ import annotations

from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import AgentRepository


class AgentResultService:
    def __init__(self, repository: AgentRepository) -> None:
        self.repository = repository

    def save_result(self, job: AgentJob, final_answer: str) -> None:
        self.repository.add_message(
            session_id=job.session_id,
            job_id=job.id,
            role="assistant",
            content=final_answer,
        )
        self.repository.add_artifact(
            job_id=job.id,
            artifact_type="report",
            name="diagnostic-report.md",
            content=final_answer,
        )
        self.repository.add_step(
            job_id=job.id,
            step_type="final_answer",
            title="Final report generated",
            content="Evidence-based diagnostic report persisted.",
        )
