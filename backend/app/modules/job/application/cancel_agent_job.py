from __future__ import annotations

from app.modules.agent.infrastructure.runtime_pool_store import (
    RuntimePoolStore,
    database_now,
    timestamp,
)
from app.modules.job.infrastructure.execution_control import JobExecutionControl
from app.shared.database import Database


def cancel_agent_job(database: Database, job_id: str, user_id: str) -> str:
    """Caller must authorize jobs.manage and the target business scope first."""
    control = JobExecutionControl(database)
    pool = RuntimePoolStore(database)
    with database.unit_of_work():
        job = control.lock_job(job_id)
        invocation = pool.get(f"{job_id}.attempt-{job['retry_count']}", lock=True)
        if (
            invocation is not None
            and invocation["state"] == "TERMINAL"
            and invocation["terminal_code"] == "runtime_invocation_outcome_unknown"
        ):
            return "outcome_unknown"
        if job["status"] in {"SUCCEEDED", "FAILED", "TIMEOUT"} or (
            invocation is not None and invocation["state"] == "TERMINAL"
        ):
            return "already_terminal"
        now = timestamp(database_now(database))
        database.execute(
            """
            update agent_job set cancel_requested_at = coalesce(cancel_requested_at, ?),
              cancel_requested_by = coalesce(cancel_requested_by, ?),
              cancel_reason = coalesce(cancel_reason, 'JOB_CANCELLED') where id = ?
            """,
            (now, user_id, job_id),
        )
        if invocation is not None:
            status = pool.request_cancel(
                invocation["invocation_id"], invocation["request_digest"], "JOB_CANCELLED"
            )
            if status == "cancel_requested":
                return status
        # No accepted SDK exists. Commit the cancellation and dispatch tombstone
        # together so a delayed broker delivery cannot revive the Job.
        database.execute(
            """
            update agent_job set status = 'FAILED', last_error_code = 'runtime_cancelled',
              error_message = '任务已取消', finished_at = ?, worker_lease_until = null,
              locked_by = null, locked_at = null where id = ?
            """,
            (now, job_id),
        )
        database.execute(
            "update job_dispatch_outbox set status = 'DEAD', dead_at = ?, "
            "last_error_code = 'runtime_cancelled', updated_at = ? where job_id = ?",
            (now, now, job_id),
        )
        control.wake_session(job["session_id"])
        return "cancelled"
