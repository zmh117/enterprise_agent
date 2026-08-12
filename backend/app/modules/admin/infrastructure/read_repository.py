from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Any

from app.modules.job.infrastructure.repositories import (
    AgentRepository,
    source_connector_projection,
)
from app.shared.database import Database


class AdminReadRepository:
    """Bounded, read-only projections for the administration browser."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def jobs_in_window(self, start: str, end: str, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select j.id, j.session_id, j.status, j.retry_count, j.max_retry_count,
                   j.internal_user_id, j.requester_id as user_id,
                   j.requester_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.routing_context_json, j.error_message,
                   j.last_error_code,
                   j.business_application_id, j.business_application_code,
                   j.business_application_publication_id,
                   j.business_application_deployment_id,
                   j.business_application_route_id,
                   j.business_application_runtime_status,
                   j.business_application_route_decision_json,
                   j.execution_policy_json,
                   j.execution_policy_tool_call_count,
                   j.execution_policy_exhausted,
                   j.created_at, j.started_at, j.finished_at,
                   s.accounting_status as audit_accounting_status,
                   s.observed_model_turn_count as audit_observed_model_turn_count,
                   s.api_retry_count as audit_api_retry_count,
                   s.runtime_invocation_count as audit_runtime_invocation_count,
                   s.total_duration_ms as audit_total_duration_ms,
                   s.total_api_duration_ms as audit_total_api_duration_ms,
                   s.input_tokens as audit_input_tokens,
                   s.output_tokens as audit_output_tokens,
                   s.cache_creation_input_tokens as audit_cache_creation_input_tokens,
                   s.cache_read_input_tokens as audit_cache_read_input_tokens,
                   s.model_usage_json as audit_model_usage_json,
                   s.estimated_cost_usd as audit_estimated_cost_usd,
                   s.execution_status as audit_execution_status,
                   s.execution_failure_stage as audit_execution_failure_stage,
                   s.failure_code as audit_failure_code,
                   s.failure_summary as audit_failure_summary,
                   s.retry_exhausted as audit_retry_exhausted,
                   s.source_protocol_version as audit_source_protocol_version,
                   (select o.status from delivery_outbox o where o.job_id = j.id
                     order by o.created_at desc, o.id desc limit 1) as audit_delivery_status,
                   d.code as agent_code,
                   c.id as source_connector_record_id,
                   c.name as source_connector_name,
                   c.enabled as source_connector_enabled,
                   c.deleted as source_connector_deleted,
                   c.metadata as source_connector_metadata,
                   (select w.correlation_id from webhook_event w where w.job_id = j.id order by w.received_at desc limit 1) as correlation_id
            from agent_job j
            left join agent_definition d on d.id = j.agent_definition_id
            left join integration_connector c on c.id = j.source_connector_id
            left join agent_job_execution_summary s on s.job_id = j.id
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
                   routing_context_json, business_application_id,
                   business_application_code, conversation_mode,
                   application_publication_id, execution_scope_hash,
                   isolation_key_version, history_read_only,
                   recent_message_limit, updated_at
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
                   routing_context_json, business_application_id,
                   business_application_code, conversation_mode,
                   application_publication_id, execution_scope_hash,
                   isolation_key_version, history_read_only,
                   recent_message_limit, created_at, updated_at
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
                   j.internal_user_id, j.requester_id as user_id,
                   j.requester_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.routing_context_json, j.error_message,
                   j.last_error_code,
                   j.business_application_id, j.business_application_code,
                   j.business_application_publication_id,
                   j.business_application_deployment_id,
                   j.business_application_route_id,
                   j.business_application_runtime_status,
                   j.business_application_route_decision_json,
                   j.execution_policy_json,
                   j.execution_policy_tool_call_count,
                   j.execution_policy_exhausted,
                   j.created_at, j.started_at, j.finished_at,
                   s.accounting_status as audit_accounting_status,
                   s.observed_model_turn_count as audit_observed_model_turn_count,
                   s.api_retry_count as audit_api_retry_count,
                   s.runtime_invocation_count as audit_runtime_invocation_count,
                   s.total_duration_ms as audit_total_duration_ms,
                   s.total_api_duration_ms as audit_total_api_duration_ms,
                   s.input_tokens as audit_input_tokens,
                   s.output_tokens as audit_output_tokens,
                   s.cache_creation_input_tokens as audit_cache_creation_input_tokens,
                   s.cache_read_input_tokens as audit_cache_read_input_tokens,
                   s.model_usage_json as audit_model_usage_json,
                   s.estimated_cost_usd as audit_estimated_cost_usd,
                   s.execution_status as audit_execution_status,
                   s.execution_failure_stage as audit_execution_failure_stage,
                   s.failure_code as audit_failure_code,
                   s.failure_summary as audit_failure_summary,
                   s.retry_exhausted as audit_retry_exhausted,
                   s.source_protocol_version as audit_source_protocol_version,
                   (select o.status from delivery_outbox o where o.job_id = j.id
                     order by o.created_at desc, o.id desc limit 1) as audit_delivery_status,
                   d.code as agent_code,
                   c.id as source_connector_record_id,
                   c.name as source_connector_name,
                   c.enabled as source_connector_enabled,
                   c.deleted as source_connector_deleted,
                   c.metadata as source_connector_metadata
            from agent_job j
            left join agent_definition d on d.id = j.agent_definition_id
            left join integration_connector c on c.id = j.source_connector_id
            left join agent_job_execution_summary s on s.job_id = j.id
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
                   j.requester_id as user_id, j.requester_id,
                   j.routing_context_json, a.media_type, a.file_name,
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
                   j.requester_id as user_id, j.requester_id,
                   j.routing_context_json, a.media_type, a.file_name,
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
                   j.internal_user_id, j.requester_id as user_id,
                   j.requester_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.external_event_id, j.routing_context_json,
                   j.business_application_id, j.business_application_code,
                   j.business_application_publication_id,
                   j.business_application_deployment_id,
                   j.business_application_route_id,
                   j.business_application_runtime_status,
                   j.business_application_route_decision_json,
                   j.execution_policy_json,
                   j.execution_policy_tool_call_count,
                   j.execution_policy_exhausted,
                   j.error_message, j.last_error_code,
                   j.created_at, j.started_at, j.finished_at,
                   s.accounting_status as audit_accounting_status,
                   s.observed_model_turn_count as audit_observed_model_turn_count,
                   s.api_retry_count as audit_api_retry_count,
                   s.runtime_invocation_count as audit_runtime_invocation_count,
                   s.total_duration_ms as audit_total_duration_ms,
                   s.total_api_duration_ms as audit_total_api_duration_ms,
                   s.input_tokens as audit_input_tokens,
                   s.output_tokens as audit_output_tokens,
                   s.cache_creation_input_tokens as audit_cache_creation_input_tokens,
                   s.cache_read_input_tokens as audit_cache_read_input_tokens,
                   s.model_usage_json as audit_model_usage_json,
                   s.estimated_cost_usd as audit_estimated_cost_usd,
                   s.execution_status as audit_execution_status,
                   s.execution_failure_stage as audit_execution_failure_stage,
                   s.failure_code as audit_failure_code,
                   s.failure_summary as audit_failure_summary,
                   s.retry_exhausted as audit_retry_exhausted,
                   s.source_protocol_version as audit_source_protocol_version,
                   (select o.status from delivery_outbox o where o.job_id = j.id
                     order by o.created_at desc, o.id desc limit 1) as audit_delivery_status,
                   d.code as agent_code,
                   c.id as source_connector_record_id,
                   c.name as source_connector_name,
                   c.enabled as source_connector_enabled,
                   c.deleted as source_connector_deleted,
                   c.metadata as source_connector_metadata
            from agent_job j
            left join agent_definition d on d.id = j.agent_definition_id
            left join integration_connector c on c.id = j.source_connector_id
            left join agent_job_execution_summary s on s.job_id = j.id
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
                   status, duration_ms, risk_level, audit_id, created_at,
                   invocation_id, runtime_tool_call_id, tool_origin,
                   server_code, mcp_call_id, persisted_by
            from agent_tool_call where job_id = ? order by created_at, id
            """,
            (job_id,),
        )
        from app.modules.job.infrastructure.execution_audit_repository import (
            ExecutionAuditRepository,
        )

        execution_audit = ExecutionAuditRepository(self.database)
        model_calls = execution_audit.list_model_calls(job_id, limit=50)
        agent_repository = AgentRepository(self.database)
        delivery_events = agent_repository.list_delivery_events(job_id)
        delivery_attempts = agent_repository.list_delivery_attempts(job_id)
        delivery_chunks = agent_repository.list_delivery_chunks(job_id)
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
            "execution_summary": job["execution_summary"],
            "model_calls": model_calls,
            "mcp_operation_links": [
                {
                    "agent_tool_call_id": str(row.get("id") or ""),
                    "mcp_call_id": str(row.get("mcp_call_id") or ""),
                    "server_code": str(row.get("server_code") or ""),
                }
                for row in tools
                if row.get("mcp_call_id")
            ],
            "deliveries": {
                "events": [_safe_times(row) for row in delivery_events],
                "attempts": [_safe_times(row) for row in delivery_attempts],
                "chunks": [_safe_times(row) for row in delivery_chunks],
            },
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
        item.update(source_connector_projection(item))
        for field in (
            "source_connector_record_id",
            "source_connector_enabled",
            "source_connector_deleted",
            "source_connector_metadata",
        ):
            item.pop(field, None)
        item["routing"] = _json_object(item.pop("routing_context_json", {}))
        item["business_application_route_decision"] = _json_object(
            item.pop("business_application_route_decision_json", {})
        )
        item["execution_policy"] = _json_object(item.pop("execution_policy_json", {}))
        item["tool_call_count"] = int(item.pop("execution_policy_tool_call_count", 0) or 0)
        item["execution_policy_exhausted"] = bool(item.get("execution_policy_exhausted") or False)
        item["correlation_id"] = str(
            item.get("correlation_id")
            or item["business_application_route_decision"].get("correlation_id")
            or ""
        )
        item["error_summary"] = str(item.pop("error_message", "") or "")[:500]
        item["agent_code"] = str(item.get("agent_code") or "default-diagnostic-agent")
        item["business_application_runtime_status"] = str(
            item.get("business_application_runtime_status") or "legacy_unattributed"
        )
        item["execution_summary"] = _execution_summary(item)
        return _safe_times(item)

    @staticmethod
    def _session(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["routing"] = _json_object(item.pop("routing_context_json", {}))
        item["history_read_only"] = bool(item.get("history_read_only"))
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


def _execution_summary(item: dict[str, Any]) -> dict[str, Any]:
    prefix = "audit_"
    accounting_status = str(item.pop(f"{prefix}accounting_status", "") or "UNAVAILABLE")
    model_usage = _json_array(item.pop(f"{prefix}model_usage_json", "[]"))
    execution_status = str(item.pop(f"{prefix}execution_status", "") or "UNKNOWN")
    delivery_status = str(item.pop(f"{prefix}delivery_status", "") or "NOT_REQUESTED")
    failure_stage = item.pop(f"{prefix}execution_failure_stage", None)
    display_failure_stage = (
        "DELIVERY"
        if execution_status == "SUCCEEDED" and delivery_status in {"FAILED", "DEAD"}
        else failure_stage
    )
    estimated_cost = item.pop(f"{prefix}estimated_cost_usd", None)
    return {
        "accounting_status": accounting_status,
        "observed_model_turn_count": int(
            item.pop(f"{prefix}observed_model_turn_count", 0) or 0
        ),
        "api_retry_count": int(item.pop(f"{prefix}api_retry_count", 0) or 0),
        "runtime_invocation_count": int(
            item.pop(f"{prefix}runtime_invocation_count", 0) or 0
        ),
        **{
            field: (
                int(value) if value is not None else None
            )
            for field in (
                "total_duration_ms",
                "total_api_duration_ms",
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
            for value in [item.pop(f"{prefix}{field}", None)]
        },
        "model_usage": model_usage,
        "models": [str(value.get("model_id") or "") for value in model_usage],
        "estimated_cost_usd": str(estimated_cost) if estimated_cost is not None else None,
        "execution_status": execution_status,
        "delivery_status": delivery_status,
        "execution_failure_stage": failure_stage,
        "display_failure_stage": display_failure_stage,
        "failure_code": item.pop(f"{prefix}failure_code", None),
        "failure_summary": item.pop(f"{prefix}failure_summary", None),
        "retry_exhausted": bool(item.pop(f"{prefix}retry_exhausted", 0) or False),
        "source_protocol_version": str(
            item.pop(f"{prefix}source_protocol_version", "") or "1.0"
        ),
    }


def _json_array(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _safe_times(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.isoformat() if isinstance(item, datetime) else item for key, item in value.items()
    }
