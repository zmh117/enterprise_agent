from __future__ import annotations

from app.modules.job.domain.job_status import JobStatus
from app.shared.database import Database
from app.shared.exceptions import NotFound


def require_job_status(database: Database, job_id: str) -> JobStatus:
    row = database.execute_one("select status from agent_job where id = ?", (job_id,))
    if not row:
        raise NotFound(f"Agent job not found: {job_id}")
    return JobStatus(str(row["status"]))
