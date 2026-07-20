from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.modules.webhook.domain.models import WebhookEventStatus
from app.shared.database import Database
from app.shared.exceptions import NotFound


class WebhookEventRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def receive(
        self,
        *,
        trigger_id: str,
        trigger_publication_id: str,
        agent_publication_id: str,
        service_account_id: str,
        external_event_id: str,
        dedup_key: str | None,
        payload_hash: str,
        request_bytes: int,
        safe_summary: dict[str, Any],
        normalized_event: dict[str, Any],
        correlation_id: str,
        status: WebhookEventStatus,
        auth_result: str,
        filter_result: str,
        error_code: str = "",
        error_summary: str = "",
        enqueue: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        event_id = new_id("webhook_event")
        timestamp = now_iso()
        rows = self.database.execute(
            """
            insert into webhook_event
              (id, trigger_id, trigger_publication_id, agent_publication_id,
               service_account_id, external_event_id, dedup_key, payload_hash,
               request_bytes, safe_summary_json, normalized_event_json,
               correlation_id, status, auth_result, filter_result, error_code,
               error_summary, received_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(trigger_id, dedup_key) do nothing
            returning id
            """,
            (
                event_id,
                trigger_id,
                trigger_publication_id,
                agent_publication_id,
                service_account_id,
                external_event_id,
                dedup_key,
                payload_hash,
                request_bytes,
                json.dumps(safe_summary, ensure_ascii=False, sort_keys=True),
                json.dumps(normalized_event, ensure_ascii=False, sort_keys=True),
                correlation_id,
                status.value,
                auth_result,
                filter_result,
                error_code,
                error_summary[:500],
                timestamp,
            ),
        )
        created = bool(rows)
        if not created and dedup_key is not None:
            existing = self.database.execute_one(
                "select id from webhook_event where trigger_id = ? and dedup_key = ?",
                (trigger_id, dedup_key),
            )
            if not existing:
                raise RuntimeError("Webhook event dedup record could not be resolved")
            event_id = str(existing["id"])
        if created and enqueue:
            self.database.execute(
                """
                insert into webhook_outbox
                  (id, webhook_event_id, correlation_id, status, attempt_count,
                   next_attempt_at, created_at, updated_at)
                values (?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (new_id("webhook_outbox"), event_id, correlation_id, timestamp, timestamp, timestamp),
            )
        return self.get(event_id), created

    def get(self, event_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select e.*, d.code as trigger_code, d.name as trigger_name,
                   p.revision as trigger_revision
            from webhook_event e
            join webhook_trigger_definition d on d.id = e.trigger_id
            join webhook_trigger_publication p on p.id = e.trigger_publication_id
            where e.id = ?
            """,
            (event_id,),
        )
        if not row:
            raise NotFound("Webhook event not found", safe_message="Webhook event not found")
        return self._event(row)

    def list_events(
        self,
        *,
        trigger_id: str | None = None,
        status: str = "",
        job_id: str = "",
        received_from: str = "",
        received_to: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if trigger_id:
            clauses.append("e.trigger_id = ?")
            params.append(trigger_id)
        if status:
            clauses.append("e.status = ?")
            params.append(status)
        if job_id:
            clauses.append("e.job_id = ?")
            params.append(job_id)
        if received_from:
            clauses.append("e.received_at >= ?")
            params.append(received_from)
        if received_to:
            clauses.append("e.received_at <= ?")
            params.append(received_to)
        where = "where " + " and ".join(clauses) if clauses else ""
        params.extend((min(max(limit, 1), 200), max(offset, 0)))
        rows = self.database.execute(
            f"""
            select e.*, d.code as trigger_code, d.name as trigger_name,
                   p.revision as trigger_revision
            from webhook_event e
            join webhook_trigger_definition d on d.id = e.trigger_id
            join webhook_trigger_publication p on p.id = e.trigger_publication_id
            {where}
            order by e.received_at desc, e.id desc limit ? offset ?
            """,
            params,
        )
        return [self._event(row) for row in rows]

    def register_nonce(self, *, trigger_id: str, nonce_hash: str, expires_at: str) -> bool:
        rows = self.database.execute(
            """
            insert into webhook_replay_nonce
              (trigger_id, nonce_hash, expires_at, created_at)
            values (?, ?, ?, ?)
            on conflict(trigger_id, nonce_hash) do nothing
            returning nonce_hash
            """,
            (trigger_id, nonce_hash, expires_at, now_iso()),
        )
        return bool(rows)

    def rate_counts(self, *, trigger_id: str, since: str) -> tuple[int, int]:
        request_row = self.database.execute_one(
            """
            select count(*) as count from webhook_event
            where trigger_id = ? and received_at >= ?
            """,
            (trigger_id, since),
        )
        in_flight_row = self.database.execute_one(
            """
            select count(*) as count from webhook_event
            where trigger_id = ? and status in ('ACCEPTED', 'DISPATCH_PENDING')
            """,
            (trigger_id,),
        )
        return int(request_row["count"] if request_row else 0), int(
            in_flight_row["count"] if in_flight_row else 0
        )

    def claim_outbox(self, *, worker_id: str, now: str) -> dict[str, Any] | None:
        rows = self.database.execute(
            """
            update webhook_outbox
            set status = 'publishing', claimed_by = ?, claimed_at = ?,
                attempt_count = attempt_count + 1, updated_at = ?
            where id = (
              select id from webhook_outbox
              where status = 'pending' and next_attempt_at <= ?
              order by next_attempt_at, created_at limit 1
            ) and status = 'pending'
            returning *
            """,
            (worker_id, now, now, now),
        )
        return rows[0] if rows else None

    def recover_stale_outbox_claims(self, *, stale_before: str) -> int:
        rows = self.database.execute(
            """
            update webhook_outbox
            set status = 'pending', claimed_by = '', claimed_at = null, updated_at = ?
            where status = 'publishing' and claimed_at < ?
            returning id
            """,
            (now_iso(), stale_before),
        )
        return len(rows)

    def mark_outbox_published(self, outbox_id: str) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            update webhook_outbox
            set status = 'published', published_at = ?, claimed_by = '',
                claimed_at = null, last_error_summary = '', updated_at = ?
            where id = ?
            """,
            (timestamp, timestamp, outbox_id),
        )
        self.database.execute(
            """
            update webhook_event set status = 'DISPATCH_PENDING'
            where id = (select webhook_event_id from webhook_outbox where id = ?)
              and status = 'ACCEPTED'
            """,
            (outbox_id,),
        )

    def mark_outbox_failed(
        self,
        *,
        outbox_id: str,
        error_summary: str,
        max_attempts: int,
        base_delay_seconds: int,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            "select attempt_count from webhook_outbox where id = ?", (outbox_id,)
        )
        attempts = int(row["attempt_count"] if row else max_attempts)
        dead = attempts >= max_attempts
        next_attempt = datetime.now(UTC) + timedelta(
            seconds=base_delay_seconds * (2 ** max(attempts - 1, 0))
        )
        self.database.execute(
            """
            update webhook_outbox
            set status = ?, next_attempt_at = ?, claimed_by = '', claimed_at = null,
                last_error_summary = ?, updated_at = ? where id = ?
            """,
            (
                "dead" if dead else "pending",
                next_attempt.isoformat(),
                error_summary[:500],
                now_iso(),
                outbox_id,
            ),
        )
        if dead:
            self.database.execute(
                """
                update webhook_event
                set status = 'DISPATCH_FAILED', error_code = 'webhook_dispatch_failed',
                    error_summary = ?, completed_at = ?
                where id = (select webhook_event_id from webhook_outbox where id = ?)
                """,
                (error_summary[:500], now_iso(), outbox_id),
            )
        return self.database.execute_one(
            "select * from webhook_outbox where id = ?", (outbox_id,)
        ) or {}

    def attach_job(self, *, event_id: str, job_id: str) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update webhook_event
            set job_id = ?, status = 'JOB_CREATED', dispatched_at = ?, completed_at = ?
            where id = ? and job_id is null
            returning id
            """,
            (job_id, now_iso(), now_iso(), event_id),
        )
        if not rows:
            return self.get(event_id)
        return self.get(event_id)

    def mark_dispatch_failed(self, *, event_id: str, error_summary: str) -> None:
        self.database.execute(
            """
            update webhook_event
            set status = 'DISPATCH_FAILED', error_code = 'webhook_dispatch_failed',
                error_summary = ?, completed_at = ?
            where id = ? and job_id is null
            """,
            (error_summary[:500], now_iso(), event_id),
        )

    def cleanup(self, *, nonce_before: str, event_before: str) -> dict[str, int]:
        nonce_count = self.database.execute_one(
            "select count(*) as count from webhook_replay_nonce where expires_at < ?",
            (nonce_before,),
        )
        self.database.execute("delete from webhook_replay_nonce where expires_at < ?", (nonce_before,))
        event_count = self.database.execute_one(
            """
            select count(*) as count from webhook_event
            where received_at < ? and job_id is null
              and status in ('REJECTED_AUTH', 'REJECTED', 'IGNORED', 'DISPATCH_FAILED')
            """,
            (event_before,),
        )
        self.database.execute(
            """
            delete from webhook_outbox
            where webhook_event_id in (
              select id from webhook_event
              where received_at < ? and job_id is null
                and status in ('REJECTED_AUTH', 'REJECTED', 'IGNORED', 'DISPATCH_FAILED')
            ) and status in ('published', 'dead')
            """,
            (event_before,),
        )
        self.database.execute(
            """
            delete from webhook_event
            where received_at < ? and job_id is null
              and status in ('REJECTED_AUTH', 'REJECTED', 'IGNORED', 'DISPATCH_FAILED')
            """,
            (event_before,),
        )
        return {
            "nonces": int(nonce_count["count"] if nonce_count else 0),
            "events": int(event_count["count"] if event_count else 0),
        }

    def _event(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "request_bytes": int(row["request_bytes"]),
            "safe_summary": _json(str(row.get("safe_summary_json") or "{}")),
            "normalized_event": _json(str(row.get("normalized_event_json") or "{}")),
        }


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}
