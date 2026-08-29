from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.external_action.domain import ExternalActionStatus, canonical_json
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database, operation_unit_of_work


class ExternalActionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, intent_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            "select * from external_action_intent where id = ?",
            (intent_id,),
        )

    def create_or_get(
        self,
        *,
        facts: dict[str, str],
        arguments: dict[str, Any],
        arguments_hash: str,
        safe_summary: dict[str, Any],
        expires_at: str,
        mcp_call_id: str,
    ) -> tuple[dict[str, Any], bool]:
        existing = self.database.execute_one(
            """
            select * from external_action_intent
             where job_id = ? and tool_identifier = ? and arguments_hash = ?
            """,
            (facts["job_id"], facts["tool_identifier"], arguments_hash),
        )
        if existing is not None:
            return existing, False
        intent_id = new_id("action")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into external_action_intent
              (id, job_id, session_id, actor_user_id, business_application_id,
               agent_publication_id, application_publication_id, source_connector_id,
               dingtalk_enterprise_id, target_external_subject_id, target_union_id,
               server_code, tool_identifier, schema_hash, confirmation_policy,
               operation_code, revision, status, arguments_json, arguments_hash,
               safe_summary_json, mcp_call_id, expires_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                    'PENDING_CONFIRMATION', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent_id,
                facts["job_id"],
                facts["session_id"],
                facts["actor_user_id"],
                facts["business_application_id"],
                facts["agent_publication_id"],
                facts["application_publication_id"],
                facts["source_connector_id"],
                facts["dingtalk_enterprise_id"],
                facts["target_external_subject_id"],
                facts["target_union_id"],
                facts["server_code"],
                facts["tool_identifier"],
                facts["schema_hash"],
                facts["confirmation_policy"],
                facts["operation_code"],
                canonical_json(arguments),
                arguments_hash,
                canonical_json(safe_summary),
                mcp_call_id,
                expires_at,
                timestamp,
                timestamp,
            ),
        )
        self.enqueue_card(
            action_intent_id=intent_id,
            event_kind="CREATE",
            idempotency_key=f"{intent_id}:create:v1",
            payload={"revision": 1},
        )
        created = self.get(intent_id)
        if created is None:
            raise RuntimeError("External Action Intent insert did not persist")
        return created, True

    def enqueue_card(
        self,
        *,
        action_intent_id: str,
        event_kind: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            insert into external_action_card_outbox
              (id, action_intent_id, event_kind, status, idempotency_key,
               payload_json, attempt_count, created_at, updated_at)
            values (?, ?, ?, 'PENDING', ?, ?, 0, ?, ?)
            on conflict(idempotency_key) do nothing
            """,
            (
                new_id("action_card"),
                action_intent_id,
                event_kind,
                idempotency_key,
                canonical_json(payload),
                timestamp,
                timestamp,
            ),
        )

    def transition_from_callback(
        self,
        *,
        intent_id: str,
        expected_revision: int,
        action: str,
    ) -> tuple[dict[str, Any], bool]:
        current = self.get(intent_id)
        if current is None:
            return {}, False
        status = str(current["status"])
        if action == "agree" and status in {
            ExternalActionStatus.APPROVED.value,
            ExternalActionStatus.EXECUTING.value,
            ExternalActionStatus.SUCCEEDED.value,
            ExternalActionStatus.FAILED.value,
            ExternalActionStatus.FAILED_UNCERTAIN.value,
        }:
            return current, False
        if action == "reject" and status == ExternalActionStatus.REJECTED.value:
            return current, False
        if status != ExternalActionStatus.PENDING_CONFIRMATION.value:
            return current, False
        target = (
            ExternalActionStatus.APPROVED.value
            if action == "agree"
            else ExternalActionStatus.REJECTED.value
        )
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update external_action_intent
               set status = ?, approved_at = case when ? = 'APPROVED' then ? else approved_at end,
                   rejected_at = case when ? = 'REJECTED' then ? else rejected_at end,
                   updated_at = ?, completed_at = case when ? = 'REJECTED' then ? else null end
             where id = ? and revision = ? and status = 'PENDING_CONFIRMATION'
             returning *
            """,
            (
                target,
                target,
                timestamp,
                target,
                timestamp,
                timestamp,
                target,
                timestamp,
                intent_id,
                expected_revision,
            ),
        )
        return (rows[0], True) if rows else (self.get(intent_id) or {}, False)

    def claim_card(self, *, worker_id: str, lease_seconds: int = 30) -> dict[str, Any] | None:
        now = now_iso()
        candidate = self.database.execute_one(
            """
            select id from external_action_card_outbox
             where (status = 'PENDING'
                    or (status = 'RETRY_WAIT' and (next_attempt_at is null or next_attempt_at <= ?))
                    or (status = 'RUNNING' and claim_expires_at <= ?))
             order by created_at, id limit 1
            """,
            (now, now),
        )
        if candidate is None:
            return None
        expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
        rows = self.database.execute(
            """
            update external_action_card_outbox
               set status = 'RUNNING', claimed_by = ?, claim_expires_at = ?,
                   attempt_count = attempt_count + 1, updated_at = ?
             where id = ? and (status != 'RUNNING' or claim_expires_at <= ?)
             returning *
            """,
            (worker_id, expires, now, candidate["id"], now),
        )
        return rows[0] if rows else None

    def complete_card(self, outbox_id: str) -> None:
        self.database.execute(
            """
            update external_action_card_outbox
               set status = 'SUCCEEDED', claimed_by = '', claim_expires_at = null,
                   last_error_code = '', last_error_summary = '', updated_at = ?
             where id = ?
            """,
            (now_iso(), outbox_id),
        )

    def fail_card(self, outbox_id: str, *, error_code: str, error_summary: str) -> None:
        row = self.database.execute_one(
            "select attempt_count from external_action_card_outbox where id = ?",
            (outbox_id,),
        )
        attempts = int((row or {}).get("attempt_count") or 1)
        dead = attempts >= 8
        next_attempt = (datetime.now(UTC) + timedelta(seconds=min(300, 2**attempts))).isoformat()
        self.database.execute(
            """
            update external_action_card_outbox
               set status = ?, next_attempt_at = ?, claimed_by = '', claim_expires_at = null,
                   last_error_code = ?, last_error_summary = ?, updated_at = ?
             where id = ?
            """,
            (
                "DEAD" if dead else "RETRY_WAIT",
                None if dead else next_attempt,
                error_code[:128],
                error_summary[:500],
                now_iso(),
                outbox_id,
            ),
        )

    def claim_approved(self, *, worker_id: str, lease_seconds: int = 60) -> dict[str, Any] | None:
        now = now_iso()
        candidate = self.database.execute_one(
            """
            select id from external_action_intent
             where status = 'APPROVED'
             order by approved_at, created_at, id limit 1
            """,
        )
        if candidate is None:
            return None
        expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
        rows = self.database.execute(
            """
            update external_action_intent
               set status = 'EXECUTING', execution_claimed_by = ?,
                   execution_claim_expires_at = ?, execution_attempts = execution_attempts + 1,
                   updated_at = ?
             where id = ? and (status = 'APPROVED'
                    )
             returning *
            """,
            (worker_id, expires, now, candidate["id"]),
        )
        return rows[0] if rows else None

    @operation_unit_of_work(lambda repository: repository.database)
    def recover_stale_execution(self) -> dict[str, Any] | None:
        now = now_iso()
        candidate = self.database.execute_one(
            """
            select id from external_action_intent
             where status = 'EXECUTING' and execution_claim_expires_at <= ?
             order by execution_claim_expires_at, id limit 1
            """,
            (now,),
        )
        if candidate is None:
            return None
        rows = self.database.execute(
            """
            update external_action_intent
               set status = 'FAILED_UNCERTAIN', execution_claimed_by = '',
                   execution_claim_expires_at = null,
                   last_error_code = 'external_action_worker_interrupted',
                   last_error_summary = '执行Worker中断，Provider结果未知，禁止自动重放',
                   updated_at = ?, completed_at = ?
             where id = ? and status = 'EXECUTING' and execution_claim_expires_at <= ?
             returning *
            """,
            (now, now, candidate["id"], now),
        )
        if not rows:
            return None
        intent = rows[0]
        self.enqueue_card(
            action_intent_id=str(intent["id"]),
            event_kind="RESULT_UPDATE",
            idempotency_key=f"{intent['id']}:result:failed_uncertain",
            payload={"status": "failed", "statusText": "执行结果未知，请人工核对"},
        )
        return intent

    @operation_unit_of_work(lambda repository: repository.database)
    def complete_execution(
        self,
        intent_id: str,
        *,
        result: dict[str, Any],
        provider_request_id: str = "",
    ) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            update external_action_intent
               set status = 'SUCCEEDED', result_json = ?, provider_request_id = ?,
                   execution_claimed_by = '', execution_claim_expires_at = null,
                   last_error_code = '', last_error_summary = '', updated_at = ?, completed_at = ?
             where id = ? and status = 'EXECUTING'
            """,
            (
                canonical_json(result),
                provider_request_id[:256],
                timestamp,
                timestamp,
                intent_id,
            ),
        )
        self.enqueue_card(
            action_intent_id=intent_id,
            event_kind="RESULT_UPDATE",
            idempotency_key=f"{intent_id}:result:succeeded",
            payload={"status": "succeeded", "statusText": "操作成功"},
        )

    @operation_unit_of_work(lambda repository: repository.database)
    def fail_execution(
        self,
        intent_id: str,
        *,
        error_code: str,
        error_summary: str,
        uncertain: bool = False,
    ) -> None:
        timestamp = now_iso()
        status = "FAILED_UNCERTAIN" if uncertain else "FAILED"
        self.database.execute(
            """
            update external_action_intent
               set status = ?, execution_claimed_by = '', execution_claim_expires_at = null,
                   last_error_code = ?, last_error_summary = ?, updated_at = ?, completed_at = ?
             where id = ? and status = 'EXECUTING'
            """,
            (status, error_code[:128], error_summary[:500], timestamp, timestamp, intent_id),
        )
        self.enqueue_card(
            action_intent_id=intent_id,
            event_kind="RESULT_UPDATE",
            idempotency_key=f"{intent_id}:result:{status.lower()}",
            payload={"status": "failed", "statusText": "操作失败，请联系管理员"},
        )

    @staticmethod
    def decode_json(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
