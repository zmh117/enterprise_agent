from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.external_action.domain import ExternalActionStatus, canonical_json
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database, operation_unit_of_work
from app.shared.dingtalk_card_templates import external_action_confirmation_card_binding
from app.shared.exceptions import NonRetryableExecutionError


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
        facts: dict[str, Any],
        arguments: dict[str, Any],
        arguments_hash: str,
        safe_summary: dict[str, Any],
        expires_at: str,
        mcp_call_id: str,
    ) -> tuple[dict[str, Any], bool]:
        is_ones_create = str(facts.get("operation_code") or "") == "ones.task.create"
        if is_ones_create:
            existing = self.database.execute_one(
                """
                select * from external_action_intent
                 where job_id = ? and tool_identifier = ? and mcp_call_id = ?
                """,
                (facts["job_id"], facts["tool_identifier"], mcp_call_id),
            )
            if existing is not None:
                if not self._same_create_call(existing, facts=facts, arguments=arguments):
                    raise NonRetryableExecutionError(
                        "MCP call id was reused with different creation arguments",
                        safe_message="同一工具调用的缺陷提案内容不一致，请重新发起",
                        error_code="external_action_mcp_call_conflict",
                    )
                return existing, False
        intent_fingerprint = str(facts.get("intent_fingerprint") or "")
        stored_arguments_hash = intent_fingerprint or arguments_hash
        if intent_fingerprint and not is_ones_create:
            existing = self.database.execute_one(
                "select * from external_action_intent where intent_fingerprint = ?",
                (intent_fingerprint,),
            )
        elif not is_ones_create:
            existing = self.database.execute_one(
                """
                select * from external_action_intent
                 where job_id = ? and tool_identifier = ? and arguments_hash = ?
                """,
                (facts["job_id"], facts["tool_identifier"], arguments_hash),
            )
        if not is_ones_create and existing is not None:
            return existing, False
        card_binding = self._confirmation_card_binding(facts)
        intent_id = new_id("action")
        timestamp = now_iso()
        supersedes_intent_id = str(facts.get("supersedes_intent_id") or "")
        proposal_chain_id = intent_id
        superseded: dict[str, Any] | None = None
        if supersedes_intent_id:
            if not is_ones_create:
                raise self._supersede_denied()
            superseded = self._require_supersedable(
                supersedes_intent_id=supersedes_intent_id,
                facts=facts,
            )
            proposal_chain_id = str(superseded["proposal_chain_id"])
        has_proposal_chain = self._has_proposal_chain_column()
        if is_ones_create and not has_proposal_chain:
            raise RuntimeError("ONES defect creation requires schema migration 129")
        confirmation_summary_json = canonical_json(safe_summary)
        legacy_summary_json = confirmation_summary_json
        if len(legacy_summary_json) > 4096:
            if str(facts.get("execution_provider_code") or "dingtalk") != "ones":
                raise ValueError("External action summary exceeds the durable limit")
            legacy_summary_json = canonical_json(
                {
                    "operation": str(safe_summary.get("operation") or ""),
                    "target": str(safe_summary.get("target") or ""),
                }
            )
        common_values = (
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
            stored_arguments_hash,
            legacy_summary_json,
            confirmation_summary_json,
            mcp_call_id,
            expires_at,
            timestamp,
            timestamp,
            str(facts.get("confirmation_channel_code") or "dingtalk"),
            str(facts.get("execution_provider_code") or "dingtalk"),
            str(facts.get("execution_external_identity_id") or "") or None,
            str(facts.get("execution_scope_id") or ""),
            str(facts.get("target_resource_type") or ""),
            str(facts.get("target_resource_id") or ""),
            canonical_json(facts.get("precondition") or {}),
            str(facts.get("precondition_hash") or ""),
            str(facts.get("field_catalog_version") or ""),
            str(facts.get("field_catalog_hash") or ""),
            intent_fingerprint,
        )
        if has_proposal_chain:
            conflict_clause = (
                "on conflict(job_id, tool_identifier, mcp_call_id) "
                "where operation_code = 'ones.task.create' do nothing returning id"
                if is_ones_create
                else ""
            )
            inserted = self.database.execute(
                f"""
            insert into external_action_intent
              (id, job_id, session_id, actor_user_id, business_application_id,
               agent_publication_id, application_publication_id, source_connector_id,
               dingtalk_enterprise_id, target_external_subject_id, target_union_id,
               server_code, tool_identifier, schema_hash, confirmation_policy,
               operation_code, revision, status, arguments_json, arguments_hash,
               safe_summary_json, confirmation_summary_json, mcp_call_id,
               expires_at, created_at, updated_at,
               confirmation_channel_code, execution_provider_code,
               execution_external_identity_id, execution_scope_id,
               target_resource_type, target_resource_id, precondition_json,
               precondition_hash, field_catalog_version, field_catalog_hash,
               intent_fingerprint, proposal_chain_id, supersedes_intent_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                    'PENDING_CONFIRMATION', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?)
            {conflict_clause}
                """,
                (*common_values, proposal_chain_id, supersedes_intent_id or None),
            )
        else:
            # Preserve the legacy insert shape for existing providers and for
            # compatibility tests that intentionally project the pre-129 table.
            inserted = self.database.execute(
                """
            insert into external_action_intent
              (id, job_id, session_id, actor_user_id, business_application_id,
               agent_publication_id, application_publication_id, source_connector_id,
               dingtalk_enterprise_id, target_external_subject_id, target_union_id,
               server_code, tool_identifier, schema_hash, confirmation_policy,
               operation_code, revision, status, arguments_json, arguments_hash,
               safe_summary_json, confirmation_summary_json, mcp_call_id,
               expires_at, created_at, updated_at,
               confirmation_channel_code, execution_provider_code,
               execution_external_identity_id, execution_scope_id,
               target_resource_type, target_resource_id, precondition_json,
               precondition_hash, field_catalog_version, field_catalog_hash,
               intent_fingerprint)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                    'PENDING_CONFIRMATION', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?)
                """,
                common_values,
            )
        if is_ones_create and not inserted:
            existing = self.database.execute_one(
                """
                select * from external_action_intent
                 where job_id = ? and tool_identifier = ? and mcp_call_id = ?
                """,
                (facts["job_id"], facts["tool_identifier"], mcp_call_id),
            )
            if existing is None or not self._same_create_call(
                existing,
                facts=facts,
                arguments=arguments,
            ):
                raise NonRetryableExecutionError(
                    "MCP call id conflict could not be safely reconciled",
                    safe_message="工具调用重入状态不一致，请重新发起",
                    error_code="external_action_mcp_call_conflict",
                )
            return existing, False
        if superseded is not None:
            rows = self.database.execute(
                """
                update external_action_intent
                   set status = 'SUPERSEDED', superseded_by_intent_id = ?,
                       superseded_at = ?, updated_at = ?, completed_at = ?
                 where id = ? and status = 'PENDING_CONFIRMATION'
                   and superseded_by_intent_id is null
                returning *
                """,
                (
                    intent_id,
                    timestamp,
                    timestamp,
                    timestamp,
                    supersedes_intent_id,
                ),
            )
            if len(rows) != 1:
                raise self._supersede_denied()
        self.enqueue_card(
            action_intent_id=intent_id,
            event_kind="CREATE",
            idempotency_key=f"{intent_id}:create:v1",
            payload={"revision": 1, "card_binding": card_binding},
        )
        if superseded is not None:
            self.enqueue_card(
                action_intent_id=supersedes_intent_id,
                event_kind="RESULT_UPDATE",
                idempotency_key=f"{supersedes_intent_id}:result:superseded",
                payload={
                    "status": "superseded",
                    "statusText": "已被新版本替代，请使用最新确认卡",
                },
            )
        created = self.get(intent_id)
        if created is None:
            raise RuntimeError("External Action Intent insert did not persist")
        return created, True

    def _has_proposal_chain_column(self) -> bool:
        if self.database.engine == "sqlite":
            return any(
                str(row.get("name") or "") == "proposal_chain_id"
                for row in self.database.execute("pragma table_info(external_action_intent)")
            )
        return self.database.execute_one(
            """
            select column_name from information_schema.columns
             where table_schema = current_schema()
               and table_name = 'external_action_intent'
               and column_name = 'proposal_chain_id'
            """
        ) is not None

    @staticmethod
    def _same_create_call(
        existing: dict[str, Any],
        *,
        facts: dict[str, Any],
        arguments: dict[str, Any],
    ) -> bool:
        return (
            str(existing.get("arguments_json") or "") == canonical_json(arguments)
            and str(existing.get("supersedes_intent_id") or "")
            == str(facts.get("supersedes_intent_id") or "")
        )

    def _require_supersedable(
        self,
        *,
        supersedes_intent_id: str,
        facts: dict[str, Any],
    ) -> dict[str, Any]:
        old = self.get(supersedes_intent_id)
        required_equal = {
            "actor_user_id": "actor_user_id",
            "session_id": "session_id",
            "business_application_id": "business_application_id",
            "agent_publication_id": "agent_publication_id",
            "application_publication_id": "application_publication_id",
            "source_connector_id": "source_connector_id",
            "dingtalk_enterprise_id": "dingtalk_enterprise_id",
            "target_external_subject_id": "target_external_subject_id",
            "target_union_id": "target_union_id",
            "server_code": "server_code",
            "tool_identifier": "tool_identifier",
            "execution_external_identity_id": "execution_external_identity_id",
            "execution_scope_id": "execution_scope_id",
        }
        if (
            old is None
            or str(old.get("operation_code") or "") != "ones.task.create"
            or str(old.get("status") or "") != ExternalActionStatus.PENDING_CONFIRMATION.value
            or str(old.get("expires_at") or "") <= datetime.now(UTC).isoformat()
            or old.get("superseded_by_intent_id") is not None
            or any(
                str(old.get(old_key) or "") != str(facts.get(fact_key) or "")
                for old_key, fact_key in required_equal.items()
            )
        ):
            raise self._supersede_denied()
        return old

    @staticmethod
    def _supersede_denied() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "External action proposal cannot be superseded",
            safe_message="原缺陷提案已确认、执行、终结或不属于当前会话，请等待结果后再更新",
            error_code="external_action_supersede_denied",
        )

    def _confirmation_card_binding(self, facts: dict[str, Any]) -> dict[str, Any]:
        if str(facts.get("confirmation_channel_code") or "dingtalk") != "dingtalk":
            raise NonRetryableExecutionError(
                "External action confirmation channel is unsupported",
                safe_message="当前外部操作确认渠道不可用",
                error_code="external_action_confirmation_channel_unsupported",
            )
        connector_id = str(facts.get("source_connector_id") or "")
        row = self.database.execute_one(
            """
            select metadata, revision from integration_connector
             where id = ? and connector_type = 'dingtalk_enterprise_stream'
               and enabled = 1 and deleted = 0
            """,
            (connector_id,),
        )
        metadata = self.decode_json((row or {}).get("metadata"))
        binding = external_action_confirmation_card_binding(
            metadata,
            connector_id=connector_id,
            connector_revision=int((row or {}).get("revision") or 0),
        )
        if binding is None:
            raise NonRetryableExecutionError(
                "DingTalk confirmation card template binding is unavailable",
                safe_message="当前钉钉来源连接未配置兼容的外部操作确认卡片模板 ID",
                error_code="dingtalk_confirmation_card_template_not_ready",
            )
        return binding

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
    def mark_provider_attempt_started(
        self,
        intent_id: str,
        *,
        request_hash: str,
        catalog_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update external_action_intent
               set provider_attempt_status = 'STARTED',
                   provider_attempt_started_at = ?, provider_request_hash = ?,
                   provider_catalog_hash = ?, updated_at = ?
             where id = ? and status = 'EXECUTING' and provider_attempt_status = ''
            returning *
            """,
            (timestamp, request_hash, catalog_hash, timestamp, intent_id),
        )
        if rows:
            return rows[0], True
        current = self.get(intent_id)
        if current is None:
            raise RuntimeError("External Action Intent disappeared")
        return current, False

    @operation_unit_of_work(lambda repository: repository.database)
    def claim_stale_for_reconciliation(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> dict[str, Any] | None:
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
        expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
        rows = self.database.execute(
            """
            update external_action_intent
               set execution_claimed_by = ?, execution_claim_expires_at = ?, updated_at = ?
             where id = ? and status = 'EXECUTING' and execution_claim_expires_at <= ?
             returning *
            """,
            (worker_id[:128], expires, now, candidate["id"], now),
        )
        return rows[0] if rows else None

    def recover_stale_execution(self) -> dict[str, Any] | None:
        """Compatibility path for Providers without a read-only reconciler."""

        intent = self.claim_stale_for_reconciliation(worker_id="stale-recovery")
        if intent is None:
            return None
        self.fail_execution(
            str(intent["id"]),
            error_code="external_action_worker_interrupted",
            error_summary="执行Worker中断，Provider结果未知，禁止自动重放",
            uncertain=True,
            card_status_text="执行结果未知，请人工核对",
        )
        return self.get(str(intent["id"]))

    @operation_unit_of_work(lambda repository: repository.database)
    def complete_execution(
        self,
        intent_id: str,
        *,
        result: dict[str, Any],
        provider_request_id: str = "",
        card_status_text: str = "",
        card_fields: dict[str, str] | None = None,
    ) -> None:
        safe_card_fields: dict[str, str] = {}
        if card_fields:
            allowed = {"providerName", "operationName", "targetName", "detailText"}
            if set(card_fields) - allowed or any(
                not isinstance(value, str) for value in card_fields.values()
            ):
                raise ValueError("External action result card fields are invalid")
            safe_card_fields = {
                key: value
                for key, value in card_fields.items()
                if key in allowed and value
            }
            if len(safe_card_fields.get("detailText", "")) > 4000:
                raise ValueError("External action result card detail exceeds its limit")
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
            payload={
                "status": "succeeded",
                **({"statusText": card_status_text[:200]} if card_status_text.strip() else {}),
                **({"cardFields": safe_card_fields} if safe_card_fields else {}),
            },
        )

    @operation_unit_of_work(lambda repository: repository.database)
    def fail_execution(
        self,
        intent_id: str,
        *,
        error_code: str,
        error_summary: str,
        uncertain: bool = False,
        card_status_text: str = "",
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
            payload={
                "status": "failed",
                "statusText": card_status_text[:200] or "操作失败，请联系管理员",
            },
        )

    @staticmethod
    def decode_json(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
