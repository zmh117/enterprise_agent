from __future__ import annotations

from contextlib import contextmanager
import hashlib
from datetime import timedelta
from typing import Any, Iterator

from app.modules.agent.infrastructure.runtime_pool_store import (
    ADMISSION_SECONDS,
    LEASE_SECONDS,
    RuntimePoolStore,
    database_now,
    timestamp,
)
from app.shared.database import Database


class WorkerLeaseLost(RuntimeError):
    """Observer lost authority. Must not trigger business retries or cancellation."""


class JobExecutionControl:
    def __init__(self, database: Database) -> None:
        self.database = database

    def lock_job(self, job_id: str) -> dict[str, Any]:
        job = self.database.execute_one("select session_id from agent_job where id = ?", (job_id,))
        if job is None:
            raise WorkerLeaseLost("Job no longer exists")
        suffix = " for update" if self.database.engine == "postgres" else ""
        self.database.execute_one(
            "select id from agent_session where id = ?" + suffix,
            (job["session_id"],),
        )
        row = self.database.execute_one("select * from agent_job where id = ?" + suffix, (job_id,))
        if row is None:
            raise WorkerLeaseLost("Job no longer exists")
        return row

    def is_head(self, job: dict[str, Any]) -> bool:
        previous = self.database.execute_one(
            """
            select j.id from agent_job j
            join agent_message m on m.id = j.input_message_id
            join agent_message current_input on current_input.id = ?
            where j.session_id = ? and j.id <> ?
              and (m.sequence_no < current_input.sequence_no
                or (m.sequence_no = current_input.sequence_no and j.id < ?))
              and (j.status in ('WAITING_INPUT','PENDING','RUNNING','RETRY_WAIT') or exists (
                select 1 from agent_runtime_invocation i where i.job_id = j.id
                  and i.accepted_at is not null and i.execution_quiesced_at is null))
            limit 1
            """,
            (job["input_message_id"], job["session_id"], job["id"], job["id"]),
        )
        return previous is None

    def claim(self, job_id: str, worker_id: str) -> bool:
        with self.database.unit_of_work():
            row = self.lock_job(job_id)
            now = database_now(self.database)
            stamp = timestamp(now)
            eligible = (
                row["status"] == "PENDING"
                or (
                    row["status"] == "RETRY_WAIT"
                    and row["next_retry_at"] is not None
                    and row["next_retry_at"] <= stamp
                )
                or (
                    row["status"] == "RUNNING"
                    and row["worker_lease_until"] is not None
                    and row["worker_lease_until"] <= stamp
                )
            )
            if not eligible or not self.is_head(row):
                return False
            self.database.execute(
                """
                update agent_job set status = 'RUNNING', started_at = coalesce(started_at, ?),
                  locked_at = ?, locked_by = ?, worker_claim_version = worker_claim_version + 1,
                  worker_lease_until = ?, next_retry_at = null,
                  admission_deadline_at = coalesce(admission_deadline_at, ?)
                where id = ?
                """,
                (
                    stamp,
                    stamp,
                    worker_id,
                    timestamp(now + timedelta(seconds=LEASE_SECONDS)),
                    timestamp(now + timedelta(seconds=ADMISSION_SECONDS)),
                    job_id,
                ),
            )
            self.database.execute(
                "update job_dispatch_outbox set wait_reason = null where job_id = ?", (job_id,)
            )
            return True

    def require(self, job_id: str, worker_id: str, version: int) -> dict[str, Any]:
        if self.database.current_unit_of_work is None:
            raise RuntimeError("Worker authority must guard a transaction")
        row = self.lock_job(job_id)
        if (
            row["status"] != "RUNNING"
            or row["locked_by"] != worker_id
            or row["worker_claim_version"] != version
            or row["worker_lease_until"] is None
            or row["worker_lease_until"] <= timestamp(database_now(self.database))
        ):
            raise WorkerLeaseLost("Worker control lease lost")
        return row

    @contextmanager
    def transaction(self, job_id: str, worker_id: str, version: int) -> Iterator[None]:
        with self.database.unit_of_work():
            self.require(job_id, worker_id, version)
            yield

    def renew(self, job_id: str, worker_id: str, version: int) -> None:
        with self.transaction(job_id, worker_id, version):
            self.database.execute(
                "update agent_job set worker_lease_until = ? where id = ?",
                (timestamp(database_now(self.database) + timedelta(seconds=LEASE_SECONDS)), job_id),
            )

    def defer(self, job_id: str, worker_id: str, version: int, *, reason: str) -> None:
        with self.transaction(job_id, worker_id, version):
            row = self.lock_job(job_id)
            invocation = RuntimePoolStore(self.database).get(
                f"{job_id}.attempt-{row['retry_count']}",
                lock=True,
            )
            # An accepted attempt remains RUNNING. Only its observer is handed
            # off; a late acceptance of PREPARED still keeps the same identity.
            status = "RUNNING" if invocation and invocation["state"] != "PREPARED" else "PENDING"
            now = database_now(self.database)
            self.database.execute(
                "update agent_job set status = ?, worker_lease_until = ?, locked_by = null "
                "where id = ?",
                (status, timestamp(now), job_id),
            )
            self.rearm(job_id, reason=reason)

    def rearm(self, job_id: str, *, reason: str) -> None:
        now = database_now(self.database)
        self.database.execute(
            """
            update job_dispatch_outbox set status = 'RETRY_WAIT', attempt_count = 0,
              next_attempt_at = ?, wait_reason = ?, claimed_by = '', claimed_at = null, updated_at = ?
            where job_id = ?
            """,
            (
                timestamp(
                    now
                    + timedelta(
                        seconds=1 + int(hashlib.sha256(job_id.encode()).hexdigest()[:8], 16) % 5
                    )
                ),
                reason,
                timestamp(now),
                job_id,
            ),
        )

    def wake_session(self, session_id: str) -> None:
        candidates = self.database.execute(
            "select * from agent_job where session_id = ? and status in ('PENDING','RETRY_WAIT') order by created_at, id limit 100",
            (session_id,),
        )
        for job in candidates:
            if self.is_head(job):
                self.rearm(job["id"], reason="session_ready")
                return

    def reconcile(self, *, limit: int = 100) -> int:
        now = database_now(self.database)
        rows = self.database.execute(
            """
            select j.id from agent_job j join job_dispatch_outbox o on o.job_id = j.id
            where o.status = 'PUBLISHED' and o.updated_at <= ?
              and (j.status in ('PENDING', 'RETRY_WAIT') or
                (j.status = 'RUNNING' and j.worker_lease_until <= ?))
            order by o.updated_at limit ?
            """,
            (timestamp(now - timedelta(seconds=30)), timestamp(now), min(max(limit, 1), 100)),
        )
        count = 0
        for candidate in rows:
            with self.database.unit_of_work():
                job = self.lock_job(candidate["id"])
                if job["status"] == "RUNNING" and (job["worker_lease_until"] or "") > timestamp(
                    database_now(self.database)
                ):
                    continue
                if job["status"] not in {"PENDING", "RETRY_WAIT", "RUNNING"} or not self.is_head(
                    job
                ):
                    continue
                self.rearm(job["id"], reason="observer_recovery")
                count += 1
        return count
