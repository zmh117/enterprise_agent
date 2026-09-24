from __future__ import annotations

import json
from typing import Any

from app.modules.job.domain.agent_job import AgentJob, AgentSession, MessageAttachment
from app.modules.job.domain.execution_policy import JobExecutionPolicySnapshot
from app.modules.job.domain.job_status import JobStatus, can_transition
from app.modules.job.infrastructure.persistence_values import json_from_text, new_id, now_iso
from app.shared.build_identity import build_identity_from_environment
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError
from app.shared.secret_redaction import (
    redact_sensitive_text,
    sanitize_for_persistence,
)


_SESSION_COLUMN_NAMES = (
    "id",
    "project_code",
    "created_at",
    "updated_at",
    "source_channel",
    "source_connector_id",
    "external_conversation_id",
    "requester_id",
    "requester_display_name",
    "routing_context_json",
    "reply_route_json",
    "session_key",
    "conversation_type",
    "bot_identity",
    "summary_text",
    "summary_through_sequence",
    "summary_version",
    "message_sequence",
    "last_message_at",
    "external_identity_id",
    "business_application_id",
    "business_application_code",
    "conversation_mode",
    "recent_message_limit",
    "session_policy_json",
    "application_publication_id",
    "execution_scope_hash",
    "isolation_key_version",
    "history_read_only",
)
_JOB_COLUMN_NAMES = (
    "id",
    "session_id",
    "idempotency_key",
    "project_code",
    "status",
    "priority",
    "retry_count",
    "max_retry_count",
    "result",
    "error_message",
    "created_at",
    "started_at",
    "finished_at",
    "locked_at",
    "locked_by",
    "source_channel",
    "source_connector_id",
    "external_event_id",
    "requester_id",
    "routing_context_json",
    "reply_route_json",
    "internal_user_id",
    "external_identity_id",
    "agent_definition_id",
    "agent_publication_id",
    "agent_revision",
    "agent_config_hash",
    "webhook_event_id",
    "webhook_trigger_id",
    "webhook_trigger_publication_id",
    "last_error_code",
    "last_error_at",
    "next_retry_at",
    "business_application_id",
    "business_application_code",
    "business_application_publication_id",
    "business_application_deployment_id",
    "business_application_route_id",
    "business_application_config_hash",
    "business_application_runtime_status",
    "business_application_route_decision_json",
    "execution_policy_json",
    "execution_policy_tool_call_count",
    "execution_policy_exhausted",
    "model_runtime_provenance_json",
    "agent_runtime_kind",
    "agent_runtime_protocol_version",
    "task_workspace_id",
    "input_message_id",
    "control_plane_build_identity_json",
    "tool_contract_status",
    "tool_contract_last_invocation_id",
    "tool_contract_observation_hash",
    "prompt_template_version",
    "prompt_contract_hash",
)
_SESSION_COLUMNS_SQL = ", ".join(_SESSION_COLUMN_NAMES)
_JOB_COLUMNS_SQL = ", ".join(_JOB_COLUMN_NAMES)
_QUALIFIED_JOB_COLUMNS_SQL = ", ".join(f"j.{column}" for column in _JOB_COLUMN_NAMES)


def source_connector_projection(row: dict[str, Any]) -> dict[str, str]:
    connector_id = str(row.get("source_connector_id") or "")
    connector_name = str(row.get("source_connector_name") or "")
    if not connector_id:
        availability = "NOT_APPLICABLE"
    elif not row.get("source_connector_record_id"):
        availability = "UNKNOWN"
    else:
        try:
            metadata = json.loads(str(row.get("source_connector_metadata") or "{}"))
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        historical_status = (
            str(metadata.get("historical_source_status") or "").upper()
            if isinstance(metadata, dict)
            else ""
        )
        if bool(row.get("source_connector_deleted")) or historical_status == "UNAVAILABLE":
            availability = "UNAVAILABLE_HISTORICAL"
        elif bool(row.get("source_connector_enabled")):
            availability = "AVAILABLE"
        else:
            availability = "UNAVAILABLE"
    return {
        "source_connector_name": connector_name,
        "source_connector_availability": availability,
    }


class AgentRepository:  # noqa: PLR0904
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_session(
        self,
        *,
        project_code: str,
        source_channel: str,
        source_connector_id: str,
        external_conversation_id: str,
        requester_id: str,
        requester_display_name: str = "",
        routing_context: dict[str, Any] | None = None,
        reply_route: dict[str, Any] | None = None,
        session_key: str = "",
        conversation_type: str = "direct",
        bot_identity: str = "",
        external_identity_id: str = "",
        business_application_id: str = "",
        business_application_code: str = "",
        application_publication_id: str = "",
        execution_scope_hash: str = "",
        isolation_key_version: int = 2,
        history_read_only: bool = False,
        conversation_mode: str = "legacy",
        recent_message_limit: int | None = None,
        session_policy: dict[str, Any] | None = None,
    ) -> AgentSession:
        if conversation_mode in {"application", "actor"}:
            raise NonRetryableExecutionError(
                "Legacy shared session mode is read-only",
                safe_message="旧共享会话模式仅可查看历史，请改为按渠道会话",
                error_code="session_mode_unsupported",
            )
        session_id = new_id("session")
        timestamp = now_iso()
        if not all(
            (
                project_code,
                source_channel,
                source_connector_id,
                external_conversation_id,
                requester_id,
            )
        ):
            raise NonRetryableExecutionError(
                "Canonical Agent session identity is incomplete",
                safe_message="会话身份或路由上下文不完整",
                error_code="session_identity_incomplete",
            )
        routing_context = routing_context or {"project_code": project_code}
        reply_route = reply_route or {"type": "dingtalk_conversation"}
        session_key = session_key or f"legacy:{session_id}"
        self.database.execute(
            """
            insert into agent_session
              (id, project_code, source_channel, source_connector_id,
               external_conversation_id, requester_id,
               requester_display_name, routing_context_json, reply_route_json, created_at, updated_at,
               session_key, conversation_type, bot_identity, external_identity_id,
               business_application_id, business_application_code,
               application_publication_id, execution_scope_hash,
               isolation_key_version, history_read_only, conversation_mode,
               recent_message_limit, session_policy_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(session_key) do nothing
            """,
            (
                session_id,
                project_code,
                source_channel,
                source_connector_id,
                external_conversation_id,
                requester_id,
                requester_display_name,
                json.dumps(routing_context, ensure_ascii=False),
                json.dumps(reply_route, ensure_ascii=False),
                timestamp,
                timestamp,
                session_key,
                conversation_type,
                bot_identity,
                external_identity_id or None,
                business_application_id or None,
                business_application_code,
                application_publication_id or None,
                execution_scope_hash or None,
                isolation_key_version,
                1 if history_read_only else 0,
                conversation_mode,
                recent_message_limit,
                json.dumps(session_policy or {}, ensure_ascii=False),
            ),
        )
        row = self.database.execute_one(
            "select id from agent_session where session_key = ?", (session_key,)
        )
        if not row:
            raise NonRetryableExecutionError(
                "Agent session could not be resolved",
                safe_message="无法确定 Agent 会话",
            )
        session = self.get_session(str(row["id"]))
        if session.history_read_only:
            raise NonRetryableExecutionError(
                "Historical Agent session is read-only",
                safe_message="该历史会话只读，不能继续创建任务",
                error_code="session_history_read_only",
            )
        if application_publication_id and (
            session.application_publication_id != application_publication_id
            or session.execution_scope_hash != execution_scope_hash
            or session.isolation_key_version != isolation_key_version
        ):
            raise NonRetryableExecutionError(
                "Agent session isolation facts do not match",
                safe_message="会话隔离上下文已变化，请创建新会话",
                error_code="session_isolation_mismatch",
            )
        return session

    def create_job(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        project_code: str,
        source_channel: str,
        source_connector_id: str,
        requester_id: str,
        input_message: str,
        max_retry_count: int,
        external_event_id: str = "",
        external_message_id: str = "",
        requester_display_name: str = "",
        message_type: str = "text",
        message_content_status: str = "READY",
        routing_context: dict[str, Any] | None = None,
        reply_route: dict[str, Any] | None = None,
        initial_status: JobStatus = JobStatus.PENDING,
        internal_user_id: str = "",
        external_identity_id: str = "",
        agent_definition_id: str = "",
        agent_publication_id: str = "",
        agent_revision: int | None = None,
        agent_config_hash: str = "",
        webhook_event_id: str = "",
        webhook_trigger_id: str = "",
        webhook_trigger_publication_id: str = "",
        business_application_id: str = "",
        business_application_code: str = "",
        business_application_publication_id: str = "",
        business_application_deployment_id: str = "",
        business_application_route_id: str = "",
        business_application_config_hash: str = "",
        business_application_runtime_status: str = "",
        business_application_route_decision: dict[str, Any] | None = None,
        execution_policy: dict[str, Any] | None = None,
        model_runtime_provenance: dict[str, Any] | None = None,
        agent_runtime_kind: str = "python-v1",
        agent_runtime_protocol_version: str = "1.5",
        task_workspace_id: str = "",
        quoted_external_message_id: str = "",
    ) -> AgentJob:
        existing = self.get_job_by_idempotency_key(idempotency_key)
        if existing:
            return existing
        session_row = self.database.execute_one(
            """
            select history_read_only, application_publication_id
              from agent_session where id = ?
            """,
            (session_id,),
        )
        if session_row is None:
            raise NotFound(f"Agent session not found: {session_id}")
        if bool(session_row.get("history_read_only")):
            raise NonRetryableExecutionError(
                "Historical Agent session is read-only",
                safe_message="该历史会话只读，不能继续创建任务",
                error_code="session_history_read_only",
            )
        session_publication_id = str(session_row.get("application_publication_id") or "")
        if business_application_publication_id and (
            session_publication_id != business_application_publication_id
        ):
            raise NonRetryableExecutionError(
                "Job publication does not match its Agent session",
                safe_message="会话发布版本已变化，请创建新会话",
                error_code="session_isolation_mismatch",
            )
        if not all((project_code, source_channel, source_connector_id, requester_id)):
            raise NonRetryableExecutionError(
                "Canonical Agent job provenance is incomplete",
                safe_message="任务来源或请求者上下文不完整",
                error_code="job_provenance_incomplete",
            )
        job_id = new_id("job")
        timestamp = now_iso()
        routing_context = routing_context or {"project_code": project_code}
        reply_route = reply_route or {"type": "dingtalk_conversation"}
        normalized_execution_policy = JobExecutionPolicySnapshot.from_dict(
            execution_policy
        ).to_dict()
        control_plane_build_identity = build_identity_from_environment("control-plane").to_dict()
        with self.database.unit_of_work():
            inserted = self.database.execute_one(
                """
                insert into agent_job
                  (id, session_id, idempotency_key, project_code,
                   status, retry_count, max_retry_count, source_channel, source_connector_id,
                   external_event_id, requester_id, routing_context_json, reply_route_json,
                   created_at, internal_user_id, external_identity_id, agent_definition_id,
                   agent_publication_id, agent_revision, agent_config_hash,
                   webhook_event_id, webhook_trigger_id, webhook_trigger_publication_id,
                   business_application_id, business_application_code,
                   business_application_publication_id, business_application_deployment_id,
                   business_application_route_id, business_application_config_hash,
                   business_application_runtime_status,
                   business_application_route_decision_json, execution_policy_json,
                   model_runtime_provenance_json, agent_runtime_kind,
                   agent_runtime_protocol_version, task_workspace_id, input_message_id,
                   control_plane_build_identity_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, ?)
                on conflict(idempotency_key) do nothing
                returning id
                """,
                (
                    job_id,
                    session_id,
                    idempotency_key,
                    project_code,
                    initial_status.value,
                    0,
                    max_retry_count,
                    source_channel,
                    source_connector_id,
                    external_event_id,
                    requester_id,
                    json.dumps(routing_context, ensure_ascii=False),
                    json.dumps(reply_route, ensure_ascii=False),
                    timestamp,
                    internal_user_id or None,
                    external_identity_id or None,
                    agent_definition_id or None,
                    agent_publication_id or None,
                    agent_revision,
                    agent_config_hash,
                    webhook_event_id or None,
                    webhook_trigger_id or None,
                    webhook_trigger_publication_id or None,
                    business_application_id or None,
                    business_application_code,
                    business_application_publication_id or None,
                    business_application_deployment_id or None,
                    business_application_route_id or None,
                    business_application_config_hash,
                    business_application_runtime_status,
                    json.dumps(
                        business_application_route_decision or {},
                        ensure_ascii=False,
                    ),
                    json.dumps(normalized_execution_policy, ensure_ascii=False),
                    json.dumps(model_runtime_provenance or {}, ensure_ascii=False),
                    agent_runtime_kind,
                    agent_runtime_protocol_version,
                    task_workspace_id or None,
                    json.dumps(
                        control_plane_build_identity,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            if inserted is None:
                concurrent = self.get_job_by_idempotency_key(idempotency_key)
                if concurrent is None:
                    raise NonRetryableExecutionError(
                        "Idempotent Agent job could not be resolved",
                        safe_message="无法确定已存在的任务",
                        error_code="job_idempotency_resolution_failed",
                    )
                return concurrent
            message_id = self.add_message(
                session_id=session_id,
                job_id=job_id,
                role="user",
                content=input_message,
                external_message_id=external_message_id,
                sender_id=requester_id,
                sender_display_name=requester_display_name,
                message_type=message_type,
                content_status=message_content_status,
                quoted_external_message_id=quoted_external_message_id,
            )
            message = self.database.execute_one(
                """
                select id
                  from agent_message
                 where id = ? and job_id = ? and session_id = ? and role = 'user'
                """,
                (message_id, job_id, session_id),
            )
            if message is None:
                raise NonRetryableExecutionError(
                    "Canonical Agent input message conflicts with an existing message",
                    safe_message="任务输入消息与已存在记录冲突",
                    error_code="job_input_message_conflict",
                )
            linked = self.database.execute_one(
                """
                update agent_job
                   set input_message_id = ?
                 where id = ? and input_message_id is null
                returning id
                """,
                (message_id, job_id),
            )
            if linked is None:
                raise NonRetryableExecutionError(
                    "Canonical Agent input message could not be linked",
                    safe_message="无法关联任务输入消息",
                    error_code="job_input_message_link_failed",
                )
        return self.get_job(job_id)

    def record_runtime_provenance(self, job_id: str, provenance: dict[str, Any]) -> None:
        allowed = {
            "runtime_kind",
            "runtime_version",
            "protocol_version",
            "sdk_version",
            "cli_version",
            "runtime_build_identity",
            "model_connection_revision_id",
            "model_connection_config_hash",
        }
        if set(provenance) != allowed:
            raise NonRetryableExecutionError(
                "Runtime provenance fields are invalid",
                safe_message="Runtime 来源信息无效",
                error_code="runtime_provenance_invalid",
            )
        self.database.execute(
            "update agent_job set model_runtime_provenance_json = ? where id = ?",
            (
                json.dumps(
                    sanitize_for_persistence(provenance),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                job_id,
            ),
        )

    def record_execution_policy_usage(
        self,
        job_id: str,
        *,
        tool_call_count: int,
        exhausted: bool,
    ) -> None:
        self.database.execute(
            """
            update agent_job
            set execution_policy_tool_call_count = ?,
                execution_policy_exhausted = ?
            where id = ?
            """,
            (max(int(tool_call_count), 0), int(exhausted), job_id),
        )

    def add_message(
        self,
        *,
        session_id: str,
        job_id: str | None,
        role: str,
        content: str,
        external_message_id: str = "",
        sender_id: str = "",
        sender_display_name: str = "",
        message_type: str = "text",
        content_status: str = "READY",
        safe_metadata: dict[str, Any] | None = None,
        quoted_external_message_id: str = "",
    ) -> str:
        if external_message_id:
            existing = self.database.execute_one(
                "select id from agent_message where session_id = ? and external_message_id = ?",
                (session_id, external_message_id),
            )
            if existing:
                return str(existing["id"])
        message_id = new_id("msg")
        sequence = self.database.execute_one(
            """
            update agent_session
            set message_sequence = message_sequence + 1, last_message_at = ?, updated_at = ?
            where id = ?
            returning message_sequence
            """,
            (now_iso(), now_iso(), session_id),
        )
        if not sequence:
            raise NotFound(f"Agent session not found: {session_id}")
        self.database.execute(
            """
            insert into agent_message
              (id, session_id, job_id, role, content, created_at, external_message_id,
               sender_id, sender_display_name, message_type, sequence_no, content_status,
               safe_metadata_json, quoted_external_message_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                job_id,
                role,
                content,
                now_iso(),
                external_message_id,
                sender_id,
                sender_display_name,
                message_type,
                int(sequence["message_sequence"]),
                content_status,
                json.dumps(safe_metadata or {}, ensure_ascii=False),
                quoted_external_message_id,
            ),
        )
        return message_id

    def add_attachment(
        self,
        *,
        message_id: str,
        job_id: str | None,
        task_workspace_id: str = "",
        ordinal: int,
        media_type: str,
        file_name: str,
        declared_mime: str = "",
        declared_size: int | None = None,
        credential_ciphertext: str = "",
        credential_type: str = "",
        credential_expires_at: str | None = None,
    ) -> MessageAttachment:
        attachment, _created = self.add_or_get_attachment(
            message_id=message_id,
            job_id=job_id,
            task_workspace_id=task_workspace_id,
            ordinal=ordinal,
            media_type=media_type,
            file_name=file_name,
            declared_mime=declared_mime,
            declared_size=declared_size,
            credential_ciphertext=credential_ciphertext,
            credential_type=credential_type,
            credential_expires_at=credential_expires_at,
        )
        return attachment

    def add_or_get_attachment(
        self,
        *,
        message_id: str,
        job_id: str | None,
        task_workspace_id: str = "",
        ordinal: int,
        media_type: str,
        file_name: str,
        declared_mime: str = "",
        declared_size: int | None = None,
        credential_ciphertext: str = "",
        credential_type: str = "",
        credential_expires_at: str | None = None,
    ) -> tuple[MessageAttachment, bool]:
        existing = self.database.execute_one(
            "select * from message_attachment where message_id = ? and ordinal = ?",
            (message_id, ordinal),
        )
        if existing:
            return self._attachment_from_row(existing), False
        attachment_id = new_id("attachment")
        timestamp = now_iso()
        inserted = self.database.execute(
            """
            insert into message_attachment
              (id, message_id, job_id, ordinal, media_type, file_name, declared_mime,
               declared_size, status, source_credential_ciphertext, source_credential_type,
               source_credential_expires_at, task_workspace_id, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?)
            on conflict(message_id, ordinal) do nothing
            returning *
            """,
            (
                attachment_id,
                message_id,
                job_id,
                ordinal,
                media_type,
                file_name,
                declared_mime,
                declared_size,
                credential_ciphertext,
                credential_type,
                credential_expires_at,
                task_workspace_id or None,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return self._attachment_from_row(inserted[0]), True
        existing = self.database.execute_one(
            "select * from message_attachment where message_id = ? and ordinal = ?",
            (message_id, ordinal),
        )
        if existing is None:
            raise RuntimeError("Attachment idempotency lookup failed")
        return self._attachment_from_row(existing), False

    def increment_attachment_retry(self, attachment_id: str) -> int:
        row = self.database.execute_one(
            """
            update message_attachment set retry_count = retry_count + 1, updated_at = ?
            where id = ? returning retry_count
            """,
            (now_iso(), attachment_id),
        )
        return int(row["retry_count"]) if row else 0

    def get_attachment(self, attachment_id: str) -> MessageAttachment:
        row = self.database.execute_one(
            "select * from message_attachment where id = ?", (attachment_id,)
        )
        if not row:
            raise NotFound(f"Message attachment not found: {attachment_id}")
        return self._attachment_from_row(row)

    def get_attachment_secret(self, attachment_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select source_credential_ciphertext, source_credential_type,
                   source_credential_expires_at
            from message_attachment where id = ?
            """,
            (attachment_id,),
        )
        if not row:
            raise NotFound(f"Message attachment not found: {attachment_id}")
        return row

    def list_attachments(self, job_id: str) -> list[MessageAttachment]:
        rows = self.database.execute(
            """
            select a.*
              from message_attachment a
              join agent_message m on m.id = a.message_id
             where a.job_id = ?
             order by m.sequence_no, a.ordinal, a.id
            """,
            (job_id,),
        )
        return [self._attachment_from_row(row) for row in rows]

    def attachment_session_context(self, attachment_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select m.session_id, s.source_connector_id, s.bot_identity,
                   s.source_channel, m.sender_id,
                   coalesce(a.task_workspace_id, j.task_workspace_id) as task_workspace_id,
                   coalesce(j.internal_user_id, m.sender_id, s.requester_id) as internal_user_id
              from message_attachment a
              join agent_message m on m.id = a.message_id
              join agent_session s on s.id = m.session_id
              left join agent_job j on j.id = a.job_id
             where a.id = ?
            """,
            (attachment_id,),
        )
        if row is None:
            raise NotFound(f"Message attachment not found: {attachment_id}")
        return row

    def list_staged_attachments(
        self,
        *,
        session_id: str,
        task_workspace_id: str,
    ) -> list[MessageAttachment]:
        rows = self.database.execute(
            """
            select a.*
              from message_attachment a
              join agent_message m on m.id = a.message_id
             where m.session_id = ? and a.task_workspace_id = ? and a.job_id is null
             order by m.sequence_no, a.ordinal, a.id
            """,
            (session_id, task_workspace_id),
        )
        return [self._attachment_from_row(row) for row in rows]

    def claim_staged_attachments(
        self,
        *,
        session_id: str,
        task_workspace_id: str,
        job_id: str,
        attachment_ids: tuple[str, ...] | list[str] = (),
    ) -> list[MessageAttachment]:
        ids = [item for item in attachment_ids if item and not str(item).startswith("current:")]
        if not ids:
            return []
        timestamp = now_iso()
        placeholders = ", ".join("?" for _ in ids)
        self.database.execute(
            f"""
            update message_attachment
               set job_id = ?, claimed_at = ?, updated_at = ?
             where job_id is null and task_workspace_id = ?
               and id in ({placeholders})
               and message_id in (
                 select id from agent_message where session_id = ?
               )
            """,
            (job_id, timestamp, timestamp, task_workspace_id, *ids, session_id),
        )
        return self.list_attachments(job_id)

    def list_file_turn_candidate_rows(
        self,
        *,
        session_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        if not session_id or not workspace_id:
            return []
        attachments = self.database.execute(
            """
            select coalesce(b.file_id, '') as file_id,
                   coalesce(b.version_id, '') as version_id,
                   coalesce(wf.logical_name, a.file_name) as display_name,
                   a.id as attachment_id,
                   coalesce(m.external_message_id, '') as message_external_id,
                   a.status as source_status,
                   a.readability_status as readability_status,
                   coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                     as error_code,
                   a.finished_at as source_ready_at,
                   f.source_received_at as source_received_at,
                   f.status as file_status,
                   v.status as version_status
              from message_attachment a
              join agent_message m on m.id = a.message_id
              left join message_attachment_file_binding b on b.attachment_id = a.id
              left join managed_file f on f.id = b.file_id
              left join managed_file_version v on v.id = b.version_id
              left join task_workspace_file wf
                on wf.workspace_id = a.task_workspace_id
               and wf.file_id = b.file_id
               and wf.status = 'ACTIVE'
             where m.session_id = ? and a.task_workspace_id = ?
             order by a.finished_at, a.id
            """,
            (session_id, workspace_id),
        )
        workspace_files = self.database.execute(
            """
            select wf.file_id as file_id,
                   wf.selected_version_id as version_id,
                   wf.logical_name as display_name,
                   '' as attachment_id,
                   '' as message_external_id,
                   case when v.status = 'AVAILABLE' then 'READY' else coalesce(v.status, '') end
                     as source_status,
                   coalesce((
                     select a.readability_status
                       from message_attachment_file_binding b
                       join message_attachment a on a.id = b.attachment_id
                      where b.version_id = wf.selected_version_id
                      order by a.readability_updated_at desc, a.id desc
                      limit 1
                   ), 'NOT_REQUIRED') as readability_status,
                   coalesce((
                     select coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                       from message_attachment_file_binding b
                       join message_attachment a on a.id = b.attachment_id
                      where b.version_id = wf.selected_version_id
                      order by a.readability_updated_at desc, a.id desc
                      limit 1
                   ), '') as error_code,
                   v.created_at as source_ready_at,
                   f.source_received_at as source_received_at,
                   f.status as file_status,
                   v.status as version_status
              from task_workspace_file wf
              join managed_file f on f.id = wf.file_id
              join managed_file_version v on v.id = wf.selected_version_id
             where wf.workspace_id = ? and wf.status = 'ACTIVE'
             order by v.created_at, wf.file_id
            """,
            (workspace_id,),
        )
        return self._merge_file_turn_rows([*attachments, *workspace_files])

    def list_session_retained_attachment_rows(
        self,
        *,
        session_id: str,
        now: str,
    ) -> list[dict[str, Any]]:
        if not session_id:
            return []
        rows = self.database.execute(
            """
            select coalesce(b.file_id, '') as file_id,
                   coalesce(b.version_id, '') as version_id,
                   coalesce(a.file_name, f.display_name, '') as display_name,
                   a.id as attachment_id,
                   coalesce(m.external_message_id, '') as message_external_id,
                   a.status as source_status,
                   a.readability_status as readability_status,
                   coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                     as error_code,
                   a.finished_at as source_ready_at,
                   f.source_received_at as source_received_at,
                   f.status as file_status,
                   v.status as version_status
              from message_attachment a
              join agent_message m on m.id = a.message_id
              join message_attachment_file_binding b on b.attachment_id = a.id
              join managed_file f on f.id = b.file_id
             join managed_file_version v on v.id = b.version_id
             where m.session_id = ?
               and a.status in ('READY', 'stored_not_interpreted')
               and a.expires_at is not null
               and a.expires_at > ?
               and b.retention_expires_at > ?
               and f.status = 'ACTIVE'
               and v.status in ('AVAILABLE', 'CONFLICT')
               and exists (
                 select 1 from file_retention_fact r
                  where r.version_id = v.id and r.expires_at > ?
               )
             order by a.created_at, a.id
            """,
            (session_id, now, now, now),
        )
        return [row for row in rows if row.get("file_id") and row.get("version_id")]

    @staticmethod
    def _merge_file_turn_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            payload = dict(row)
            file_id = str(payload.get("file_id") or "")
            version_id = str(payload.get("version_id") or "")
            attachment_id = str(payload.get("attachment_id") or "")
            key = (file_id, version_id, attachment_id or file_id)
            existing = merged.get(key)
            if existing is None:
                merged[key] = payload
                continue
            if not existing.get("message_external_id") and payload.get("message_external_id"):
                merged[key] = payload
        return list(merged.values())

    def record_file_readiness_blocked_turn(
        self,
        *,
        session_id: str,
        workspace_id: str,
        user_message_id: str,
        reason_code: str,
        version_ids: tuple[str, ...],
        expires_at: str,
    ) -> str:
        turn_id = new_id("file_turn")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into file_readiness_blocked_turn
              (id, session_id, workspace_id, user_message_id, reason_code,
               status, created_at, expires_at, notified_at)
            values (?, ?, ?, ?, ?, 'OPEN', ?, ?, null)
            """,
            (
                turn_id,
                session_id,
                workspace_id,
                user_message_id,
                reason_code,
                timestamp,
                expires_at,
            ),
        )
        for version_id in dict.fromkeys(version_ids):
            if not version_id:
                continue
            self.database.execute(
                """
                insert into file_readiness_blocked_turn_version
                  (turn_id, file_version_id)
                values (?, ?)
                """,
                (turn_id, version_id),
            )
        return turn_id

    def expire_file_readiness_blocked_turns(self, *, now: str | None = None) -> int:
        timestamp = now or now_iso()
        rows = self.database.execute(
            """
            update file_readiness_blocked_turn
               set status = 'EXPIRED'
             where status = 'OPEN'
               and (
                 expires_at <= ?
                 or workspace_id in (
                   select id from task_workspace where status <> 'ACTIVE'
                 )
               )
            returning id
            """,
            (timestamp,),
        )
        return len(rows)

    def list_ready_file_readiness_blocked_turns(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select t.id, t.session_id, t.workspace_id, t.user_message_id, t.reason_code
              from file_readiness_blocked_turn t
             where t.status = 'OPEN'
               and exists (
                 select 1 from file_readiness_blocked_turn_version v
                  where v.turn_id = t.id
               )
               and not exists (
                 select 1
                   from file_readiness_blocked_turn_version v
                  where v.turn_id = t.id
                    and coalesce((
                      select a.readability_status
                        from message_attachment_file_binding b
                        join message_attachment a on a.id = b.attachment_id
                       where b.version_id = v.file_version_id
                       order by a.readability_updated_at desc, a.id desc
                       limit 1
                    ), (
                      select case r.status
                               when 'AVAILABLE' then 'AVAILABLE'
                               when 'PARTIAL' then 'PARTIAL'
                               else r.status
                             end
                        from file_representation r
                       where r.source_version_id = v.file_version_id
                         and r.kind = 'MARKDOWN'
                       order by r.created_at desc
                       limit 1
                    ), 'PENDING') not in ('AVAILABLE', 'PARTIAL')
               )
             order by t.created_at, t.id
            """
        )
        return [dict(row) for row in rows]

    def list_blocked_turn_version_ids(self, turn_id: str) -> list[str]:
        rows = self.database.execute(
            """
            select file_version_id
              from file_readiness_blocked_turn_version
             where turn_id = ?
             order by file_version_id
            """,
            (turn_id,),
        )
        return [str(row["file_version_id"]) for row in rows]

    def mark_file_readiness_blocked_turn_notified(self, turn_id: str) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            update file_readiness_blocked_turn
               set status = 'NOTIFIED', notified_at = ?
             where id = ? and status = 'OPEN'
            """,
            (timestamp, turn_id),
        )

    def display_names_for_versions(self, version_ids: tuple[str, ...]) -> tuple[str, ...]:
        names: list[str] = []
        for version_id in version_ids:
            row = self.database.execute_one(
                """
                select coalesce(wf.logical_name, f.display_name, a.file_name, '') as display_name
                  from managed_file_version v
                  join managed_file f on f.id = v.file_id
                  left join task_workspace_file wf
                    on wf.file_id = v.file_id and wf.status = 'ACTIVE'
                  left join message_attachment_file_binding b on b.version_id = v.id
                  left join message_attachment a on a.id = b.attachment_id
                 where v.id = ?
                 limit 1
                """,
                (version_id,),
            )
            names.append(str((row or {}).get("display_name") or "文件"))
        return tuple(names)

    def refresh_file_turn_dependency_row(self, payload: dict[str, Any]) -> dict[str, Any]:
        refreshed = dict(payload)
        attachment_id = str(payload.get("attachment_id") or "")
        version_id = str(payload.get("version_id") or "")
        if attachment_id and not attachment_id.startswith("current:"):
            row = self.database.execute_one(
                """
                select a.status, a.readability_status, a.file_name,
                       coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                         as error_code,
                       coalesce(b.file_id, '') as file_id,
                       coalesce(b.version_id, '') as version_id
                  from message_attachment a
                  left join message_attachment_file_binding b on b.attachment_id = a.id
                 where a.id = ?
                """,
                (attachment_id,),
            )
            if row is not None:
                refreshed["source_status"] = str(row["status"] or "")
                refreshed["readability_status"] = str(
                    row.get("readability_status") or "NOT_REQUIRED"
                )
                refreshed["file_id"] = str(row.get("file_id") or refreshed.get("file_id") or "")
                refreshed["version_id"] = str(
                    row.get("version_id") or refreshed.get("version_id") or ""
                )
                refreshed["display_name"] = str(
                    row.get("file_name") or refreshed.get("display_name") or ""
                )
                refreshed["error_code"] = str(
                    row.get("error_code") or refreshed.get("error_code") or ""
                )
                return refreshed
        if version_id:
            row = self.database.execute_one(
                """
                select v.status as version_status,
                       coalesce((
                         select a.readability_status
                           from message_attachment_file_binding b
                           join message_attachment a on a.id = b.attachment_id
                          where b.version_id = v.id
                          order by a.readability_updated_at desc, a.id desc
                          limit 1
                       ), 'NOT_REQUIRED') as readability_status,
                       coalesce((
                         select coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                           from message_attachment_file_binding b
                           join message_attachment a on a.id = b.attachment_id
                          where b.version_id = v.id
                          order by a.readability_updated_at desc, a.id desc
                          limit 1
                       ), '') as error_code
                  from managed_file_version v
                 where v.id = ?
                """,
                (version_id,),
            )
            if row is not None:
                status = str(row.get("version_status") or "")
                refreshed["source_status"] = "READY" if status == "AVAILABLE" else status
                refreshed["readability_status"] = str(
                    row.get("readability_status") or "NOT_REQUIRED"
                )
                refreshed["error_code"] = str(
                    row.get("error_code") or refreshed.get("error_code") or ""
                )
        return refreshed

    def update_attachment(
        self,
        attachment_id: str,
        *,
        status: str,
        detected_mime: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        object_bucket: str | None = None,
        object_key: str | None = None,
        failure_code: str | None = None,
        clear_credential: bool = False,
    ) -> MessageAttachment:
        terminal = status in {"READY", "REJECTED", "FAILED", "stored_not_interpreted"}
        self.database.execute(
            """
            update message_attachment
            set status = ?, detected_mime = coalesce(?, detected_mime),
                size_bytes = coalesce(?, size_bytes), sha256 = coalesce(?, sha256),
                object_bucket = coalesce(?, object_bucket), object_key = coalesce(?, object_key),
                failure_code = coalesce(?, failure_code), updated_at = ?,
                finished_at = case when ? then ? else finished_at end,
                source_credential_ciphertext = case when ? then '' else source_credential_ciphertext end,
                source_credential_type = case when ? then '' else source_credential_type end,
                source_credential_expires_at = case when ? then null else source_credential_expires_at end
            where id = ?
            """,
            (
                status,
                detected_mime,
                size_bytes,
                sha256,
                object_bucket,
                object_key,
                failure_code,
                now_iso(),
                terminal,
                now_iso(),
                clear_credential or terminal,
                clear_credential or terminal,
                clear_credential or terminal,
                attachment_id,
            ),
        )
        return self.get_attachment(attachment_id)

    def list_messages(self, session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id, session_id, job_id, role, content, external_message_id, sender_id,
                   sender_display_name, message_type, sequence_no, content_status,
                   safe_metadata_json, created_at
            from agent_message where session_id = ?
            order by sequence_no desc limit ?
            """,
            (session_id, limit),
        )
        return [
            {**row, "safe_metadata": json_from_text(row.get("safe_metadata_json") or "{}")}
            for row in reversed(rows)
        ]

    def list_expired_attachments(self, now: str) -> list[MessageAttachment]:
        rows = self.database.execute(
            """
            select * from message_attachment
            where expires_at is not null and expires_at <= ? and object_key <> ''
              and status <> 'DELETED'
            order by expires_at, id
            """,
            (now,),
        )
        return [self._attachment_from_row(row) for row in rows]

    def mark_attachment_deleted(self, attachment_id: str) -> None:
        self.database.execute(
            """
            update message_attachment
            set status = 'DELETED', object_bucket = '', object_key = '', updated_at = ?,
                finished_at = coalesce(finished_at, ?)
            where id = ?
            """,
            (now_iso(), now_iso(), attachment_id),
        )

    def update_session_summary(
        self,
        session_id: str,
        *,
        expected_version: int,
        summary_text: str,
        through_sequence: int,
    ) -> bool:
        rows = self.database.execute(
            """
            update agent_session
            set summary_text = ?, summary_through_sequence = ?,
                summary_version = summary_version + 1, updated_at = ?
            where id = ? and summary_version = ?
            returning id
            """,
            (summary_text, through_sequence, now_iso(), session_id, expected_version),
        )
        return bool(rows)

    def add_step(self, *, job_id: str, step_type: str, title: str, content: str) -> str:
        step_id = new_id("step")
        self.database.execute(
            """
            insert into agent_step (id, job_id, step_type, title, content, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (step_id, job_id, step_type, title, content, now_iso()),
        )
        return step_id

    def add_artifact(
        self,
        *,
        job_id: str,
        artifact_type: str,
        name: str,
        content: str,
        file_path: str | None = None,
    ) -> str:
        artifact_id = new_id("artifact")
        self.database.execute(
            """
            insert into agent_artifact (id, job_id, artifact_type, name, content, file_path, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (artifact_id, job_id, artifact_type, name, content, file_path, now_iso()),
        )
        return artifact_id

    def ensure_artifact(
        self,
        *,
        artifact_id: str,
        job_id: str,
        artifact_type: str,
        name: str,
        content: str,
    ) -> str:
        """Create a deterministic artifact once and reject identity rebinding."""
        self.database.execute(
            """
            insert into agent_artifact
              (id, job_id, artifact_type, name, content, file_path, created_at)
            values (?, ?, ?, ?, ?, null, ?)
            on conflict(id) do nothing
            """,
            (artifact_id, job_id, artifact_type, name, content, now_iso()),
        )
        artifact = self.get_artifact(artifact_id)
        if (
            str(artifact["job_id"]) != job_id
            or str(artifact["artifact_type"]) != artifact_type
            or str(artifact["name"]) != name
            or str(artifact["content"]) != content
        ):
            raise NonRetryableExecutionError(
                "Deterministic Delivery artifact identity was rebound",
                safe_message="投递通知幂等身份冲突",
                error_code="delivery_artifact_idempotency_conflict",
            )
        return artifact_id

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select id, job_id, artifact_type, name, content, file_path, created_at
              from agent_artifact
             where id = ?
            """,
            (artifact_id,),
        )
        if row is None:
            raise NotFound(f"Agent artifact not found: {artifact_id}")
        return row

    def get_artifact_for_job(
        self,
        *,
        job_id: str,
        artifact_type: str,
        name: str,
    ) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select id, job_id, artifact_type, name, content, file_path, created_at
              from agent_artifact
             where job_id = ? and artifact_type = ? and name = ?
             order by created_at, id
             limit 1
            """,
            (job_id, artifact_type, name),
        )

    def get_job(self, job_id: str) -> AgentJob:
        row = self.database.execute_one(
            f"select {_JOB_COLUMNS_SQL} from agent_job where id = ?",
            (job_id,),
        )
        if not row:
            raise NotFound(f"Agent job not found: {job_id}")
        return self._job_from_row(row)

    def get_session(self, session_id: str) -> AgentSession:
        row = self.database.execute_one(
            f"select {_SESSION_COLUMNS_SQL} from agent_session where id = ?",
            (session_id,),
        )
        if not row:
            raise NotFound(f"Agent session not found: {session_id}")
        return AgentSession(
            id=row["id"],
            project_code=row["project_code"],
            source_channel=row.get("source_channel") or "",
            source_connector_id=row.get("source_connector_id") or "",
            external_conversation_id=row.get("external_conversation_id") or "",
            requester_id=row.get("requester_id") or "",
            requester_display_name=row.get("requester_display_name") or "",
            routing_context=json_from_text(row.get("routing_context_json") or "{}"),
            reply_route=json_from_text(row.get("reply_route_json") or "{}"),
            session_key=row.get("session_key") or f"legacy:{row['id']}",
            conversation_type=row.get("conversation_type") or "direct",
            bot_identity=row.get("bot_identity") or "",
            summary_text=row.get("summary_text") or "",
            summary_through_sequence=int(row.get("summary_through_sequence") or 0),
            summary_version=int(row.get("summary_version") or 0),
            external_identity_id=row.get("external_identity_id") or "",
            business_application_id=row.get("business_application_id") or "",
            business_application_code=row.get("business_application_code") or "",
            application_publication_id=row.get("application_publication_id") or "",
            execution_scope_hash=row.get("execution_scope_hash") or "",
            isolation_key_version=int(row.get("isolation_key_version") or 1),
            history_read_only=bool(row.get("history_read_only")),
            conversation_mode=row.get("conversation_mode") or "legacy",
            recent_message_limit=(
                int(row["recent_message_limit"])
                if row.get("recent_message_limit") is not None
                else None
            ),
            session_policy=json_from_text(row.get("session_policy_json") or "{}"),
        )

    def get_job_by_idempotency_key(self, idempotency_key: str) -> AgentJob | None:
        row = self.database.execute_one(
            f"select {_JOB_COLUMNS_SQL} from agent_job where idempotency_key = ?",
            (idempotency_key,),
        )
        return self._job_from_row(row) if row else None

    def get_job_detail(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            f"""
            select {_QUALIFIED_JOB_COLUMNS_SQL},
                   input_message.content as input_message_content,
                   input_message.content_status as input_message_content_status,
                   c.id as source_connector_record_id,
                   c.name as source_connector_name,
                   c.enabled as source_connector_enabled,
                   c.deleted as source_connector_deleted,
                   c.metadata as source_connector_metadata
              from agent_job j
              left join agent_message input_message
                on input_message.id = j.input_message_id
               and input_message.job_id = j.id
               and input_message.role = 'user'
              left join integration_connector c
                on c.id = j.source_connector_id
             where j.id = ?
            """,
            (job_id,),
        )
        if not row:
            raise NotFound(f"Agent job not found: {job_id}")
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "idempotency_key": row["idempotency_key"],
            "user_id": row.get("requester_id") or "",
            "project_code": row["project_code"],
            "source": row.get("source_channel") or "",
            "source_channel": row.get("source_channel") or "",
            "source_connector_id": row.get("source_connector_id") or "",
            **source_connector_projection(row),
            "external_event_id": row.get("external_event_id") or "",
            "requester_id": row.get("requester_id") or "",
            "internal_user_id": row.get("internal_user_id") or "",
            "external_identity_id": row.get("external_identity_id") or "",
            "agent_definition_id": row.get("agent_definition_id") or "",
            "agent_publication_id": row.get("agent_publication_id") or "",
            "agent_revision": (
                int(row["agent_revision"]) if row.get("agent_revision") is not None else None
            ),
            "agent_config_hash": row.get("agent_config_hash") or "",
            "business_application_id": row.get("business_application_id") or "",
            "business_application_code": row.get("business_application_code") or "",
            "business_application_publication_id": (
                row.get("business_application_publication_id") or ""
            ),
            "business_application_deployment_id": (
                row.get("business_application_deployment_id") or ""
            ),
            "business_application_route_id": (row.get("business_application_route_id") or ""),
            "business_application_config_hash": (row.get("business_application_config_hash") or ""),
            "business_application_runtime_status": (
                row.get("business_application_runtime_status") or "legacy_unattributed"
            ),
            "business_application_route_decision": json_from_text(
                row.get("business_application_route_decision_json") or "{}"
            ),
            "execution_policy": json_from_text(row.get("execution_policy_json") or "{}"),
            "model_runtime_provenance": json_from_text(
                row.get("model_runtime_provenance_json") or "{}"
            ),
            "agent_runtime_kind": row.get("agent_runtime_kind") or "python-v1",
            "agent_runtime_protocol_version": (row.get("agent_runtime_protocol_version") or "1.5"),
            "tool_call_count": int(row.get("execution_policy_tool_call_count") or 0),
            "execution_policy_exhausted": bool(row.get("execution_policy_exhausted") or False),
            "routing_context": json_from_text(row.get("routing_context_json") or "{}"),
            "reply_route": json_from_text(row.get("reply_route_json") or "{}"),
            "user_message": row.get("input_message_content"),
            "input_message_id": row.get("input_message_id") or "",
            "input_message_state": (
                "available"
                if row.get("input_message_content") is not None
                else "legacy_message_unavailable"
            ),
            "status": row["status"],
            "priority": int(row["priority"]),
            "retry_count": int(row["retry_count"]),
            "max_retry_count": int(row["max_retry_count"]),
            "result": row.get("result"),
            "error_message": row.get("error_message"),
            "last_error_code": row.get("last_error_code") or "",
            "last_error_at": row.get("last_error_at"),
            "next_retry_at": row.get("next_retry_at"),
            "created_at": row["created_at"],
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
        }

    def list_steps(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        return self.database.execute(
            """
            select id, job_id, step_type, title, content, created_at
            from agent_step
            where job_id = ?
            order by created_at, id
            """,
            (job_id,),
        )

    def claim_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        recover_runtime_running: bool = False,
    ) -> AgentJob | None:
        timestamp = now_iso()
        row = self.database.execute_one(
            f"""
            update agent_job
            set status = ?, started_at = coalesce(started_at, ?), locked_at = ?, locked_by = ?,
                next_retry_at = null
            where id = ?
              and (
                status = ?
                or (status = ? and next_retry_at is not null and next_retry_at <= ?)
                or (? = 1 and status = ? and agent_runtime_kind = 'python-v1')
              )
            returning {_JOB_COLUMNS_SQL}
            """,
            (
                JobStatus.RUNNING.value,
                timestamp,
                timestamp,
                worker_id,
                job_id,
                JobStatus.PENDING.value,
                JobStatus.RETRY_WAIT.value,
                timestamp,
                int(recover_runtime_running),
                JobStatus.RUNNING.value,
            ),
        )
        return self._job_from_row(row) if row else None

    def transition_job(
        self,
        *,
        job_id: str,
        target: JobStatus,
        result: str | None = None,
        error_message: str | None = None,
        error_code: str = "",
    ) -> AgentJob:
        job = self.get_job(job_id)
        if not can_transition(job.status, target):
            raise NonRetryableExecutionError(
                f"Invalid job transition {job.status.value} -> {target.value}",
                safe_message="任务状态不能这样变更",
            )
        finished_at = (
            now_iso()
            if target in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.TIMEOUT}
            else None
        )
        row = self.database.execute_one(
            f"""
            update agent_job
            set status = ?, result = coalesce(?, result), error_message = coalesce(?, error_message),
                last_error_code = case when ? <> '' then ? else last_error_code end,
                last_error_at = coalesce(?, last_error_at),
                next_retry_at = null,
                finished_at = coalesce(?, finished_at), locked_at = null, locked_by = null
            where id = ? and status = ?
            returning {_JOB_COLUMNS_SQL}
            """,
            (
                target.value,
                result,
                error_message,
                error_code,
                error_code,
                now_iso() if error_message is not None else None,
                finished_at,
                job_id,
                job.status.value,
            ),
        )
        if not row:
            raise NonRetryableExecutionError(
                "Job changed while transitioning",
                safe_message="任务状态已被其他操作修改，请刷新后重试",
                error_code="job_transition_conflict",
            )
        return self._job_from_row(row)

    def schedule_retry(
        self,
        job_id: str,
        *,
        error_message: str,
        error_code: str,
        next_retry_at: str,
    ) -> AgentJob:
        row = self.database.execute_one(
            f"""
            update agent_job
            set retry_count = retry_count + 1, error_message = ?, last_error_code = ?,
                last_error_at = ?, next_retry_at = ?, status = ?, locked_at = null, locked_by = null
            where id = ? and status = ? and retry_count < max_retry_count
            returning {_JOB_COLUMNS_SQL}
            """,
            (
                error_message,
                error_code,
                now_iso(),
                next_retry_at,
                JobStatus.RETRY_WAIT.value,
                job_id,
                JobStatus.RUNNING.value,
            ),
        )
        if not row:
            raise NonRetryableExecutionError(
                "Job is not eligible for retry scheduling",
                safe_message="任务重试状态已被其他操作修改，请刷新后重试",
                error_code="job_retry_conflict",
            )
        return self._job_from_row(row)

    def list_stranded_retry_jobs(
        self,
        job_ids: list[str] | None = None,
        *,
        lock_stale_before: str | None = None,
    ) -> list[AgentJob]:
        parameters: list[Any] = [JobStatus.PENDING.value]
        lock_filter = " and (locked_at is null or locked_by is null)"
        if lock_stale_before is not None:
            lock_filter = " and (locked_at is null or locked_by is null or locked_at <= ?)"
            parameters.append(lock_stale_before)
        job_filter = ""
        if job_ids:
            placeholders = ", ".join("?" for _ in job_ids)
            job_filter = f" and id in ({placeholders})"
            parameters.extend(job_ids)
        rows = self.database.execute(
            f"""
            select {_JOB_COLUMNS_SQL} from agent_job
            where status = ? and retry_count > 0 and error_message is not null
              and result is null {lock_filter}
              {job_filter}
            order by created_at, id
            """,
            tuple(parameters),
        )
        return [self._job_from_row(row) for row in rows]

    def list_overdue_retry_wait_jobs(
        self, *, before: str, job_ids: list[str] | None = None
    ) -> list[AgentJob]:
        parameters: list[Any] = [JobStatus.RETRY_WAIT.value, before]
        job_filter = ""
        if job_ids:
            placeholders = ", ".join("?" for _ in job_ids)
            job_filter = f" and id in ({placeholders})"
            parameters.extend(job_ids)
        rows = self.database.execute(
            f"""
            select {_JOB_COLUMNS_SQL} from agent_job
            where status = ? and retry_count > 0 and result is null
              and next_retry_at is not null and next_retry_at <= ?
              {job_filter}
            order by next_retry_at, id
            """,
            tuple(parameters),
        )
        return [self._job_from_row(row) for row in rows]

    def recover_stranded_retry(
        self,
        job_id: str,
        *,
        next_retry_at: str,
        error_code: str = "legacy_retry_recovered",
        lock_stale_before: str | None = None,
    ) -> AgentJob | None:
        lock_filter = " and (locked_at is null or locked_by is null)"
        parameters: list[Any] = [
            JobStatus.RETRY_WAIT.value,
            error_code,
            now_iso(),
            next_retry_at,
            job_id,
            JobStatus.PENDING.value,
        ]
        if lock_stale_before is not None:
            lock_filter = " and (locked_at is null or locked_by is null or locked_at <= ?)"
            parameters.append(lock_stale_before)
        row = self.database.execute_one(
            f"""
            update agent_job
            set status = ?, last_error_code = case when last_error_code = '' then ? else last_error_code end,
                last_error_at = coalesce(last_error_at, ?), next_retry_at = ?,
                locked_at = null, locked_by = null
            where id = ? and status = ? and retry_count > 0 and error_message is not null
              and result is null {lock_filter}
            returning {_JOB_COLUMNS_SQL}
            """,
            tuple(parameters),
        )
        return self._job_from_row(row) if row else None

    def count_rows(self, table: str) -> int:
        row = self.database.execute_one(f"select count(*) as count from {table}")
        return int(row["count"]) if row else 0

    def _attachment_from_row(self, row: dict[str, Any]) -> MessageAttachment:
        return MessageAttachment(
            id=str(row["id"]),
            message_id=str(row["message_id"]),
            job_id=str(row.get("job_id") or ""),
            ordinal=int(row["ordinal"]),
            media_type=str(row["media_type"]),
            file_name=str(row["file_name"]),
            declared_mime=str(row.get("declared_mime") or ""),
            detected_mime=str(row.get("detected_mime") or ""),
            declared_size=int(row["declared_size"])
            if row.get("declared_size") is not None
            else None,
            size_bytes=int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
            sha256=str(row.get("sha256") or ""),
            object_bucket=str(row.get("object_bucket") or ""),
            object_key=str(row.get("object_key") or ""),
            status=str(row["status"]),
            task_workspace_id=str(row.get("task_workspace_id") or ""),
            claimed_at=(str(row["claimed_at"]) if row.get("claimed_at") else None),
            failure_code=str(row.get("failure_code") or ""),
            readability_status=str(row.get("readability_status") or "NOT_REQUIRED"),
            file_processing_run_id=str(row.get("file_processing_run_id") or ""),
            readability_error_code=str(row.get("readability_error_code") or ""),
            readability_updated_at=(
                str(row["readability_updated_at"]) if row.get("readability_updated_at") else None
            ),
        )

    def _job_from_row(self, row: dict[str, Any]) -> AgentJob:
        input_message_id = str(row.get("input_message_id") or "")
        input_message: str | None = None
        if input_message_id:
            message = self.database.execute_one(
                """
                select content
                  from agent_message
                 where id = ? and job_id = ? and session_id = ? and role = 'user'
                """,
                (input_message_id, row["id"], row["session_id"]),
            )
            if message is not None:
                input_message = str(message["content"])
        return AgentJob(
            id=row["id"],
            session_id=row["session_id"],
            idempotency_key=row["idempotency_key"],
            project_code=row["project_code"],
            source_channel=row.get("source_channel") or "",
            source_connector_id=row.get("source_connector_id") or "",
            requester_id=row.get("requester_id") or "",
            input_message_id=input_message_id,
            input_message=input_message,
            input_message_state=(
                "available" if input_message is not None else "legacy_message_unavailable"
            ),
            status=JobStatus(row["status"]),
            retry_count=int(row["retry_count"]),
            max_retry_count=int(row["max_retry_count"]),
            result=row.get("result"),
            error_message=row.get("error_message"),
            last_error_code=row.get("last_error_code") or "",
            last_error_at=row.get("last_error_at"),
            next_retry_at=row.get("next_retry_at"),
            external_event_id=row.get("external_event_id") or "",
            routing_context=json_from_text(row.get("routing_context_json") or "{}"),
            reply_route=json_from_text(row.get("reply_route_json") or "{}"),
            internal_user_id=row.get("internal_user_id") or "",
            external_identity_id=row.get("external_identity_id") or "",
            agent_definition_id=row.get("agent_definition_id") or "",
            agent_publication_id=row.get("agent_publication_id") or "",
            agent_revision=(
                int(row["agent_revision"]) if row.get("agent_revision") is not None else None
            ),
            agent_config_hash=row.get("agent_config_hash") or "",
            webhook_event_id=row.get("webhook_event_id") or "",
            webhook_trigger_id=row.get("webhook_trigger_id") or "",
            webhook_trigger_publication_id=row.get("webhook_trigger_publication_id") or "",
            business_application_id=row.get("business_application_id") or "",
            business_application_code=row.get("business_application_code") or "",
            business_application_publication_id=(
                row.get("business_application_publication_id") or ""
            ),
            business_application_deployment_id=(
                row.get("business_application_deployment_id") or ""
            ),
            business_application_route_id=(row.get("business_application_route_id") or ""),
            business_application_config_hash=(row.get("business_application_config_hash") or ""),
            business_application_runtime_status=(
                row.get("business_application_runtime_status") or "legacy_unattributed"
            ),
            business_application_route_decision=json_from_text(
                row.get("business_application_route_decision_json") or "{}"
            ),
            execution_policy=json_from_text(row.get("execution_policy_json") or "{}"),
            execution_policy_tool_call_count=int(row.get("execution_policy_tool_call_count") or 0),
            execution_policy_exhausted=bool(row.get("execution_policy_exhausted") or False),
            model_runtime_provenance=json_from_text(
                row.get("model_runtime_provenance_json") or "{}"
            ),
            agent_runtime_kind=row.get("agent_runtime_kind") or "python-v1",
            agent_runtime_protocol_version=(row.get("agent_runtime_protocol_version") or "1.5"),
            task_workspace_id=str(row.get("task_workspace_id") or ""),
            control_plane_build_identity=json_from_text(
                row.get("control_plane_build_identity_json") or "{}"
            ),
            tool_contract_status=str(row.get("tool_contract_status") or "NOT_OBSERVED"),
            tool_contract_last_invocation_id=str(row.get("tool_contract_last_invocation_id") or ""),
            tool_contract_observation_hash=str(row.get("tool_contract_observation_hash") or ""),
            prompt_template_version=str(row.get("prompt_template_version") or ""),
            prompt_contract_hash=str(row.get("prompt_contract_hash") or ""),
        )


class AuditRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self,
        *,
        event_type: str,
        status: str,
        summary: str,
        job_id: str | None = None,
        actor_id: str | None = None,
        payload_summary: dict[str, Any] | None = None,
    ) -> str:
        audit_id = new_id("audit")
        safe_summary = redact_sensitive_text(summary)
        safe_payload = sanitize_for_persistence(payload_summary or {})
        persisted_job_id = (job_id or "").strip() or None
        self.database.execute(
            """
            insert into audit_event
              (id, job_id, event_type, actor_id, status, summary, payload_summary, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                persisted_job_id,
                event_type,
                actor_id,
                status,
                safe_summary,
                json.dumps(safe_payload, ensure_ascii=False),
                now_iso(),
            ),
        )
        return audit_id

    def list_for_job(self, job_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            "select * from audit_event where job_id = ? order by created_at", (job_id,)
        )

    def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id, job_id, event_type, actor_id, status, summary,
                   payload_summary, created_at
            from audit_event
            order by created_at desc
            limit ?
            """,
            (max(1, min(limit, 1000)),),
        )
        for row in rows:
            row["payload_summary"] = self._safe_payload(str(row.get("payload_summary") or "{}"))
        return rows

    @staticmethod
    def _safe_payload(value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        sanitized = sanitize_for_persistence(parsed)
        return sanitized if isinstance(sanitized, dict) else {}


class ConfigurationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_connector(self, connector_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from integration_connector where id = ? and deleted = 0",
            (connector_id,),
        )
        if not row:
            return None
        row["metadata"] = json_from_text(str(row.get("metadata") or "{}"))
        return row
