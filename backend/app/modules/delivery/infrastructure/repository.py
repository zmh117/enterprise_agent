from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.delivery.domain import DeliveryEvent, DeliveryStatus
from app.modules.job.infrastructure.job_status_lookup import require_job_status
from app.modules.job.infrastructure.persistence_values import json_from_text, new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class DeliveryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_system_notice_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        row = self.database.execute_one(
            "select * from delivery_outbox where event_key = ?",
            (f"delivery.system_notice:{idempotency_key}",),
        )
        return dict(row) if row is not None else None

    def create_system_notice_event(
        self,
        *,
        idempotency_key: str,
        session_id: str,
        application_publication_id: str,
        delivery_binding: dict[str, Any],
        target_summary: dict[str, Any],
        correlation_id: str,
        max_attempts: int,
        max_replay_count: int,
        principal_user_id: str = "",
        agent_publication_id: str = "",
    ) -> DeliveryEvent:
        timestamp = now_iso()
        event_key = f"delivery.system_notice:{idempotency_key}"
        existing = self.database.execute_one(
            "select * from delivery_outbox where event_key = ?",
            (event_key,),
        )
        if existing is not None:
            return self._delivery_event_from_row(existing)
        event_id = new_id("delivery_outbox")
        self.database.execute(
            """
            insert into delivery_outbox
              (id, event_key, job_id, result_artifact_id,
               application_publication_id, delivery_binding_json,
               target_summary, correlation_id, status, attempt_count,
               max_attempts, replay_count, max_replay_count,
               next_attempt_at, created_at, updated_at,
               delivery_kind, session_id, principal_user_id, agent_publication_id)
            values (?, ?, null, null, ?, ?, ?, ?, 'PENDING', 0, ?, 0, ?, ?, ?, ?,
                    'SYSTEM_NOTICE', ?, ?, ?)
            on conflict(event_key) do nothing
            """,
            (
                event_id,
                event_key,
                application_publication_id,
                json.dumps(delivery_binding, ensure_ascii=False, sort_keys=True),
                json.dumps(target_summary, ensure_ascii=False, sort_keys=True),
                correlation_id,
                max(1, int(max_attempts)),
                max(0, int(max_replay_count)),
                timestamp,
                timestamp,
                timestamp,
                session_id,
                principal_user_id,
                agent_publication_id,
            ),
        )
        row = self.database.execute_one(
            "select * from delivery_outbox where event_key = ?",
            (event_key,),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "System notice delivery event could not be persisted",
                safe_message="系统说明保存失败",
                error_code="delivery_outbox_persistence_failed",
            )
        return self._delivery_event_from_row(row)

    def create_delivery_event(
        self,
        *,
        job_id: str,
        result_artifact_id: str,
        application_publication_id: str,
        delivery_binding: dict[str, Any],
        target_summary: dict[str, Any],
        correlation_id: str,
        max_attempts: int,
        max_replay_count: int,
    ) -> DeliveryEvent:
        if self._artifact_job_id(result_artifact_id) != job_id:
            raise NonRetryableExecutionError(
                "Delivery artifact does not belong to the Job",
                safe_message="投递结果产物与任务不匹配",
                error_code="delivery_artifact_job_mismatch",
            )
        timestamp = now_iso()
        event_id = new_id("delivery_outbox")
        self.database.execute(
            """
            insert into delivery_outbox
              (id, event_key, job_id, result_artifact_id,
               application_publication_id, delivery_binding_json,
               target_summary, correlation_id, status, attempt_count,
               max_attempts, replay_count, max_replay_count,
               next_attempt_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, 0, ?, ?, ?, ?)
            on conflict(job_id, result_artifact_id) do nothing
            """,
            (
                event_id,
                f"delivery.result:{result_artifact_id}",
                job_id,
                result_artifact_id,
                application_publication_id,
                json.dumps(delivery_binding, ensure_ascii=False, sort_keys=True),
                json.dumps(target_summary, ensure_ascii=False, sort_keys=True),
                correlation_id,
                max(1, int(max_attempts)),
                max(0, int(max_replay_count)),
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        row = self.database.execute_one(
            """
            select * from delivery_outbox
             where job_id = ? and result_artifact_id = ?
            """,
            (job_id, result_artifact_id),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "Delivery event could not be persisted",
                safe_message="投递事件保存失败",
                error_code="delivery_outbox_persistence_failed",
            )
        return self._delivery_event_from_row(row)

    def get_delivery_event(self, delivery_id: str) -> DeliveryEvent:
        row = self.database.execute_one(
            "select * from delivery_outbox where id = ?",
            (delivery_id,),
        )
        if row is None:
            raise NotFound(f"Delivery event not found: {delivery_id}")
        return self._delivery_event_from_row(row)

    def get_delivery_event_for_job(self, job_id: str) -> DeliveryEvent | None:
        row = self.database.execute_one(
            """
            select * from delivery_outbox
             where job_id = ?
             order by created_at desc, id desc
             limit 1
            """,
            (job_id,),
        )
        return self._delivery_event_from_row(row) if row else None

    def list_delivery_events(self, job_id: str) -> list[dict[str, Any]]:
        """Return the safe, read-only Delivery lifecycle for a Job.

        The frozen binding and artifact body are deliberately not returned.
        Only the adapter identity and already-redacted target summary cross the
        API boundary.
        """
        require_job_status(self.database, job_id)
        rows = self.database.execute(
            """
            select id, job_id, result_artifact_id,
                   application_publication_id, delivery_binding_json,
                   target_summary, correlation_id, status,
                   attempt_count, max_attempts, replay_count, max_replay_count,
                   next_attempt_at, last_error_code, last_error_summary,
                   started_at, finished_at, dead_at,
                   last_replayed_at, created_at, updated_at
              from delivery_outbox
             where job_id = ?
             order by created_at, id
            """,
            (job_id,),
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            binding = json_from_text(str(row.pop("delivery_binding_json", "{}") or "{}"))
            if not isinstance(binding, dict):
                binding = {}
            target_summary = json_from_text(str(row.get("target_summary") or "{}"))
            events.append(
                {
                    **row,
                    "route_type": str(binding.get("route_type") or "none"),
                    "connector_id": str(binding.get("connector_id") or ""),
                    "delivery_kind": str(binding.get("delivery_kind") or "result"),
                    "target_summary": (target_summary if isinstance(target_summary, dict) else {}),
                    "terminal": str(row["status"]) in {"SUCCEEDED", "FAILED", "DEAD", "SKIPPED"},
                    "delivered": str(row["status"]) == "SUCCEEDED",
                }
            )
        return events

    def delivery_metrics(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in DeliveryStatus}
        for row in self.database.execute(
            """
            select status, count(*) as count
              from delivery_outbox
             group by status
            """
        ):
            counts[str(row["status"])] = int(row["count"])
        active = (
            self.database.execute_one(
                """
            select min(next_attempt_at) as oldest_due_at,
                   max(attempt_count) as max_attempt_count
              from delivery_outbox
             where status in ('PENDING', 'RETRY_WAIT', 'RUNNING')
            """
            )
            or {}
        )
        return {
            "counts": counts,
            "active_count": sum(counts[status] for status in ("PENDING", "RETRY_WAIT", "RUNNING")),
            "terminal_failure_count": counts["FAILED"] + counts["DEAD"],
            "oldest_due_at": active.get("oldest_due_at"),
            "max_attempt_count": int(active.get("max_attempt_count") or 0),
        }

    def replay_dead_delivery(
        self,
        *,
        delivery_id: str,
        actor_id: str,
    ) -> DeliveryEvent:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update delivery_outbox
               set status = 'PENDING',
                   attempt_count = 0,
                   replay_count = replay_count + 1,
                   next_attempt_at = ?,
                   claimed_by = '',
                   claim_token = '',
                   claimed_at = null,
                   claim_expires_at = null,
                   last_error_code = '',
                   last_error_summary = '',
                   started_at = null,
                   finished_at = null,
                   dead_at = null,
                   last_replayed_at = ?,
                   last_replayed_by = ?,
                   updated_at = ?
             where id = ?
               and status = 'DEAD'
               and replay_count < max_replay_count
               and exists (
                 select 1
                   from agent_job
                  where agent_job.id = delivery_outbox.job_id
                    and agent_job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
               )
            returning *
            """,
            (
                timestamp,
                timestamp,
                actor_id[:200],
                timestamp,
                delivery_id,
            ),
        )
        if rows:
            return self._delivery_event_from_row(rows[0])
        current = self.get_delivery_event(delivery_id)
        if current.status != DeliveryStatus.DEAD:
            raise NonRetryableExecutionError(
                "Only DEAD Delivery events can be replayed",
                safe_message="只有 DEAD 投递事件可以重放",
                error_code="delivery_replay_status_invalid",
            )
        if current.replay_count >= current.max_replay_count:
            raise NonRetryableExecutionError(
                "Delivery replay limit is exhausted",
                safe_message="投递事件已达到允许的重放次数上限",
                error_code="delivery_replay_limit_exhausted",
            )
        job_status = require_job_status(self.database, current.job_id)
        raise NonRetryableExecutionError(
            f"Job is not terminal in status {job_status.value}",
            safe_message="任务尚未结束，不能重放投递",
            error_code="delivery_replay_job_not_terminal",
        )

    def claim_delivery_event(
        self,
        *,
        worker_id: str,
        claim_timeout_seconds: int,
        now: str | None = None,
    ) -> DeliveryEvent | None:
        timestamp = now or now_iso()
        now_value = datetime.fromisoformat(timestamp)
        if now_value.tzinfo is None:
            now_value = now_value.replace(tzinfo=UTC)
        claim_expires_at = (
            now_value + timedelta(seconds=max(1, int(claim_timeout_seconds)))
        ).isoformat()
        claim_token = new_id("delivery_claim")
        with self.database.unit_of_work():
            if self.database.engine == "postgres":
                rows = self.database.execute(
                    """
                    with candidate as (
                      select outbox.id
                        from delivery_outbox outbox
                        left join agent_job job on job.id = outbox.job_id
                       where outbox.status in ('PENDING', 'RETRY_WAIT')
                         and outbox.next_attempt_at <= ?
                         and outbox.attempt_count < outbox.max_attempts
                         and (
                           outbox.delivery_kind = 'SYSTEM_NOTICE'
                           or job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
                         )
                       order by outbox.next_attempt_at,
                                outbox.created_at,
                                outbox.id
                       for update of outbox skip locked
                       limit 1
                    )
                    update delivery_outbox
                       set status = 'RUNNING',
                           claimed_by = ?,
                           claim_token = ?,
                           claimed_at = ?,
                           claim_expires_at = ?,
                           started_at = coalesce(started_at, ?),
                           attempt_count = attempt_count + 1,
                           updated_at = ?
                     where id = (select id from candidate)
                    returning *
                    """,
                    (
                        timestamp,
                        worker_id,
                        claim_token,
                        timestamp,
                        claim_expires_at,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                rows = self.database.execute(
                    """
                    update delivery_outbox
                       set status = 'RUNNING',
                           claimed_by = ?,
                           claim_token = ?,
                           claimed_at = ?,
                           claim_expires_at = ?,
                           started_at = coalesce(started_at, ?),
                           attempt_count = attempt_count + 1,
                           updated_at = ?
                     where id = (
                       select outbox.id
                         from delivery_outbox outbox
                         left join agent_job job on job.id = outbox.job_id
                        where outbox.status in ('PENDING', 'RETRY_WAIT')
                          and outbox.next_attempt_at <= ?
                          and outbox.attempt_count < outbox.max_attempts
                          and (
                            outbox.delivery_kind = 'SYSTEM_NOTICE'
                            or job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
                          )
                        order by outbox.next_attempt_at,
                                 outbox.created_at,
                                 outbox.id
                        limit 1
                     )
                       and status in ('PENDING', 'RETRY_WAIT')
                    returning *
                    """,
                    (
                        worker_id,
                        claim_token,
                        timestamp,
                        claim_expires_at,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
        return self._delivery_event_from_row(rows[0]) if rows else None

    def create_delivery_attempt(
        self,
        *,
        event: DeliveryEvent,
    ) -> dict[str, Any]:
        attempt_id = new_id("delivery")
        idempotency_key = f"delivery.attempt:{event.id}:{event.replay_count}:{event.attempt_count}"
        timestamp = now_iso()
        file_binding = (
            self.database.execute_one(
                "select file_id, file_version_id from delivery_outbox where id = ?",
                (event.id,),
            )
            or {}
        )
        self.database.execute(
            """
            insert into delivery_attempt
              (id, job_id, route_type, connector_id, target_summary,
               status, error_message, created_at, finished_at,
               delivery_outbox_id, replay_no, attempt_no, correlation_id,
               idempotency_key, error_code, file_id, file_version_id)
            values (?, ?, ?, ?, ?, 'RUNNING', null, ?, null, ?, ?, ?, ?, ?, '', ?, ?)
            on conflict(idempotency_key) do nothing
            """,
            (
                attempt_id,
                event.job_id or None,
                str(event.delivery_binding.get("route_type") or "none"),
                str(event.delivery_binding.get("connector_id") or ""),
                json.dumps(
                    event.target_summary,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
                event.id,
                event.replay_count,
                event.attempt_count,
                event.correlation_id,
                idempotency_key,
                str(file_binding.get("file_id") or ""),
                str(file_binding.get("file_version_id") or ""),
            ),
        )
        row = self.database.execute_one(
            """
            select * from delivery_attempt
             where idempotency_key = ?
            """,
            (idempotency_key,),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "Delivery attempt could not be persisted",
                safe_message="投递尝试保存失败",
                error_code="delivery_attempt_persistence_failed",
            )
        return row

    def has_successful_delivery_chunk(
        self,
        *,
        delivery_id: str,
        chunk_index: int,
        payload_hash: str,
    ) -> bool:
        row = self.database.execute_one(
            """
            select payload_hash
              from delivery_chunk
             where delivery_outbox_id = ?
               and chunk_index = ?
               and status = 'SUCCEEDED'
            """,
            (delivery_id, chunk_index),
        )
        if row is None:
            return False
        if str(row["payload_hash"]) != payload_hash:
            raise NonRetryableExecutionError(
                "Successful Delivery chunk payload hash changed",
                safe_message="投递分片内容与已成功记录不一致",
                error_code="delivery_chunk_payload_drift",
            )
        return True

    def record_delivery_chunk(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
        chunk_index: int,
        chunk_count: int,
        payload_hash: str,
        payload_summary: dict[str, Any],
        status: str,
        error_message: str = "",
    ) -> str:
        existing = self.database.execute_one(
            """
            select id from delivery_chunk
             where delivery_outbox_id = ?
               and replay_no = ?
               and attempt_no = ?
               and chunk_index = ?
            """,
            (
                event.id,
                event.replay_count,
                event.attempt_count,
                chunk_index,
            ),
        )
        sent_at = now_iso() if status == "SUCCEEDED" else None
        if existing is not None:
            self.database.execute(
                """
                update delivery_chunk
                   set status = ?, payload_summary = ?, error_message = ?,
                       payload_hash = ?, sent_at = ?
                 where id = ?
                """,
                (
                    status,
                    json.dumps(
                        payload_summary,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    error_message or None,
                    payload_hash,
                    sent_at,
                    str(existing["id"]),
                ),
            )
            return str(existing["id"])
        chunk_id = new_id("chunk")
        self.database.execute(
            """
            insert into delivery_chunk
              (id, attempt_id, chunk_index, chunk_count, status,
               payload_summary, error_message, created_at,
               delivery_outbox_id, replay_no, attempt_no, idempotency_key,
               payload_hash, sent_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                attempt_id,
                chunk_index,
                chunk_count,
                status,
                json.dumps(
                    payload_summary,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                error_message or None,
                now_iso(),
                event.id,
                event.replay_count,
                event.attempt_count,
                f"delivery.chunk:{event.id}:{chunk_index}:{payload_hash}",
                payload_hash,
                sent_at,
            ),
        )
        return chunk_id

    def mark_delivery_succeeded(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
    ) -> DeliveryEvent:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = 'SUCCEEDED',
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       last_error_code = '',
                       last_error_summary = '',
                       finished_at = ?,
                       updated_at = ?
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                returning *
                """,
                (
                    timestamp,
                    timestamp,
                    event.id,
                    event.claimed_by,
                    event.claim_token,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Delivery claim ownership was lost",
                    safe_message="投递事件领取权已失效",
                    error_code="delivery_claim_lost",
                )
            self.database.execute(
                """
                update delivery_attempt
                   set status = 'SUCCEEDED', error_code = '',
                       error_message = null, finished_at = ?
                 where id = ? and delivery_outbox_id = ?
                """,
                (timestamp, attempt_id, event.id),
            )
        return self._delivery_event_from_row(rows[0])

    def mark_delivery_skipped(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
    ) -> DeliveryEvent:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = 'SKIPPED',
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       finished_at = ?,
                       updated_at = ?
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                returning *
                """,
                (
                    timestamp,
                    timestamp,
                    event.id,
                    event.claimed_by,
                    event.claim_token,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Delivery claim ownership was lost",
                    safe_message="投递事件领取权已失效",
                    error_code="delivery_claim_lost",
                )
            self.database.execute(
                """
                update delivery_attempt
                   set status = 'SKIPPED', finished_at = ?
                 where id = ? and delivery_outbox_id = ?
                """,
                (timestamp, attempt_id, event.id),
            )
        return self._delivery_event_from_row(rows[0])

    def mark_delivery_failed(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
        retryable: bool,
        error_code: str,
        error_summary: str,
        retry_base_seconds: int,
    ) -> DeliveryEvent:
        with self.database.unit_of_work():
            current = self.database.execute_one(
                """
                select * from delivery_outbox
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                """,
                (event.id, event.claimed_by, event.claim_token),
            )
            if current is None:
                raise NonRetryableExecutionError(
                    "Delivery claim ownership was lost",
                    safe_message="投递事件领取权已失效",
                    error_code="delivery_claim_lost",
                )
            attempt_count = int(current["attempt_count"])
            max_attempts = int(current["max_attempts"])
            exhausted = retryable and attempt_count >= max_attempts
            if not retryable:
                target = DeliveryStatus.FAILED
            elif exhausted:
                target = DeliveryStatus.DEAD
            else:
                target = DeliveryStatus.RETRY_WAIT
            timestamp = now_iso()
            delay_seconds = min(
                max(1, int(retry_base_seconds)) * (2 ** max(attempt_count - 1, 0)),
                3600,
            )
            next_attempt_at = (
                timestamp
                if target.terminal
                else (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
            )
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = ?,
                       next_attempt_at = ?,
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       last_error_code = ?,
                       last_error_summary = ?,
                       finished_at = ?,
                       dead_at = ?,
                       updated_at = ?
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                returning *
                """,
                (
                    target.value,
                    next_attempt_at,
                    error_code[:100],
                    error_summary[:500],
                    timestamp if target.terminal else None,
                    timestamp if target == DeliveryStatus.DEAD else None,
                    timestamp,
                    event.id,
                    event.claimed_by,
                    event.claim_token,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Delivery failure state could not be saved",
                    safe_message="投递失败状态保存失败",
                    error_code="delivery_claim_lost",
                )
            self.database.execute(
                """
                update delivery_attempt
                   set status = 'FAILED', error_code = ?,
                       error_message = ?, finished_at = ?
                 where id = ? and delivery_outbox_id = ?
                """,
                (
                    error_code[:100],
                    error_summary[:500],
                    timestamp,
                    attempt_id,
                    event.id,
                ),
            )
        return self._delivery_event_from_row(rows[0])

    def recover_stale_delivery_claims(self, *, now: str | None = None) -> tuple[int, int]:
        timestamp = now or now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = case
                         when attempt_count >= max_attempts then 'DEAD'
                         else 'RETRY_WAIT'
                       end,
                       next_attempt_at = ?,
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       last_error_code = 'delivery_claim_expired',
                       last_error_summary =
                         'Delivery Dispatcher claim expired before completion',
                       finished_at = case
                         when attempt_count >= max_attempts then ?
                         else null
                       end,
                       dead_at = case
                         when attempt_count >= max_attempts then ?
                         else dead_at
                       end,
                       updated_at = ?
                 where status = 'RUNNING'
                   and claim_expires_at is not null
                   and claim_expires_at <= ?
                returning id, status
                """,
                (
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            for row in rows:
                self.database.execute(
                    """
                    update delivery_attempt
                       set status = 'FAILED',
                           error_code = 'delivery_claim_expired',
                           error_message =
                             'Delivery Dispatcher claim expired before completion',
                           finished_at = ?
                     where delivery_outbox_id = ? and status = 'RUNNING'
                    """,
                    (timestamp, str(row["id"])),
                )
        return (
            sum(row["status"] == DeliveryStatus.RETRY_WAIT.value for row in rows),
            sum(row["status"] == DeliveryStatus.DEAD.value for row in rows),
        )

    def list_delivery_attempts(self, job_id: str) -> list[dict[str, Any]]:
        require_job_status(self.database, job_id)
        rows = self.database.execute(
            """
            select id, job_id, route_type, connector_id, target_summary, status,
                   error_message, created_at, finished_at,
                   delivery_outbox_id, replay_no, attempt_no, correlation_id,
                   idempotency_key, error_code
            from delivery_attempt
            where job_id = ?
            order by created_at, id
            """,
            (job_id,),
        )
        return [
            {
                **row,
                "target_summary": json_from_text(row.get("target_summary") or "{}"),
            }
            for row in rows
        ]

    def list_delivery_chunks(self, job_id: str) -> list[dict[str, Any]]:
        require_job_status(self.database, job_id)
        rows = self.database.execute(
            """
            select c.id, c.attempt_id, a.job_id, c.chunk_index, c.chunk_count, c.status,
                   c.payload_summary, c.error_message, c.created_at,
                   c.delivery_outbox_id, c.replay_no, c.attempt_no, c.idempotency_key,
                   c.payload_hash, c.sent_at
            from delivery_chunk c
            join delivery_attempt a on a.id = c.attempt_id
            where a.job_id = ?
            order by c.created_at, c.chunk_index, c.id
            """,
            (job_id,),
        )
        return [
            {
                **row,
                "payload_summary": json_from_text(row.get("payload_summary") or "{}"),
            }
            for row in rows
        ]

    def _artifact_job_id(self, artifact_id: str) -> str:
        row = self.database.execute_one(
            "select job_id from agent_artifact where id = ?",
            (artifact_id,),
        )
        if row is None:
            raise NotFound(f"Agent artifact not found: {artifact_id}")
        return str(row["job_id"])

    def _delivery_event_from_row(self, row: dict[str, Any]) -> DeliveryEvent:
        return DeliveryEvent(
            id=str(row["id"]),
            event_key=str(row["event_key"]),
            job_id=str(row["job_id"] or ""),
            result_artifact_id=str(row["result_artifact_id"] or ""),
            application_publication_id=str(row.get("application_publication_id") or ""),
            delivery_binding=json_from_text(row.get("delivery_binding_json") or "{}"),
            target_summary=json_from_text(row.get("target_summary") or "{}"),
            correlation_id=str(row.get("correlation_id") or ""),
            status=DeliveryStatus(str(row["status"])),
            attempt_count=int(row.get("attempt_count") or 0),
            max_attempts=int(row["max_attempts"]),
            replay_count=int(row.get("replay_count") or 0),
            max_replay_count=int(row.get("max_replay_count") or 0),
            next_attempt_at=str(row["next_attempt_at"]),
            claimed_by=str(row.get("claimed_by") or ""),
            claim_token=str(row.get("claim_token") or ""),
            claimed_at=(str(row["claimed_at"]) if row.get("claimed_at") else None),
            claim_expires_at=(
                str(row["claim_expires_at"]) if row.get("claim_expires_at") else None
            ),
            last_error_code=str(row.get("last_error_code") or ""),
            last_error_summary=str(row.get("last_error_summary") or ""),
            started_at=(str(row["started_at"]) if row.get("started_at") else None),
            finished_at=(str(row["finished_at"]) if row.get("finished_at") else None),
            dead_at=str(row["dead_at"]) if row.get("dead_at") else None,
            last_replayed_at=(
                str(row["last_replayed_at"]) if row.get("last_replayed_at") else None
            ),
            last_replayed_by=str(row.get("last_replayed_by") or ""),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
