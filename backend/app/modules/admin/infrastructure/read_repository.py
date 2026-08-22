from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.modules.admin.application.scope import AdminScope
from app.modules.job.infrastructure.repositories import (
    AgentRepository,
    source_connector_projection,
)
from app.shared.database import Database


@dataclass(frozen=True)
class AdminJobQuery:
    start: str
    end: str
    scope: AdminScope
    username: str = ""
    application_name: str = ""
    statuses: tuple[str, ...] = ()
    user_id: str = ""
    agent: str = ""
    channel: str = ""
    project: str = ""
    session_id: str = ""
    correlation_id: str = ""
    execution_statuses: tuple[str, ...] = ()
    delivery_statuses: tuple[str, ...] = ()
    failure_stages: tuple[str, ...] = ()
    model: str = ""
    cursor_created_at: str = ""
    cursor_id: str = ""
    limit: int = 25


class AdminReadRepository:
    """Bounded, read-only projections for the administration browser."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def jobs_in_window(
        self,
        start: str,
        end: str,
        *,
        username: str = "",
        application_name: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return self._query_jobs(
            AdminJobQuery(
                start=start,
                end=end,
                scope=AdminScope({"mode": "global", "grants": []}, ""),
                username=username,
                application_name=application_name,
                limit=limit,
            ),
            include_extra=False,
        )

    def query_jobs(self, query: AdminJobQuery) -> list[dict[str, Any]]:
        return self._query_jobs(query, include_extra=True)

    def _query_jobs(
        self,
        query: AdminJobQuery,
        *,
        include_extra: bool,
    ) -> list[dict[str, Any]]:
        clauses = ["j.created_at >= ?", "j.created_at < ?"]
        params: list[Any] = [query.start, query.end]
        scope_clause, scope_params = _job_scope_clause(self.database, query.scope)
        if scope_clause:
            clauses.append(scope_clause)
            params.extend(scope_params)

        username_pattern = _contains_pattern(query.username)
        if username_pattern:
            clauses.append(
                """
                (lower(coalesce(u.username, '')) like ? escape '!'
                 or lower(coalesce(u.display_name, '')) like ? escape '!')
                """
            )
            params.extend((username_pattern, username_pattern))
        application_pattern = _contains_pattern(query.application_name)
        if application_pattern:
            clauses.append(
                """
                (lower(coalesce(a.name, '')) like ? escape '!'
                 or lower(coalesce(j.business_application_code, '')) like ? escape '!')
                """
            )
            params.extend((application_pattern, application_pattern))

        _append_in_filter(clauses, params, "j.status", query.statuses)
        if query.user_id:
            clauses.append("(j.internal_user_id = ? or j.requester_id = ?)")
            params.extend((query.user_id, query.user_id))
        if query.agent:
            clauses.append("coalesce(d.code, 'default-diagnostic-agent') = ?")
            params.append(query.agent)
        if query.channel:
            clauses.append("j.source_channel = ?")
            params.append(query.channel)
        if query.project:
            clauses.append("j.project_code = ?")
            params.append(query.project)
        if query.session_id:
            clauses.append("j.session_id = ?")
            params.append(query.session_id)

        route_correlation = _json_text_expression(
            self.database,
            "j.business_application_route_decision_json",
            "correlation_id",
        )
        webhook_correlation = (
            "(select w.correlation_id from webhook_event w where w.job_id = j.id "
            "order by w.received_at desc limit 1)"
        )
        if query.correlation_id:
            clauses.append(
                f"coalesce(nullif({webhook_correlation}, ''), {route_correlation}, '') = ?"
            )
            params.append(query.correlation_id)

        _append_in_filter(
            clauses,
            params,
            "coalesce(s.execution_status, 'UNKNOWN')",
            query.execution_statuses,
        )
        delivery_status = (
            "coalesce((select o.status from delivery_outbox o where o.job_id = j.id "
            "order by o.created_at desc, o.id desc limit 1), 'NOT_REQUESTED')"
        )
        _append_in_filter(
            clauses,
            params,
            delivery_status,
            query.delivery_statuses,
        )
        display_failure_stage = (
            "case when coalesce(s.execution_status, 'UNKNOWN') = 'SUCCEEDED' "
            f"and {delivery_status} in ('FAILED', 'DEAD') then 'DELIVERY' "
            "else s.execution_failure_stage end"
        )
        _append_in_filter(
            clauses,
            params,
            display_failure_stage,
            query.failure_stages,
        )
        if query.model:
            clauses.append(_model_usage_clause(self.database))
            params.append(query.model)

        if query.cursor_created_at or query.cursor_id:
            clauses.append("(j.created_at < ? or (j.created_at = ? and j.id < ?))")
            params.extend(
                (query.cursor_created_at, query.cursor_created_at, query.cursor_id)
            )

        bounded_limit = max(1, min(int(query.limit), 1000))
        params.append(bounded_limit + (1 if include_extra else 0))
        rows = self.database.execute(
            f"""
            select j.id, j.session_id, j.status, j.retry_count, j.max_retry_count,
                   j.internal_user_id, j.requester_id as user_id,
                   u.username as user_username,
                   u.display_name as user_display_name,
                   j.requester_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.routing_context_json, j.error_message,
                   j.last_error_code,
                   j.business_application_id, j.business_application_code,
                   a.name as business_application_name,
                   j.business_application_publication_id,
                   j.business_application_deployment_id,
                   j.business_application_route_id,
                   j.business_application_runtime_status,
                   j.business_application_route_decision_json,
                   j.execution_policy_json,
                   j.execution_policy_tool_call_count,
                   (select count(*) from agent_tool_call tc
                     where tc.job_id = j.id
                       and tc.invocation_id =
                         j.id || '.attempt-' || cast(j.retry_count as text))
                     as observed_execution_policy_tool_call_count,
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
                   {webhook_correlation} as correlation_id
            from agent_job j
            left join agent_definition d on d.id = j.agent_definition_id
            left join integration_connector c on c.id = j.source_connector_id
            left join agent_job_execution_summary s on s.job_id = j.id
            left join app_user u on u.id = j.internal_user_id
            left join business_application a on a.id = j.business_application_id
            where {" and ".join(clauses)}
            order by j.created_at desc, j.id desc
            limit ?
            """,
            params,
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
                   u.username as user_username,
                   u.display_name as user_display_name,
                   j.requester_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.routing_context_json, j.error_message,
                   j.last_error_code,
                   j.business_application_id, j.business_application_code,
                   a.name as business_application_name,
                   j.business_application_publication_id,
                   j.business_application_deployment_id,
                   j.business_application_route_id,
                   j.business_application_runtime_status,
                   j.business_application_route_decision_json,
                   j.execution_policy_json,
                   j.execution_policy_tool_call_count,
                   (select count(*) from agent_tool_call tc
                     where tc.job_id = j.id
                       and tc.invocation_id =
                         j.id || '.attempt-' || cast(j.retry_count as text))
                     as observed_execution_policy_tool_call_count,
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
            left join app_user u on u.id = j.internal_user_id
            left join business_application a on a.id = j.business_application_id
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
            select a.id, a.message_id, a.job_id, m.session_id,
                   coalesce(j.internal_user_id, m.sender_id, s.requester_id) as internal_user_id,
                   coalesce(j.requester_id, m.sender_id, s.requester_id) as user_id,
                   coalesce(j.requester_id, m.sender_id, s.requester_id) as requester_id,
                   coalesce(j.routing_context_json, s.routing_context_json) as routing_context_json,
                   a.media_type, a.file_name,
                   a.declared_mime, a.detected_mime, a.declared_size, a.size_bytes,
                   a.status, a.failure_code, a.retry_count, a.sha256,
                   a.object_bucket, a.object_key, a.created_at, a.updated_at
            from message_attachment a
            join agent_message m on m.id = a.message_id
            join agent_session s on s.id = m.session_id
            left join agent_job j on j.id = a.job_id
            where a.created_at >= ? and a.created_at < ?
            order by a.created_at desc, a.id desc limit ?
            """,
            (start, end, limit),
        )
        return [self._attachment(row) for row in rows]

    def attachment_detail(self, attachment_id: str) -> dict[str, Any] | None:
        rows = self.database.execute(
            """
            select a.id, a.message_id, a.job_id, m.session_id,
                   coalesce(j.internal_user_id, m.sender_id, s.requester_id) as internal_user_id,
                   coalesce(j.requester_id, m.sender_id, s.requester_id) as user_id,
                   coalesce(j.requester_id, m.sender_id, s.requester_id) as requester_id,
                   coalesce(j.routing_context_json, s.routing_context_json) as routing_context_json,
                   a.media_type, a.file_name,
                   a.declared_mime, a.detected_mime, a.declared_size, a.size_bytes,
                   a.status, a.failure_code, a.retry_count, a.sha256,
                   a.object_bucket, a.object_key, a.created_at, a.updated_at
            from message_attachment a
            join agent_message m on m.id = a.message_id
            join agent_session s on s.id = m.session_id
            left join agent_job j on j.id = a.job_id
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
                   u.username as user_username,
                   u.display_name as user_display_name,
                   j.requester_id, j.project_code, j.source_channel,
                   j.source_connector_id, j.external_event_id, j.routing_context_json,
                   j.business_application_id, j.business_application_code,
                   a.name as business_application_name,
                   j.business_application_publication_id,
                   j.business_application_deployment_id,
                   j.business_application_route_id,
                   j.business_application_runtime_status,
                   j.business_application_route_decision_json,
                   j.execution_policy_json,
                   j.execution_policy_tool_call_count,
                   (select count(*) from agent_tool_call tc
                     where tc.job_id = j.id
                       and tc.invocation_id =
                         j.id || '.attempt-' || cast(j.retry_count as text))
                     as observed_execution_policy_tool_call_count,
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
            left join app_user u on u.id = j.internal_user_id
            left join business_application a on a.id = j.business_application_id
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
        persisted_tool_call_count = int(item.pop("execution_policy_tool_call_count", 0) or 0)
        observed_tool_call_count = int(
            item.pop("observed_execution_policy_tool_call_count", 0) or 0
        )
        item["tool_call_count"] = max(
            persisted_tool_call_count,
            observed_tool_call_count,
        )
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
        return _safe_times(item)


def _contains_pattern(value: str) -> str:
    term = value.strip().lower()[:200]
    if not term:
        return ""
    escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"


def _append_in_filter(
    clauses: list[str],
    params: list[Any],
    expression: str,
    values: tuple[str, ...],
) -> None:
    if not values:
        return
    clauses.append(f"{expression} in ({', '.join('?' for _ in values)})")
    params.extend(values)


def _job_scope_clause(database: Database, scope: AdminScope) -> tuple[str, list[Any]]:
    if scope.global_access:
        return "", []

    owner_clause = (
        "coalesce(nullif(j.internal_user_id, ''), nullif(j.requester_id, ''), '') = ?"
    )
    owner_params: list[Any] = [scope.user_id]
    allow_matches: list[tuple[str, list[Any]]] = []
    deny_matches: list[tuple[str, list[Any]]] = []
    for grant in scope.grants:
        match_clauses: list[str] = []
        match_params: list[Any] = []
        for field in ("environment", "base", "workshop"):
            expected = str(grant.get(field) or "*")
            if expected == "*":
                continue
            expression = _json_text_expression(
                database,
                "j.routing_context_json",
                field,
            )
            match_clauses.append(f"coalesce({expression}, '') = ?")
            match_params.append(expected)
        match = f"({' and '.join(match_clauses)})" if match_clauses else "(1 = 1)"
        target = (
            deny_matches
            if str(grant.get("effect") or "allow").lower() == "deny"
            else allow_matches
        )
        target.append((match, match_params))

    if not allow_matches:
        return f"({owner_clause})", owner_params

    allow_sql = " or ".join(match for match, _ in allow_matches)
    allow_params = [value for _, values in allow_matches for value in values]
    if not deny_matches:
        return f"({owner_clause} or ({allow_sql}))", owner_params + allow_params

    deny_sql = " or ".join(match for match, _ in deny_matches)
    deny_params = [value for _, values in deny_matches for value in values]
    return (
        f"({owner_clause} or (({allow_sql}) and not ({deny_sql})))",
        owner_params + allow_params + deny_params,
    )


def _json_text_expression(database: Database, column: str, key: str) -> str:
    if database.engine == "sqlite":
        return (
            "json_extract(case when json_valid("
            f"{column}) then {column} else '{{}}' end, '$.{key}')"
        )
    return f"(coalesce(nullif({column}, ''), '{{}}')::jsonb ->> '{key}')"


def _model_usage_clause(database: Database) -> str:
    if database.engine == "sqlite":
        return (
            "exists (select 1 from json_each(case when json_valid(s.model_usage_json) "
            "then s.model_usage_json else '[]' end) model_usage "
            "where json_extract(model_usage.value, '$.model_id') = ?)"
        )
    return (
        "exists (select 1 from jsonb_array_elements("
        "coalesce(nullif(s.model_usage_json, ''), '[]')::jsonb) model_usage "
        "where model_usage ->> 'model_id' = ?)"
    )


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
        "observed_model_turn_count": int(item.pop(f"{prefix}observed_model_turn_count", 0) or 0),
        "api_retry_count": int(item.pop(f"{prefix}api_retry_count", 0) or 0),
        "runtime_invocation_count": int(item.pop(f"{prefix}runtime_invocation_count", 0) or 0),
        **{
            field: (int(value) if value is not None else None)
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
        "source_protocol_version": str(item.pop(f"{prefix}source_protocol_version", "") or "1.3"),
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
