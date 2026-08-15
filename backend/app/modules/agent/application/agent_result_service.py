from __future__ import annotations

import json

from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import AgentRepository


class AgentResultService:
    def __init__(self, repository: AgentRepository) -> None:
        self.repository = repository

    def save_result(self, job: AgentJob, final_answer: str) -> str:
        self.repository.add_message(
            session_id=job.session_id,
            job_id=job.id,
            role="assistant",
            content=final_answer,
        )
        artifact_id = self.repository.add_artifact(
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
        file_results = self.repository.database.execute(
            """
            select commit_id, target_file_id, result_version_id,
                   conflict_candidate_version_id, display_name, status,
                   failure_code
              from file_commit_intent
             where job_id = ?
             order by created_at, id
            """,
            (job.id,),
        )
        if file_results:
            self.repository.add_artifact(
                job_id=job.id,
                artifact_type="file_commit_results",
                name="file-commit-results.json",
                content=json.dumps(
                    {
                        "job_id": job.id,
                        "status": "SUCCEEDED",
                        "files": [
                            {
                                "commit_id": str(row["commit_id"]),
                                "file_id": str(row.get("target_file_id") or ""),
                                "version_id": str(
                                    row.get("result_version_id")
                                    or row.get("conflict_candidate_version_id")
                                    or ""
                                ),
                                "display_name": str(row["display_name"]),
                                "status": str(row["status"]),
                                "error_code": str(row.get("failure_code") or ""),
                            }
                            for row in file_results
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        return artifact_id
