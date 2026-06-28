from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.job.domain.agent_job import AgentJob, AgentSession
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
    ) -> AgentSession:
        session_id = new_id("session")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_session
              (id, dingding_conversation_id, dingding_user_id, source, project_code, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                dingding_conversation_id,
                dingding_user_id,
                source,
                project_code,
                timestamp,
                timestamp,
            ),
        )
        return AgentSession(
            id=session_id,
            dingding_conversation_id=dingding_conversation_id,
            dingding_user_id=dingding_user_id,
            source=source,
            project_code=project_code,
        )

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
    ) -> AgentJob:
        existing = self.get_job_by_idempotency_key(idempotency_key)
        if existing:
            return existing
        job_id = new_id("job")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_job
              (id, session_id, idempotency_key, user_id, project_code, source, user_message,
               status, retry_count, max_retry_count, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                session_id,
                idempotency_key,
                user_id,
                project_code,
                source,
                user_message,
                JobStatus.PENDING.value,
                0,
                max_retry_count,
                timestamp,
            ),
        )
        return self.get_job(job_id)

    def add_message(self, *, session_id: str, job_id: str | None, role: str, content: str) -> str:
        message_id = new_id("msg")
        self.database.execute(
            """
            insert into agent_message (id, session_id, job_id, role, content, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (message_id, session_id, job_id, role, content, now_iso()),
        )
        return message_id

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


class ConfigurationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def enabled_tools(self) -> list[dict[str, Any]]:
        return self.database.execute("select * from tool_definition where enabled = 1")

    def get_tool(self, name: str) -> dict[str, Any] | None:
        return self.database.execute_one("select * from tool_definition where name = ?", (name,))

    def is_allowed(self, *, subject_code: str, resource_type: str, resource_code: str) -> bool:
        row = self.database.execute_one(
            """
            select * from permission_policy
            where subject_code = ?
              and resource_type = ?
              and (resource_code = ? or resource_code = '*')
              and effect = 'allow'
            limit 1
            """,
            (subject_code, resource_type, resource_code),
        )
        return row is not None
