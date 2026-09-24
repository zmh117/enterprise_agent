from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.job.domain.job_dispatch import JobDispatchEvent, JobDispatchStatus
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class JobDispatchRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_dispatch_event(
        self,
        *,
        job_id: str,
        job_idempotency_key: str,
        correlation_id: str,
        max_attempts: int = 8,
        max_replay_count: int = 3,
    ) -> JobDispatchEvent:
        timestamp = now_iso()
        event_id = new_id("job_dispatch")
        self.database.execute(
            """
            insert into job_dispatch_outbox
              (id, event_key, idempotency_key, job_id, correlation_id,
               status, attempt_count, max_attempts, replay_count,
               max_replay_count, next_attempt_at,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, 'PENDING', 0, ?, 0, ?, ?, ?, ?)
            on conflict(job_id) do nothing
            """,
            (
                event_id,
                f"job.dispatch:{job_id}",
                f"job.dispatch:{job_idempotency_key}",
                job_id,
                correlation_id,
                max(1, int(max_attempts)),
                max(0, int(max_replay_count)),
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        row = self.database.execute_one(
            "select * from job_dispatch_outbox where job_id = ?",
            (job_id,),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "Job dispatch event could not be persisted",
                safe_message="任务调度事件保存失败",
                error_code="job_dispatch_persistence_failed",
            )
        return self._dispatch_event_from_row(row)

    def abandon_pending_dispatch(self, job_id: str, *, reason_code: str) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            update job_dispatch_outbox
               set status = 'DEAD',
                   last_error_code = ?,
                   last_error_summary = 'Job ended without model execution',
                   dead_at = coalesce(dead_at, ?),
                   claimed_by = '',
                   claimed_at = null,
                   updated_at = ?
             where job_id = ?
               and status in ('PENDING', 'RETRY_WAIT', 'RUNNING')
            """,
            (reason_code[:80], timestamp, timestamp, job_id),
        )

    def get_dispatch_event_for_job(self, job_id: str) -> JobDispatchEvent | None:
        row = self.database.execute_one(
            "select * from job_dispatch_outbox where job_id = ?",
            (job_id,),
        )
        return self._dispatch_event_from_row(row) if row else None

    def get_dispatch_event(self, event_id: str) -> JobDispatchEvent:
        row = self.database.execute_one(
            "select * from job_dispatch_outbox where id = ?",
            (event_id,),
        )
        if row is None:
            raise NotFound(f"Job dispatch event not found: {event_id}")
        return self._dispatch_event_from_row(row)

    def claim_dispatch_event(
        self,
        *,
        worker_id: str,
        now: str | None = None,
    ) -> JobDispatchEvent | None:
        timestamp = now or now_iso()
        with self.database.unit_of_work():
            if self.database.engine == "postgres":
                rows = self.database.execute(
                    """
                    with candidate as (
                      select outbox.id
                        from job_dispatch_outbox outbox
                        join agent_job job on job.id = outbox.job_id
                       where outbox.status in ('PENDING', 'RETRY_WAIT')
                         and outbox.next_attempt_at <= ?
                         and outbox.attempt_count < outbox.max_attempts
                         and job.status in ('PENDING', 'RETRY_WAIT')
                       order by outbox.next_attempt_at, outbox.created_at, outbox.id
                       for update of outbox skip locked
                       limit 1
                    )
                    update job_dispatch_outbox
                       set status = 'RUNNING', claimed_by = ?, claimed_at = ?,
                           attempt_count = attempt_count + 1, updated_at = ?
                     where id = (select id from candidate)
                    returning *
                    """,
                    (timestamp, worker_id, timestamp, timestamp),
                )
            else:
                rows = self.database.execute(
                    """
                    update job_dispatch_outbox
                       set status = 'RUNNING', claimed_by = ?, claimed_at = ?,
                           attempt_count = attempt_count + 1, updated_at = ?
                     where id = (
                       select outbox.id
                         from job_dispatch_outbox outbox
                         join agent_job job on job.id = outbox.job_id
                        where outbox.status in ('PENDING', 'RETRY_WAIT')
                          and outbox.next_attempt_at <= ?
                          and outbox.attempt_count < outbox.max_attempts
                          and job.status in ('PENDING', 'RETRY_WAIT')
                        order by outbox.next_attempt_at, outbox.created_at, outbox.id
                        limit 1
                     )
                       and status in ('PENDING', 'RETRY_WAIT')
                    returning *
                    """,
                    (worker_id, timestamp, timestamp, timestamp),
                )
        return self._dispatch_event_from_row(rows[0]) if rows else None

    def mark_dispatch_published(self, *, event_id: str, worker_id: str) -> bool:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = 'PUBLISHED', published_at = ?, claimed_by = '',
                       claimed_at = null, last_error_code = '',
                       last_error_summary = '', updated_at = ?
                 where id = ? and status = 'RUNNING' and claimed_by = ?
                returning id
                """,
                (timestamp, timestamp, event_id, worker_id),
            )
        return bool(rows)

    def mark_dispatch_failed(
        self,
        *,
        event_id: str,
        worker_id: str,
        error_code: str,
        error_summary: str,
        retry_base_seconds: int,
    ) -> JobDispatchEvent:
        with self.database.unit_of_work():
            current = self.database.execute_one(
                """
                select * from job_dispatch_outbox
                 where id = ? and status = 'RUNNING' and claimed_by = ?
                """,
                (event_id, worker_id),
            )
            if current is None:
                raise NonRetryableExecutionError(
                    "Job dispatch claim ownership was lost",
                    safe_message="任务调度事件领取权已失效",
                    error_code="job_dispatch_claim_lost",
                )
            attempt_count = int(current["attempt_count"])
            max_attempts = int(current["max_attempts"])
            dead = attempt_count >= max_attempts
            delay_seconds = min(
                max(1, int(retry_base_seconds)) * (2 ** max(attempt_count - 1, 0)),
                3600,
            )
            timestamp = now_iso()
            next_attempt_at = (
                timestamp
                if dead
                else (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
            )
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = ?, next_attempt_at = ?, claimed_by = '',
                       claimed_at = null, dead_at = ?, last_error_code = ?,
                       last_error_summary = ?, updated_at = ?
                 where id = ? and status = 'RUNNING' and claimed_by = ?
                returning *
                """,
                (
                    JobDispatchStatus.DEAD.value if dead else JobDispatchStatus.RETRY_WAIT.value,
                    next_attempt_at,
                    timestamp if dead else None,
                    error_code[:100],
                    error_summary[:500],
                    timestamp,
                    event_id,
                    worker_id,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Job dispatch failure state could not be saved",
                    safe_message="任务调度失败状态保存失败",
                    error_code="job_dispatch_claim_lost",
                )
        return self._dispatch_event_from_row(rows[0])

    def rearm_dispatch_for_retry(
        self,
        *,
        job_id: str,
        next_attempt_at: str,
    ) -> JobDispatchEvent:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update job_dispatch_outbox
               set status = 'RETRY_WAIT', attempt_count = 0,
                   next_attempt_at = ?, claimed_by = '', claimed_at = null,
                   published_at = null, dead_at = null,
                   last_error_code = '', last_error_summary = '', updated_at = ?
             where job_id = ?
               and status in ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PUBLISHED')
            returning *
            """,
            (next_attempt_at, timestamp, job_id),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Job dispatch event is not eligible for retry rearming",
                safe_message="任务调度事件当前状态不允许安排执行重试",
                error_code="job_dispatch_retry_rearm_conflict",
            )
        return self._dispatch_event_from_row(rows[0])

    def rearm_dispatch_for_cutover(
        self,
        *,
        job_id: str,
        target_status: JobDispatchStatus,
        next_attempt_at: str,
    ) -> JobDispatchEvent:
        if target_status not in {
            JobDispatchStatus.PENDING,
            JobDispatchStatus.RETRY_WAIT,
        }:
            raise ValueError("Cutover target must be PENDING or RETRY_WAIT")
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update job_dispatch_outbox
               set status = ?, attempt_count = 0,
                   next_attempt_at = ?, claimed_by = '', claimed_at = null,
                   published_at = null, dead_at = null,
                   last_error_code = '', last_error_summary = '', updated_at = ?
             where job_id = ?
               and status in ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PUBLISHED')
            returning *
            """,
            (target_status.value, next_attempt_at, timestamp, job_id),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Job dispatch event cannot be converted from its current state",
                safe_message="任务调度事件当前状态无法安全切换",
                error_code="job_dispatch_cutover_state_conflict",
            )
        return self._dispatch_event_from_row(rows[0])

    def record_dispatch_cutover_quarantine(
        self,
        *,
        source_queue: str,
        message_digest: str,
        reason_code: str,
        actor_id: str,
        job_id: str = "",
    ) -> bool:
        rows = self.database.execute(
            """
            insert into job_dispatch_cutover_quarantine
              (id, source_queue, message_digest, job_id, reason_code,
               observed_at, observed_by)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(source_queue, message_digest) do nothing
            returning id
            """,
            (
                new_id("job_dispatch_quarantine"),
                source_queue,
                message_digest,
                job_id or None,
                reason_code,
                now_iso(),
                actor_id[:200],
            ),
        )
        return bool(rows)

    def dispatch_cutover_quarantine_count(self) -> int:
        row = self.database.execute_one(
            "select count(*) as count from job_dispatch_cutover_quarantine"
        )
        return int(row["count"]) if row else 0

    def recover_stale_dispatch_claims(
        self,
        *,
        stale_before: str,
    ) -> tuple[int, int]:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = case
                         when attempt_count >= max_attempts then 'DEAD'
                         else 'RETRY_WAIT'
                       end,
                       next_attempt_at = ?,
                       claimed_by = '',
                       claimed_at = null,
                       dead_at = case
                         when attempt_count >= max_attempts then ?
                         else dead_at
                       end,
                       last_error_code = 'job_dispatch_claim_expired',
                       last_error_summary = 'Dispatcher claim expired before completion',
                       updated_at = ?
                 where status = 'RUNNING' and claimed_at <= ?
                returning status
                """,
                (timestamp, timestamp, timestamp, stale_before),
            )
        return (
            sum(row["status"] == JobDispatchStatus.RETRY_WAIT.value for row in rows),
            sum(row["status"] == JobDispatchStatus.DEAD.value for row in rows),
        )

    def expire_terminal_job_dispatches(self) -> int:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = 'DEAD', dead_at = ?,
                       last_error_code = 'job_not_dispatchable',
                       last_error_summary = 'Job reached a terminal state before dispatch',
                       updated_at = ?
                 where status in ('PENDING', 'RETRY_WAIT')
                   and exists (
                     select 1 from agent_job
                      where agent_job.id = job_dispatch_outbox.job_id
                        and agent_job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT', 'CANCELLED')
                   )
                returning id
                """,
                (timestamp, timestamp),
            )
        return len(rows)

    def replay_dead_dispatch(
        self,
        *,
        event_id: str,
        actor_id: str,
    ) -> JobDispatchEvent:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update job_dispatch_outbox
               set status = 'PENDING', attempt_count = 0,
                   replay_count = replay_count + 1,
                   next_attempt_at = ?, claimed_by = '', claimed_at = null,
                   published_at = null, dead_at = null,
                   last_replayed_at = ?, last_replayed_by = ?,
                   last_error_code = '', last_error_summary = '', updated_at = ?
             where id = ? and status = 'DEAD'
               and replay_count < max_replay_count
               and exists (
                 select 1 from agent_job
                  where agent_job.id = job_dispatch_outbox.job_id
                    and agent_job.status = 'PENDING'
               )
            returning *
            """,
            (timestamp, timestamp, actor_id[:200], timestamp, event_id),
        )
        if rows:
            return self._dispatch_event_from_row(rows[0])
        current = self.get_dispatch_event(event_id)
        if current.status != JobDispatchStatus.DEAD:
            raise NonRetryableExecutionError(
                "Only DEAD dispatch events can be replayed",
                safe_message="只有 DEAD 调度事件可以重放",
                error_code="job_dispatch_replay_status_invalid",
            )
        if current.replay_count >= current.max_replay_count:
            raise NonRetryableExecutionError(
                "Job dispatch replay limit is exhausted",
                safe_message="任务调度事件已达到允许的重放次数上限",
                error_code="job_dispatch_replay_limit_exhausted",
            )
        job_status = self._job_status(current.job_id)
        raise NonRetryableExecutionError(
            f"Job is not dispatchable in status {job_status.value}",
            safe_message="任务当前状态不允许重新调度",
            error_code="job_dispatch_replay_job_not_pending",
        )

    def _job_status(self, job_id: str) -> JobStatus:
        row = self.database.execute_one("select status from agent_job where id = ?", (job_id,))
        if not row:
            raise NotFound(f"Agent job not found: {job_id}")
        return JobStatus(str(row["status"]))

    def dispatch_metrics(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in JobDispatchStatus}
        for row in self.database.execute(
            """
            select status, count(*) as count
              from job_dispatch_outbox
             group by status
            """
        ):
            counts[str(row["status"])] = int(row["count"])
        oldest = (
            self.database.execute_one(
                """
            select min(next_attempt_at) as oldest_due_at,
                   max(attempt_count) as max_attempt_count
              from job_dispatch_outbox
             where status in ('PENDING', 'RETRY_WAIT', 'RUNNING')
            """
            )
            or {}
        )
        return {
            "counts": counts,
            "oldest_due_at": oldest.get("oldest_due_at"),
            "max_attempt_count": int(oldest.get("max_attempt_count") or 0),
        }

    def _dispatch_event_from_row(self, row: dict[str, Any]) -> JobDispatchEvent:
        return JobDispatchEvent(
            id=str(row["id"]),
            event_key=str(row["event_key"]),
            idempotency_key=str(row["idempotency_key"]),
            job_id=str(row["job_id"]),
            correlation_id=str(row["correlation_id"]),
            status=JobDispatchStatus(str(row["status"])),
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            replay_count=int(row["replay_count"]),
            max_replay_count=int(row["max_replay_count"]),
            next_attempt_at=str(row["next_attempt_at"]),
            claimed_by=str(row.get("claimed_by") or ""),
            claimed_at=row.get("claimed_at"),
            published_at=row.get("published_at"),
            dead_at=row.get("dead_at"),
            last_replayed_at=row.get("last_replayed_at"),
            last_replayed_by=str(row.get("last_replayed_by") or ""),
            last_error_code=str(row.get("last_error_code") or ""),
            last_error_summary=str(row.get("last_error_summary") or ""),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
