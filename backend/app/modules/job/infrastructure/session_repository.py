from __future__ import annotations

import json
from typing import Any

from app.modules.job.domain.agent_job import AgentSession
from app.modules.job.infrastructure.persistence_values import json_from_text, new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound

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


_SESSION_COLUMNS_SQL = ", ".join(_SESSION_COLUMN_NAMES)


class SessionRepository:
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
