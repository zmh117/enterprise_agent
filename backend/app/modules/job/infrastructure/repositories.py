from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.job.domain.agent_job import AgentJob, AgentSession, MessageAttachment
from app.modules.job.domain.job_status import JobStatus, can_transition
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AgentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_session(
        self,
        *,
        dingding_conversation_id: str,
        dingding_user_id: str,
        source: str,
        project_code: str,
        source_channel: str | None = None,
        source_connector_id: str = "",
        external_conversation_id: str | None = None,
        requester_id: str | None = None,
        requester_display_name: str = "",
        routing_context: dict[str, Any] | None = None,
        reply_route: dict[str, Any] | None = None,
        session_key: str = "",
        conversation_type: str = "direct",
        bot_identity: str = "",
        external_identity_id: str = "",
    ) -> AgentSession:
        session_id = new_id("session")
        timestamp = now_iso()
        source_channel = source_channel or source
        external_conversation_id = external_conversation_id or dingding_conversation_id
        requester_id = requester_id or dingding_user_id
        routing_context = routing_context or {"project_code": project_code}
        reply_route = reply_route or {"type": "dingtalk_conversation"}
        session_key = session_key or f"legacy:{session_id}"
        self.database.execute(
            """
            insert into agent_session
              (id, dingding_conversation_id, dingding_user_id, source, project_code,
               source_channel, source_connector_id, external_conversation_id, requester_id,
               requester_display_name, routing_context_json, reply_route_json, created_at, updated_at,
               session_key, conversation_type, bot_identity, external_identity_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(session_key) do nothing
            """,
            (
                session_id,
                dingding_conversation_id,
                dingding_user_id,
                source,
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
            ),
        )
        row = self.database.execute_one("select id from agent_session where session_key = ?", (session_key,))
        if not row:
            raise NonRetryableExecutionError(
                "Agent session could not be resolved", safe_message="Agent session could not be resolved"
            )
        return self.get_session(str(row["id"]))

    def create_job(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        user_id: str,
        project_code: str,
        source: str,
        user_message: str,
        max_retry_count: int,
        source_channel: str | None = None,
        source_connector_id: str = "",
        external_event_id: str = "",
        requester_id: str | None = None,
        routing_context: dict[str, Any] | None = None,
        reply_route: dict[str, Any] | None = None,
        initial_status: JobStatus = JobStatus.PENDING,
        internal_user_id: str = "",
        external_identity_id: str = "",
        agent_definition_id: str = "",
        agent_publication_id: str = "",
        agent_revision: int | None = None,
        agent_config_hash: str = "",
    ) -> AgentJob:
        existing = self.get_job_by_idempotency_key(idempotency_key)
        if existing:
            return existing
        job_id = new_id("job")
        timestamp = now_iso()
        source_channel = source_channel or source
        requester_id = requester_id or user_id
        routing_context = routing_context or {"project_code": project_code}
        reply_route = reply_route or {"type": "dingtalk_conversation"}
        self.database.execute(
            """
            insert into agent_job
              (id, session_id, idempotency_key, user_id, project_code, source, user_message,
               status, retry_count, max_retry_count, source_channel, source_connector_id,
               external_event_id, requester_id, routing_context_json, reply_route_json, created_at,
               internal_user_id, external_identity_id, agent_definition_id,
               agent_publication_id, agent_revision, agent_config_hash)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                session_id,
                idempotency_key,
                user_id,
                project_code,
                source,
                user_message,
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
            ),
        )
        return self.get_job(job_id)

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
               safe_metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        return message_id

    def add_attachment(
        self,
        *,
        message_id: str,
        job_id: str,
        ordinal: int,
        media_type: str,
        file_name: str,
        declared_mime: str = "",
        declared_size: int | None = None,
        credential_ciphertext: str = "",
        credential_type: str = "",
        credential_expires_at: str | None = None,
    ) -> MessageAttachment:
        existing = self.database.execute_one(
            "select * from message_attachment where message_id = ? and ordinal = ?",
            (message_id, ordinal),
        )
        if existing:
            return self._attachment_from_row(existing)
        attachment_id = new_id("attachment")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into message_attachment
              (id, message_id, job_id, ordinal, media_type, file_name, declared_mime,
               declared_size, status, source_credential_ciphertext, source_credential_type,
               source_credential_expires_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)
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
                timestamp,
                timestamp,
            ),
        )
        return self.get_attachment(attachment_id)

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
        row = self.database.execute_one("select * from message_attachment where id = ?", (attachment_id,))
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
            "select * from message_attachment where job_id = ? order by ordinal", (job_id,)
        )
        return [self._attachment_from_row(row) for row in rows]

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

    def save_attachment_content(
        self,
        *,
        attachment_id: str,
        plain_text: str,
        segments: list[dict[str, Any]],
        parser_version: str,
        truncated: bool,
    ) -> None:
        content_id = new_id("attachment_content")
        self.database.execute(
            """
            insert into attachment_content
              (id, attachment_id, plain_text, segments_json, parser_version,
               char_count, truncated, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(attachment_id) do update set
              plain_text = excluded.plain_text,
              segments_json = excluded.segments_json,
              parser_version = excluded.parser_version,
              char_count = excluded.char_count,
              truncated = excluded.truncated
            """,
            (
                content_id,
                attachment_id,
                plain_text,
                json.dumps(segments, ensure_ascii=False),
                parser_version,
                len(plain_text),
                int(truncated),
                now_iso(),
            ),
        )

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
            {**row, "safe_metadata": self._json_from_text(row.get("safe_metadata_json") or "{}")}
            for row in reversed(rows)
        ]

    def list_attachment_context(self, job_id: str, *, max_chars: int) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select a.id, a.file_name, a.status, a.failure_code, c.plain_text, c.truncated
            from message_attachment a
            left join attachment_content c on c.attachment_id = a.id
            where a.job_id = ? order by a.ordinal
            """,
            (job_id,),
        )
        return [
            {
                "attachment_id": row["id"],
                "file_name": row["file_name"],
                "status": row["status"],
                "failure_code": row.get("failure_code") or "",
                "text": str(row.get("plain_text") or "")[:max_chars],
                "truncated": bool(row.get("truncated"))
                or len(str(row.get("plain_text") or "")) > max_chars,
            }
            for row in rows
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
        self.database.execute(
            "delete from attachment_content where attachment_id = ?", (attachment_id,)
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

    def add_tool_call(
        self,
        *,
        job_id: str,
        tool_name: str,
        request_payload: dict[str, Any],
        response_summary: dict[str, Any] | str,
        status: str,
        duration_ms: int,
        risk_level: str,
        audit_id: str | None = None,
    ) -> str:
        tool_call_id = new_id("tool")
        response = (
            response_summary
            if isinstance(response_summary, str)
            else json.dumps(response_summary, ensure_ascii=False)
        )
        self.database.execute(
            """
            insert into agent_tool_call
              (id, job_id, tool_name, request_payload, response_summary, status,
               duration_ms, risk_level, audit_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool_call_id,
                job_id,
                tool_name,
                json.dumps(request_payload, ensure_ascii=False),
                response,
                status,
                duration_ms,
                risk_level,
                audit_id,
                now_iso(),
            ),
        )
        return tool_call_id

    def get_job(self, job_id: str) -> AgentJob:
        row = self.database.execute_one("select * from agent_job where id = ?", (job_id,))
        if not row:
            raise NotFound(f"Agent job not found: {job_id}")
        return self._job_from_row(row)

    def job_allows_tool(self, job_id: str, tool_name: str) -> bool:
        row = self.database.execute_one(
            """
            select j.agent_publication_id,
                   exists(
                     select 1 from agent_tool_binding b
                     where b.publication_id = j.agent_publication_id
                       and b.tool_name = ?
                   ) as assigned
            from agent_job j
            where j.id = ?
            """,
            (tool_name, job_id),
        )
        if not row:
            raise NotFound(f"Agent job not found: {job_id}")
        if not row.get("agent_publication_id"):
            return True
        return bool(row.get("assigned"))

    def get_session(self, session_id: str) -> AgentSession:
        row = self.database.execute_one("select * from agent_session where id = ?", (session_id,))
        if not row:
            raise NotFound(f"Agent session not found: {session_id}")
        return AgentSession(
            id=row["id"],
            dingding_conversation_id=row["dingding_conversation_id"],
            dingding_user_id=row["dingding_user_id"],
            source=row["source"],
            project_code=row["project_code"],
            source_channel=row.get("source_channel") or row["source"],
            source_connector_id=row.get("source_connector_id") or "",
            external_conversation_id=row.get("external_conversation_id")
            or row["dingding_conversation_id"],
            requester_id=row.get("requester_id") or row["dingding_user_id"],
            requester_display_name=row.get("requester_display_name") or "",
            routing_context=self._json_from_text(row.get("routing_context_json") or "{}"),
            reply_route=self._json_from_text(row.get("reply_route_json") or "{}"),
            session_key=row.get("session_key") or f"legacy:{row['id']}",
            conversation_type=row.get("conversation_type") or "direct",
            bot_identity=row.get("bot_identity") or "",
            summary_text=row.get("summary_text") or "",
            summary_through_sequence=int(row.get("summary_through_sequence") or 0),
            summary_version=int(row.get("summary_version") or 0),
            external_identity_id=row.get("external_identity_id") or "",
        )

    def get_job_by_idempotency_key(self, idempotency_key: str) -> AgentJob | None:
        row = self.database.execute_one(
            "select * from agent_job where idempotency_key = ?", (idempotency_key,)
        )
        return self._job_from_row(row) if row else None

    def get_job_detail(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from agent_job where id = ?", (job_id,))
        if not row:
            raise NotFound(f"Agent job not found: {job_id}")
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "idempotency_key": row["idempotency_key"],
            "user_id": row["user_id"],
            "project_code": row["project_code"],
            "source": row["source"],
            "source_channel": row.get("source_channel") or row["source"],
            "source_connector_id": row.get("source_connector_id") or "",
            "external_event_id": row.get("external_event_id") or "",
            "requester_id": row.get("requester_id") or row["user_id"],
            "internal_user_id": row.get("internal_user_id") or "",
            "external_identity_id": row.get("external_identity_id") or "",
            "agent_definition_id": row.get("agent_definition_id") or "",
            "agent_publication_id": row.get("agent_publication_id") or "",
            "agent_revision": (
                int(row["agent_revision"]) if row.get("agent_revision") is not None else None
            ),
            "agent_config_hash": row.get("agent_config_hash") or "",
            "routing_context": self._json_from_text(row.get("routing_context_json") or "{}"),
            "reply_route": self._json_from_text(row.get("reply_route_json") or "{}"),
            "user_message": row["user_message"],
            "status": row["status"],
            "priority": int(row["priority"]),
            "retry_count": int(row["retry_count"]),
            "max_retry_count": int(row["max_retry_count"]),
            "result": row.get("result"),
            "error_message": row.get("error_message"),
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

    def list_tool_calls(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        rows = self.database.execute(
            """
            select id, job_id, tool_name, request_payload, response_summary,
                   status, duration_ms, risk_level, audit_id, created_at
            from agent_tool_call
            where job_id = ?
            order by created_at, id
            """,
            (job_id,),
        )
        return [self._tool_call_from_row(row) for row in rows]

    def add_delivery_attempt(
        self,
        *,
        job_id: str,
        route_type: str,
        connector_id: str,
        target_summary: dict[str, Any],
        status: str,
        error_message: str | None = None,
    ) -> str:
        attempt_id = new_id("delivery")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into delivery_attempt
              (id, job_id, route_type, connector_id, target_summary, status,
               error_message, created_at, finished_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                job_id,
                route_type,
                connector_id,
                json.dumps(target_summary, ensure_ascii=False),
                status,
                error_message,
                timestamp,
                timestamp if status in {"SUCCEEDED", "FAILED", "SKIPPED"} else None,
            ),
        )
        return attempt_id

    def update_delivery_attempt(
        self, attempt_id: str, *, status: str, error_message: str | None = None
    ) -> None:
        self.database.execute(
            """
            update delivery_attempt
            set status = ?, error_message = ?, finished_at = ?
            where id = ?
            """,
            (
                status,
                error_message,
                now_iso() if status in {"SUCCEEDED", "FAILED", "SKIPPED"} else None,
                attempt_id,
            ),
        )

    def add_delivery_chunk(
        self,
        *,
        attempt_id: str,
        chunk_index: int,
        chunk_count: int,
        status: str,
        payload_summary: dict[str, Any],
        error_message: str | None = None,
    ) -> str:
        chunk_id = new_id("chunk")
        self.database.execute(
            """
            insert into delivery_chunk
              (id, attempt_id, chunk_index, chunk_count, status, payload_summary,
               error_message, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                attempt_id,
                chunk_index,
                chunk_count,
                status,
                json.dumps(payload_summary, ensure_ascii=False),
                error_message,
                now_iso(),
            ),
        )
        return chunk_id

    def list_delivery_attempts(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        rows = self.database.execute(
            """
            select id, job_id, route_type, connector_id, target_summary, status,
                   error_message, created_at, finished_at
            from delivery_attempt
            where job_id = ?
            order by created_at, id
            """,
            (job_id,),
        )
        return [
            {
                **row,
                "target_summary": self._json_from_text(row.get("target_summary") or "{}"),
            }
            for row in rows
        ]

    def list_delivery_chunks(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        rows = self.database.execute(
            """
            select c.id, c.attempt_id, a.job_id, c.chunk_index, c.chunk_count, c.status,
                   c.payload_summary, c.error_message, c.created_at
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
                "payload_summary": self._json_from_text(row.get("payload_summary") or "{}"),
            }
            for row in rows
        ]

    def claim_job(self, job_id: str, worker_id: str) -> AgentJob | None:
        job = self.get_job(job_id)
        if job.status != JobStatus.PENDING:
            return None
        timestamp = now_iso()
        self.database.execute(
            """
            update agent_job
            set status = ?, started_at = ?, locked_at = ?, locked_by = ?
            where id = ? and status = ?
            """,
            (
                JobStatus.RUNNING.value,
                timestamp,
                timestamp,
                worker_id,
                job_id,
                JobStatus.PENDING.value,
            ),
        )
        claimed = self.get_job(job_id)
        return claimed if claimed.status == JobStatus.RUNNING else None

    def transition_job(
        self,
        *,
        job_id: str,
        target: JobStatus,
        result: str | None = None,
        error_message: str | None = None,
    ) -> AgentJob:
        job = self.get_job(job_id)
        if not can_transition(job.status, target):
            raise NonRetryableExecutionError(
                f"Invalid job transition {job.status.value} -> {target.value}",
                safe_message="Invalid job status transition",
            )
        finished_at = (
            now_iso()
            if target in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.TIMEOUT}
            else None
        )
        self.database.execute(
            """
            update agent_job
            set status = ?, result = coalesce(?, result), error_message = coalesce(?, error_message),
                finished_at = coalesce(?, finished_at)
            where id = ?
            """,
            (target.value, result, error_message, finished_at, job_id),
        )
        return self.get_job(job_id)

    def increment_retry(self, job_id: str, error_message: str) -> AgentJob:
        self.database.execute(
            """
            update agent_job
            set retry_count = retry_count + 1, error_message = ?, status = ?
            where id = ?
            """,
            (error_message, JobStatus.PENDING.value, job_id),
        )
        return self.get_job(job_id)

    def count_rows(self, table: str) -> int:
        row = self.database.execute_one(f"select count(*) as count from {table}")
        return int(row["count"]) if row else 0

    def _attachment_from_row(self, row: dict[str, Any]) -> MessageAttachment:
        return MessageAttachment(
            id=str(row["id"]),
            message_id=str(row["message_id"]),
            job_id=str(row["job_id"]),
            ordinal=int(row["ordinal"]),
            media_type=str(row["media_type"]),
            file_name=str(row["file_name"]),
            declared_mime=str(row.get("declared_mime") or ""),
            detected_mime=str(row.get("detected_mime") or ""),
            declared_size=int(row["declared_size"]) if row.get("declared_size") is not None else None,
            size_bytes=int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
            sha256=str(row.get("sha256") or ""),
            object_bucket=str(row.get("object_bucket") or ""),
            object_key=str(row.get("object_key") or ""),
            status=str(row["status"]),
            failure_code=str(row.get("failure_code") or ""),
        )

    def _job_from_row(self, row: dict[str, Any]) -> AgentJob:
        return AgentJob(
            id=row["id"],
            session_id=row["session_id"],
            idempotency_key=row["idempotency_key"],
            user_id=row["user_id"],
            project_code=row["project_code"],
            source=row["source"],
            user_message=row["user_message"],
            status=JobStatus(row["status"]),
            retry_count=int(row["retry_count"]),
            max_retry_count=int(row["max_retry_count"]),
            result=row.get("result"),
            error_message=row.get("error_message"),
            source_channel=row.get("source_channel") or row["source"],
            source_connector_id=row.get("source_connector_id") or "",
            external_event_id=row.get("external_event_id") or "",
            requester_id=row.get("requester_id") or row["user_id"],
            routing_context=self._json_from_text(row.get("routing_context_json") or "{}"),
            reply_route=self._json_from_text(row.get("reply_route_json") or "{}"),
            internal_user_id=row.get("internal_user_id") or "",
            external_identity_id=row.get("external_identity_id") or "",
            agent_definition_id=row.get("agent_definition_id") or "",
            agent_publication_id=row.get("agent_publication_id") or "",
            agent_revision=(
                int(row["agent_revision"]) if row.get("agent_revision") is not None else None
            ),
            agent_config_hash=row.get("agent_config_hash") or "",
        )

    def _tool_call_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "tool_name": row["tool_name"],
            "request_payload": self._json_from_text(row["request_payload"]),
            "response_summary": self._json_from_text(row["response_summary"]),
            "status": row["status"],
            "duration_ms": int(row["duration_ms"]),
            "risk_level": row["risk_level"],
            "audit_id": row.get("audit_id"),
            "created_at": row["created_at"],
        }

    def _json_from_text(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value


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
        self.database.execute(
            """
            insert into audit_event
              (id, job_id, event_type, actor_id, status, summary, payload_summary, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                job_id,
                event_type,
                actor_id,
                status,
                summary,
                json.dumps(payload_summary or {}, ensure_ascii=False),
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
            row["payload_summary"] = self._safe_payload(
                str(row.get("payload_summary") or "{}")
            )
        return rows

    @staticmethod
    def _safe_payload(value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        forbidden = {"password", "password_hash", "token", "secret", "api_key"}
        return {
            key: ("[REDACTED]" if key.lower() in forbidden else item)
            for key, item in parsed.items()
        }


class ConfigurationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def enabled_tools(self) -> list[dict[str, Any]]:
        return self.database.execute("select * from tool_definition where enabled = 1")

    def get_tool(self, name: str) -> dict[str, Any] | None:
        return self.database.execute_one("select * from tool_definition where name = ?", (name,))

    def get_connector(self, connector_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from integration_connector where id = ?", (connector_id,)
        )
        if not row:
            return None
        row["metadata"] = self._json_from_text(str(row.get("metadata") or "{}"))
        return row

    def is_allowed(
        self,
        *,
        subject_code: str,
        resource_type: str,
        resource_code: str,
        action: str = "use",
    ) -> bool:
        # Legacy permission rows predate action-level authorization. The unified
        # evaluator owns action semantics; compatibility mode must preserve the
        # original subject/resource allow behavior until cutover.
        del action
        row = self.database.execute_one(
            """
            select * from permission_policy
            where subject_code = ?
              and resource_type = ?
              and (resource_code = ? or resource_code = '*')
              and effect = 'allow'
              and status = 'enabled'
            limit 1
            """,
            (subject_code, resource_type, resource_code),
        )
        return row is not None

    def _json_from_text(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
