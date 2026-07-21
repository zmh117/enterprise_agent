from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Any

from app.shared.database import Database


class AdminReadRepository:
    """Bounded, read-only projections for the administration browser."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def jobs_in_window(self, start: str, end: str, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select j.id, j.session_id, j.status, j.retry_count, j.max_retry_count,
                   j.internal_user_id, j.user_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.routing_context_json, j.error_message,
                   j.created_at, j.started_at, j.finished_at,
                   d.code as agent_code,
                   (select w.correlation_id from webhook_event w where w.job_id = j.id order by w.received_at desc limit 1) as correlation_id
            from agent_job j
            left join agent_definition d on d.id = j.agent_definition_id
            where j.created_at >= ? and j.created_at < ?
            order by j.created_at desc, j.id desc
            limit ?
            """,
            (start, end, limit),
        )
        return [self._job(row) for row in rows]

    def delivery_failures(self, start: str, end: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select d.id, d.job_id, d.route_type, d.connector_id, d.status,
                   d.error_message, d.created_at, d.finished_at
            from delivery_attempt d
            where d.created_at >= ? and d.created_at < ? and d.status = 'FAILED'
            order by d.created_at desc, d.id desc
            limit ?
            """,
            (start, end, limit),
        )

    def recent_webhook_events(
        self, start: str, end: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select id, job_id, external_event_id, correlation_id, status,
                   error_code, error_summary, received_at
            from webhook_event
            where received_at >= ? and received_at < ?
            order by received_at desc, id desc
            limit ?
            """,
            (start, end, limit),
        )

    def recent_sessions(self, start: str, end: str, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id, requester_id, project_code, source_channel,
                   source_connector_id, external_conversation_id,
                   routing_context_json, updated_at
            from agent_session
            where updated_at >= ? and updated_at < ?
            order by updated_at desc, id desc
            limit ?
            """,
            (start, end, limit),
        )
        return [self._session(row) for row in rows]

    def counts(self) -> dict[str, int]:
        queries = {
            "users": "select count(*) as value from app_user where status = 'enabled'",
            "agents": "select count(*) as value from agent_definition where status = 'enabled'",
            "channels": "select count(*) as value from integration_connector where enabled = 1 and (allow_ingress = 1 or allow_delivery = 1)",
        }
        result: dict[str, int] = {}
        for key, query in queries.items():
            row = self.database.execute_one(query)
            result[key] = int(row["value"] if row else 0)
        return result

    def session_detail(self, session_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select id, requester_id, requester_display_name, project_code,
                   source_channel, source_connector_id, external_conversation_id,
                   routing_context_json, created_at, updated_at
            from agent_session where id = ?
            """,
            (session_id,),
        )
        return self._session(row) if row else None

    def session_messages(self, session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id, job_id, role, substr(content, 1, 4000) as content,
                   message_type, content_status, sequence_no, created_at
            from agent_message where session_id = ?
            order by sequence_no, created_at, id limit ?
            """,
            (session_id, limit),
        )
        return [_safe_times(row) for row in rows]

    def session_jobs(self, session_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select j.id, j.session_id, j.status, j.retry_count, j.max_retry_count,
                   j.internal_user_id, j.user_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.routing_context_json, j.error_message,
                   j.created_at, j.started_at, j.finished_at, d.code as agent_code
            from agent_job j left join agent_definition d on d.id = j.agent_definition_id
            where j.session_id = ? order by j.created_at, j.id limit ?
            """,
            (session_id, limit),
        )
        return [self._job(row) for row in rows]

    def attachments_in_window(
        self, start: str, end: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select a.id, a.message_id, a.job_id, j.session_id, j.internal_user_id,
                   j.user_id, j.routing_context_json, a.media_type, a.file_name,
                   a.declared_mime, a.detected_mime, a.declared_size, a.size_bytes,
                   a.status, a.failure_code, a.retry_count, a.sha256,
                   a.object_bucket, a.object_key, a.created_at, a.updated_at,
                   c.char_count, c.truncated, substr(c.plain_text, 1, 4000) as text_preview
            from message_attachment a
            join agent_job j on j.id = a.job_id
            left join attachment_content c on c.attachment_id = a.id
            where a.created_at >= ? and a.created_at < ?
            order by a.created_at desc, a.id desc limit ?
            """,
            (start, end, limit),
        )
        return [self._attachment(row) for row in rows]

    def attachment_detail(self, attachment_id: str) -> dict[str, Any] | None:
        rows = self.database.execute(
            """
            select a.id, a.message_id, a.job_id, j.session_id, j.internal_user_id,
                   j.user_id, j.routing_context_json, a.media_type, a.file_name,
                   a.declared_mime, a.detected_mime, a.declared_size, a.size_bytes,
                   a.status, a.failure_code, a.retry_count, a.sha256,
                   a.object_bucket, a.object_key, a.created_at, a.updated_at,
                   c.char_count, c.truncated, substr(c.plain_text, 1, 4000) as text_preview
            from message_attachment a
            join agent_job j on j.id = a.job_id
            left join attachment_content c on c.attachment_id = a.id
            where a.id = ?
            """,
            (attachment_id,),
        )
        return self._attachment(rows[0]) if rows else None

    def job_evidence(self, job_id: str) -> dict[str, Any] | None:
        jobs = self.database.execute(
            """
            select j.id, j.session_id, j.status, j.retry_count, j.max_retry_count,
                   j.internal_user_id, j.user_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.external_event_id, j.routing_context_json,
                   j.error_message, j.created_at, j.started_at, j.finished_at,
                   d.code as agent_code
            from agent_job j left join agent_definition d on d.id = j.agent_definition_id
            where j.id = ?
            """,
            (job_id,),
        )
        if not jobs:
            return None
        job = self._job(jobs[0])
        steps = self.database.execute(
            "select id, step_type, title, substr(content, 1, 2000) as content, created_at from agent_step where job_id = ? order by created_at, id",
            (job_id,),
        )
        tools = self.database.execute(
            """
            select id, tool_name, substr(response_summary, 1, 2000) as response_summary,
                   status, duration_ms, risk_level, audit_id, created_at
            from agent_tool_call where job_id = ? order by created_at, id
            """,
            (job_id,),
        )
        deliveries = self.database.execute(
            """
            select id, route_type, connector_id, status,
                   substr(error_message, 1, 500) as error_summary, created_at, finished_at
            from delivery_attempt where job_id = ? order by created_at, id
            """,
            (job_id,),
        )
        webhooks = self.database.execute(
            """
            select id, external_event_id, correlation_id, status, error_code,
                   substr(error_summary, 1, 500) as error_summary, received_at, dispatched_at
            from webhook_event where job_id = ? order by received_at, id
            """,
            (job_id,),
        )
        return {
            "job": job,
            "session_ref": {"id": job["session_id"]},
            "steps": [_safe_times(row) for row in steps],
            "tool_calls": [_safe_times(row) for row in tools],
            "delivery_attempts": [_safe_times(row) for row in deliveries],
            "webhook_events": [_safe_times(row) for row in webhooks],
            "retry": {
                "count": int(job.get("retry_count") or 0),
                "max": int(job.get("max_retry_count") or 0),
                "waiting": job["status"] == "RETRY_WAIT",
            },
        }

    @staticmethod
    def _job(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["routing"] = _json_object(item.pop("routing_context_json", {}))
        item["error_summary"] = str(item.pop("error_message", "") or "")[:500]
        item["agent_code"] = str(item.get("agent_code") or "default-diagnostic-agent")
        return _safe_times(item)

    @staticmethod
    def _session(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["routing"] = _json_object(item.pop("routing_context_json", {}))
        return _safe_times(item)

    @staticmethod
    def _attachment(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["routing"] = _json_object(item.pop("routing_context_json", {}))
        bucket = str(item.pop("object_bucket", "") or "")
        key = str(item.pop("object_key", "") or "")
        item["object_ref_summary"] = (
            hashlib.sha256(f"{bucket}/{key}".encode()).hexdigest()[:16] if bucket or key else ""
        )
        item["storage_configured"] = bool(bucket and key)
        item["text_preview"] = str(item.get("text_preview") or "")[:4000]
        return _safe_times(item)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_times(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.isoformat() if isinstance(item, datetime) else item for key, item in value.items()
    }
