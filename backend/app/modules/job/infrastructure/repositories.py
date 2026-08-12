from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.delivery.domain import DeliveryEvent, DeliveryStatus
from app.modules.job.domain.agent_job import AgentJob, AgentSession, MessageAttachment
from app.modules.job.domain.execution_policy import JobExecutionPolicySnapshot
from app.modules.job.domain.job_dispatch import JobDispatchEvent, JobDispatchStatus
from app.modules.job.domain.job_status import JobStatus, can_transition
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
    "input_message_id",
)
_SESSION_COLUMNS_SQL = ", ".join(_SESSION_COLUMN_NAMES)
_JOB_COLUMNS_SQL = ", ".join(_JOB_COLUMN_NAMES)
_QUALIFIED_JOB_COLUMNS_SQL = ", ".join(
    f"j.{column}" for column in _JOB_COLUMN_NAMES
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _safe_runtime_event_payload(event_type: str, value: object) -> dict[str, Any]:
    """Persist only the audit-safe subset; token counts are measurements, not secrets."""
    payload = value if isinstance(value, dict) else {}
    if event_type == "runtime_initialized":
        return {
            "model_id": str(payload.get("model_id") or "")[:200],
            "mcp_servers": [
                {
                    "server_code": str(item.get("server_code") or "")[:128],
                    "status": str(item.get("status") or "UNKNOWN")[:32],
                }
                for item in payload.get("mcp_servers") or []
                if isinstance(item, dict)
            ][:64],
        }
    if event_type == "model_call":
        return {
            "model_call_id": str(payload.get("model_call_id") or "")[:200],
            "provider_request_id": _optional_bounded_string(
                payload.get("provider_request_id"), 200
            ),
            "provider_message_id": _optional_bounded_string(
                payload.get("provider_message_id"), 200
            ),
            "model_id": str(payload.get("model_id") or "unknown")[:200],
            "status": str(payload.get("status") or "FAILED")[:32],
            "started_at": _optional_bounded_string(payload.get("started_at"), 64),
            "completed_at": _optional_bounded_string(payload.get("completed_at"), 64),
            "duration_ms": _optional_nonnegative_integer(payload.get("duration_ms")),
            "duration_source": str(payload.get("duration_source") or "UNAVAILABLE")[:32],
            "usage": _runtime_token_usage(payload.get("usage")),
            "stop_reason": _optional_bounded_string(payload.get("stop_reason"), 128),
            "error_code": _optional_bounded_string(payload.get("error_code"), 128),
            "error_summary": _optional_bounded_string(payload.get("error_summary"), 2048),
        }
    if event_type == "api_retry":
        return {
            "attempt": _optional_nonnegative_integer(payload.get("attempt")),
            "max_retries": _optional_nonnegative_integer(payload.get("max_retries")),
            "retry_delay_ms": _optional_nonnegative_integer(payload.get("retry_delay_ms")),
            "error_status": _optional_nonnegative_integer(payload.get("error_status")),
            "error_code": str(payload.get("error_code") or "unknown")[:128],
        }
    if event_type == "terminal":
        safe = {
            key: payload.get(key)
            for key in (
                "protocol_version",
                "invocation_id",
                "request_digest",
                "last_sequence",
                "status",
                "cancel_reason",
            )
            if key in payload
        }
        safe["usage"] = _runtime_token_usage(payload.get("usage"))
        if isinstance(payload.get("accounting"), dict):
            safe["accounting"] = _safe_runtime_accounting(payload["accounting"])
        if isinstance(payload.get("runtime_provenance"), dict):
            safe["runtime_provenance"] = sanitize_for_persistence(
                payload["runtime_provenance"]
            )
        if isinstance(payload.get("failure"), dict):
            failure = payload["failure"]
            safe["failure"] = {
                "code": str(failure.get("code") or "runtime_failure")[:128],
                "retry_class": str(failure.get("retry_class") or "PERMANENT")[:32],
                "safe_message": str(failure.get("safe_message") or "")[:2048],
            }
        return safe
    if event_type == "assistant_text":
        text = str(payload.get("text") or "")
        return {"content_status": "OMITTED", "character_count": len(text)}
    return sanitize_for_persistence(payload)


def _safe_runtime_accounting(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(value.get("status") or "UNAVAILABLE")[:32],
        "duration_ms": _optional_nonnegative_integer(value.get("duration_ms")),
        "duration_api_ms": _optional_nonnegative_integer(value.get("duration_api_ms")),
        "num_turns": _optional_nonnegative_integer(value.get("num_turns")),
        "usage": _runtime_token_usage(value.get("usage")),
        "estimated_cost_usd": _optional_nonnegative_number(value.get("estimated_cost_usd")),
        "permission_denials_count": _optional_nonnegative_integer(
            value.get("permission_denials_count")
        ),
        "model_usage": [],
    }
    for item in value.get("model_usage") or []:
        if not isinstance(item, dict):
            continue
        result["model_usage"].append(
            {
                "model_id": str(item.get("model_id") or "unknown")[:200],
                "canonical_model": str(item.get("canonical_model") or "")[:200],
                "provider": str(item.get("provider") or "")[:100],
                "usage": _runtime_token_usage(item.get("usage")),
                "estimated_cost_usd": _optional_nonnegative_number(
                    item.get("estimated_cost_usd")
                ),
            }
        )
    result["model_usage"] = result["model_usage"][:64]
    return result


def _runtime_token_usage(value: object) -> dict[str, int | None]:
    usage = value if isinstance(value, dict) else {}
    return {
        field: _optional_nonnegative_integer(usage.get(field))
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    }


def _optional_nonnegative_integer(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        candidate = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if 0 <= candidate <= 9_223_372_036_854_775_807 else None


def _optional_nonnegative_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if 0 <= candidate < float("inf") else None


def _optional_bounded_string(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:maximum] if text else None


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


class AgentRepository:
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
        agent_runtime_protocol_version: str = "1.0",
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
                   agent_runtime_protocol_version, input_message_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null)
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

    def record_runtime_event(self, job_id: str, event: dict[str, Any]) -> None:
        invocation_id = str(event.get("invocation_id") or "")
        request_digest = str(event.get("request_digest") or "")
        sequence = int(event.get("sequence") or 0)
        event_type = str(event.get("event_type") or "")
        if (
            not invocation_id
            or len(request_digest) != 64
            or sequence < 1
            or event_type not in {
                "execution_started",
                "runtime_initialized",
                "model_call",
                "api_retry",
                "tool_event",
                "assistant_text",
                "terminal",
            }
        ):
            raise NonRetryableExecutionError(
                "Runtime event identity is invalid",
                safe_message="Runtime 事件身份无效",
                error_code="runtime_event_invalid",
            )
        payload_json = json.dumps(
            _safe_runtime_event_payload(event_type, event.get("payload") or {}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = self.database.execute_one(
            """
            select request_digest, event_type, payload_json
              from agent_runtime_event
             where job_id = ? and invocation_id = ? and sequence = ?
            """,
            (job_id, invocation_id, sequence),
        )
        if existing is not None:
            if (
                str(existing["request_digest"]) != request_digest
                or str(existing["event_type"]) != event_type
                or str(existing["payload_json"]) != payload_json
            ):
                raise NonRetryableExecutionError(
                    "Runtime event sequence conflicts with persisted data",
                    safe_message="Runtime 事件与已保存记录冲突",
                    error_code="runtime_event_digest_conflict",
                )
            return
        previous = self.database.execute_one(
            """
            select max(sequence) last_sequence
              from agent_runtime_event
             where job_id = ? and invocation_id = ?
            """,
            (job_id, invocation_id),
        )
        if sequence != int((previous or {}).get("last_sequence") or 0) + 1:
            raise NonRetryableExecutionError(
                "Runtime event sequence contains a gap",
                safe_message="Runtime 事件顺序不完整",
                error_code="runtime_event_sequence_gap",
            )
        self.database.execute(
            """
            insert into agent_runtime_event
              (id, job_id, invocation_id, request_digest, sequence,
               event_type, payload_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(job_id, invocation_id, sequence) do nothing
            """,
            (
                new_id("runtime_event"),
                job_id,
                invocation_id,
                request_digest,
                sequence,
                event_type,
                payload_json,
                now_iso(),
            ),
        )
        persisted = self.database.execute_one(
            """
            select request_digest, event_type, payload_json
              from agent_runtime_event
             where job_id = ? and invocation_id = ? and sequence = ?
            """,
            (job_id, invocation_id, sequence),
        )
        if persisted is None or (
            str(persisted["request_digest"]) != request_digest
            or str(persisted["event_type"]) != event_type
            or str(persisted["payload_json"]) != payload_json
        ):
            raise NonRetryableExecutionError(
                "Runtime event sequence conflicts with concurrently persisted data",
                safe_message="Runtime 事件与已保存记录冲突",
                error_code="runtime_event_digest_conflict",
            )

    def record_runtime_provenance(self, job_id: str, provenance: dict[str, Any]) -> None:
        allowed = {
            "runtime_kind",
            "runtime_version",
            "protocol_version",
            "sdk_version",
            "cli_version",
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

    def list_runtime_events(
        self,
        job_id: str,
        *,
        invocation_id: str = "",
    ) -> list[dict[str, Any]]:
        where = "job_id = ?"
        params: tuple[Any, ...] = (job_id,)
        if invocation_id:
            where += " and invocation_id = ?"
            params += (invocation_id,)
        rows = self.database.execute(
            f"""
            select * from agent_runtime_event
             where {where}
             order by invocation_id, sequence
            """,
            params,
        )
        return [
            {
                **row,
                "sequence": int(row["sequence"]),
                "payload": self._json_from_text(str(row["payload_json"])),
            }
            for row in rows
        ]

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

    def create_dispatch_event(
        self,
        *,
        job_id: str,
        job_idempotency_key: str,
        correlation_id: str,
        max_attempts: int = 8,
        max_replay_count: int = 3,
    ) -> JobDispatchEvent:
        timestamp = now_iso()
        event_id = new_id("job_dispatch")
        self.database.execute(
            """
            insert into job_dispatch_outbox
              (id, event_key, idempotency_key, job_id, correlation_id,
               status, attempt_count, max_attempts, replay_count,
               max_replay_count, next_attempt_at,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, 'PENDING', 0, ?, 0, ?, ?, ?, ?)
            on conflict(job_id) do nothing
            """,
            (
                event_id,
                f"job.dispatch:{job_id}",
                f"job.dispatch:{job_idempotency_key}",
                job_id,
                correlation_id,
                max(1, int(max_attempts)),
                max(0, int(max_replay_count)),
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        row = self.database.execute_one(
            "select * from job_dispatch_outbox where job_id = ?",
            (job_id,),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "Job dispatch event could not be persisted",
                safe_message="任务调度事件保存失败",
                error_code="job_dispatch_persistence_failed",
            )
        return self._dispatch_event_from_row(row)

    def get_dispatch_event_for_job(self, job_id: str) -> JobDispatchEvent | None:
        row = self.database.execute_one(
            "select * from job_dispatch_outbox where job_id = ?",
            (job_id,),
        )
        return self._dispatch_event_from_row(row) if row else None

    def get_dispatch_event(self, event_id: str) -> JobDispatchEvent:
        row = self.database.execute_one(
            "select * from job_dispatch_outbox where id = ?",
            (event_id,),
        )
        if row is None:
            raise NotFound(f"Job dispatch event not found: {event_id}")
        return self._dispatch_event_from_row(row)

    def claim_dispatch_event(
        self,
        *,
        worker_id: str,
        now: str | None = None,
    ) -> JobDispatchEvent | None:
        timestamp = now or now_iso()
        with self.database.unit_of_work():
            if self.database.engine == "postgres":
                rows = self.database.execute(
                    """
                    with candidate as (
                      select outbox.id
                        from job_dispatch_outbox outbox
                        join agent_job job on job.id = outbox.job_id
                       where outbox.status in ('PENDING', 'RETRY_WAIT')
                         and outbox.next_attempt_at <= ?
                         and outbox.attempt_count < outbox.max_attempts
                         and job.status in ('PENDING', 'RETRY_WAIT')
                       order by outbox.next_attempt_at, outbox.created_at, outbox.id
                       for update of outbox skip locked
                       limit 1
                    )
                    update job_dispatch_outbox
                       set status = 'RUNNING', claimed_by = ?, claimed_at = ?,
                           attempt_count = attempt_count + 1, updated_at = ?
                     where id = (select id from candidate)
                    returning *
                    """,
                    (timestamp, worker_id, timestamp, timestamp),
                )
            else:
                rows = self.database.execute(
                    """
                    update job_dispatch_outbox
                       set status = 'RUNNING', claimed_by = ?, claimed_at = ?,
                           attempt_count = attempt_count + 1, updated_at = ?
                     where id = (
                       select outbox.id
                         from job_dispatch_outbox outbox
                         join agent_job job on job.id = outbox.job_id
                        where outbox.status in ('PENDING', 'RETRY_WAIT')
                          and outbox.next_attempt_at <= ?
                          and outbox.attempt_count < outbox.max_attempts
                          and job.status in ('PENDING', 'RETRY_WAIT')
                        order by outbox.next_attempt_at, outbox.created_at, outbox.id
                        limit 1
                     )
                       and status in ('PENDING', 'RETRY_WAIT')
                    returning *
                    """,
                    (worker_id, timestamp, timestamp, timestamp),
                )
        return self._dispatch_event_from_row(rows[0]) if rows else None

    def mark_dispatch_published(self, *, event_id: str, worker_id: str) -> bool:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = 'PUBLISHED', published_at = ?, claimed_by = '',
                       claimed_at = null, last_error_code = '',
                       last_error_summary = '', updated_at = ?
                 where id = ? and status = 'RUNNING' and claimed_by = ?
                returning id
                """,
                (timestamp, timestamp, event_id, worker_id),
            )
        return bool(rows)

    def mark_dispatch_failed(
        self,
        *,
        event_id: str,
        worker_id: str,
        error_code: str,
        error_summary: str,
        retry_base_seconds: int,
    ) -> JobDispatchEvent:
        with self.database.unit_of_work():
            current = self.database.execute_one(
                """
                select * from job_dispatch_outbox
                 where id = ? and status = 'RUNNING' and claimed_by = ?
                """,
                (event_id, worker_id),
            )
            if current is None:
                raise NonRetryableExecutionError(
                    "Job dispatch claim ownership was lost",
                    safe_message="任务调度事件领取权已失效",
                    error_code="job_dispatch_claim_lost",
                )
            attempt_count = int(current["attempt_count"])
            max_attempts = int(current["max_attempts"])
            dead = attempt_count >= max_attempts
            delay_seconds = min(
                max(1, int(retry_base_seconds)) * (2 ** max(attempt_count - 1, 0)),
                3600,
            )
            timestamp = now_iso()
            next_attempt_at = (
                timestamp
                if dead
                else (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
            )
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = ?, next_attempt_at = ?, claimed_by = '',
                       claimed_at = null, dead_at = ?, last_error_code = ?,
                       last_error_summary = ?, updated_at = ?
                 where id = ? and status = 'RUNNING' and claimed_by = ?
                returning *
                """,
                (
                    JobDispatchStatus.DEAD.value if dead else JobDispatchStatus.RETRY_WAIT.value,
                    next_attempt_at,
                    timestamp if dead else None,
                    error_code[:100],
                    error_summary[:500],
                    timestamp,
                    event_id,
                    worker_id,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Job dispatch failure state could not be saved",
                    safe_message="任务调度失败状态保存失败",
                    error_code="job_dispatch_claim_lost",
                )
        return self._dispatch_event_from_row(rows[0])

    def rearm_dispatch_for_retry(
        self,
        *,
        job_id: str,
        next_attempt_at: str,
    ) -> JobDispatchEvent:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update job_dispatch_outbox
               set status = 'RETRY_WAIT', attempt_count = 0,
                   next_attempt_at = ?, claimed_by = '', claimed_at = null,
                   published_at = null, dead_at = null,
                   last_error_code = '', last_error_summary = '', updated_at = ?
             where job_id = ?
               and status in ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PUBLISHED')
            returning *
            """,
            (next_attempt_at, timestamp, job_id),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Job dispatch event is not eligible for retry rearming",
                safe_message="任务调度事件当前状态不允许安排执行重试",
                error_code="job_dispatch_retry_rearm_conflict",
            )
        return self._dispatch_event_from_row(rows[0])

    def rearm_dispatch_for_cutover(
        self,
        *,
        job_id: str,
        target_status: JobDispatchStatus,
        next_attempt_at: str,
    ) -> JobDispatchEvent:
        if target_status not in {
            JobDispatchStatus.PENDING,
            JobDispatchStatus.RETRY_WAIT,
        }:
            raise ValueError("Cutover target must be PENDING or RETRY_WAIT")
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update job_dispatch_outbox
               set status = ?, attempt_count = 0,
                   next_attempt_at = ?, claimed_by = '', claimed_at = null,
                   published_at = null, dead_at = null,
                   last_error_code = '', last_error_summary = '', updated_at = ?
             where job_id = ?
               and status in ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PUBLISHED')
            returning *
            """,
            (target_status.value, next_attempt_at, timestamp, job_id),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Job dispatch event cannot be converted from its current state",
                safe_message="任务调度事件当前状态无法安全切换",
                error_code="job_dispatch_cutover_state_conflict",
            )
        return self._dispatch_event_from_row(rows[0])

    def record_dispatch_cutover_quarantine(
        self,
        *,
        source_queue: str,
        message_digest: str,
        reason_code: str,
        actor_id: str,
        job_id: str = "",
    ) -> bool:
        rows = self.database.execute(
            """
            insert into job_dispatch_cutover_quarantine
              (id, source_queue, message_digest, job_id, reason_code,
               observed_at, observed_by)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(source_queue, message_digest) do nothing
            returning id
            """,
            (
                new_id("job_dispatch_quarantine"),
                source_queue,
                message_digest,
                job_id or None,
                reason_code,
                now_iso(),
                actor_id[:200],
            ),
        )
        return bool(rows)

    def dispatch_cutover_quarantine_count(self) -> int:
        row = self.database.execute_one(
            "select count(*) as count from job_dispatch_cutover_quarantine"
        )
        return int(row["count"]) if row else 0

    def recover_stale_dispatch_claims(
        self,
        *,
        stale_before: str,
    ) -> tuple[int, int]:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = case
                         when attempt_count >= max_attempts then 'DEAD'
                         else 'RETRY_WAIT'
                       end,
                       next_attempt_at = ?,
                       claimed_by = '',
                       claimed_at = null,
                       dead_at = case
                         when attempt_count >= max_attempts then ?
                         else dead_at
                       end,
                       last_error_code = 'job_dispatch_claim_expired',
                       last_error_summary = 'Dispatcher claim expired before completion',
                       updated_at = ?
                 where status = 'RUNNING' and claimed_at <= ?
                returning status
                """,
                (timestamp, timestamp, timestamp, stale_before),
            )
        return (
            sum(row["status"] == JobDispatchStatus.RETRY_WAIT.value for row in rows),
            sum(row["status"] == JobDispatchStatus.DEAD.value for row in rows),
        )

    def expire_terminal_job_dispatches(self) -> int:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update job_dispatch_outbox
                   set status = 'DEAD', dead_at = ?,
                       last_error_code = 'job_not_dispatchable',
                       last_error_summary = 'Job reached a terminal state before dispatch',
                       updated_at = ?
                 where status in ('PENDING', 'RETRY_WAIT')
                   and exists (
                     select 1 from agent_job
                      where agent_job.id = job_dispatch_outbox.job_id
                        and agent_job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT', 'CANCELLED')
                   )
                returning id
                """,
                (timestamp, timestamp),
            )
        return len(rows)

    def replay_dead_dispatch(
        self,
        *,
        event_id: str,
        actor_id: str,
    ) -> JobDispatchEvent:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update job_dispatch_outbox
               set status = 'PENDING', attempt_count = 0,
                   replay_count = replay_count + 1,
                   next_attempt_at = ?, claimed_by = '', claimed_at = null,
                   published_at = null, dead_at = null,
                   last_replayed_at = ?, last_replayed_by = ?,
                   last_error_code = '', last_error_summary = '', updated_at = ?
             where id = ? and status = 'DEAD'
               and replay_count < max_replay_count
               and exists (
                 select 1 from agent_job
                  where agent_job.id = job_dispatch_outbox.job_id
                    and agent_job.status = 'PENDING'
               )
            returning *
            """,
            (timestamp, timestamp, actor_id[:200], timestamp, event_id),
        )
        if rows:
            return self._dispatch_event_from_row(rows[0])
        current = self.get_dispatch_event(event_id)
        if current.status != JobDispatchStatus.DEAD:
            raise NonRetryableExecutionError(
                "Only DEAD dispatch events can be replayed",
                safe_message="只有 DEAD 调度事件可以重放",
                error_code="job_dispatch_replay_status_invalid",
            )
        if current.replay_count >= current.max_replay_count:
            raise NonRetryableExecutionError(
                "Job dispatch replay limit is exhausted",
                safe_message="任务调度事件已达到允许的重放次数上限",
                error_code="job_dispatch_replay_limit_exhausted",
            )
        job = self.get_job(current.job_id)
        raise NonRetryableExecutionError(
            f"Job is not dispatchable in status {job.status.value}",
            safe_message="任务当前状态不允许重新调度",
            error_code="job_dispatch_replay_job_not_pending",
        )

    def dispatch_metrics(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in JobDispatchStatus}
        for row in self.database.execute(
            """
            select status, count(*) as count
              from job_dispatch_outbox
             group by status
            """
        ):
            counts[str(row["status"])] = int(row["count"])
        oldest = (
            self.database.execute_one(
                """
            select min(next_attempt_at) as oldest_due_at,
                   max(attempt_count) as max_attempt_count
              from job_dispatch_outbox
             where status in ('PENDING', 'RETRY_WAIT', 'RUNNING')
            """
            )
            or {}
        )
        return {
            "counts": counts,
            "oldest_due_at": oldest.get("oldest_due_at"),
            "max_attempt_count": int(oldest.get("max_attempt_count") or 0),
        }

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
            f"""
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

    def create_delivery_event(
        self,
        *,
        job_id: str,
        result_artifact_id: str,
        application_publication_id: str,
        delivery_binding: dict[str, Any],
        target_summary: dict[str, Any],
        correlation_id: str,
        max_attempts: int,
        max_replay_count: int,
    ) -> DeliveryEvent:
        artifact = self.get_artifact(result_artifact_id)
        if str(artifact["job_id"]) != job_id:
            raise NonRetryableExecutionError(
                "Delivery artifact does not belong to the Job",
                safe_message="投递结果产物与任务不匹配",
                error_code="delivery_artifact_job_mismatch",
            )
        timestamp = now_iso()
        event_id = new_id("delivery_outbox")
        self.database.execute(
            """
            insert into delivery_outbox
              (id, event_key, job_id, result_artifact_id,
               application_publication_id, delivery_binding_json,
               target_summary, correlation_id, status, attempt_count,
               max_attempts, replay_count, max_replay_count,
               next_attempt_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, 0, ?, ?, ?, ?)
            on conflict(job_id, result_artifact_id) do nothing
            """,
            (
                event_id,
                f"delivery.result:{result_artifact_id}",
                job_id,
                result_artifact_id,
                application_publication_id,
                json.dumps(delivery_binding, ensure_ascii=False, sort_keys=True),
                json.dumps(target_summary, ensure_ascii=False, sort_keys=True),
                correlation_id,
                max(1, int(max_attempts)),
                max(0, int(max_replay_count)),
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        row = self.database.execute_one(
            """
            select * from delivery_outbox
             where job_id = ? and result_artifact_id = ?
            """,
            (job_id, result_artifact_id),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "Delivery event could not be persisted",
                safe_message="投递事件保存失败",
                error_code="delivery_outbox_persistence_failed",
            )
        return self._delivery_event_from_row(row)

    def get_delivery_event(self, delivery_id: str) -> DeliveryEvent:
        row = self.database.execute_one(
            "select * from delivery_outbox where id = ?",
            (delivery_id,),
        )
        if row is None:
            raise NotFound(f"Delivery event not found: {delivery_id}")
        return self._delivery_event_from_row(row)

    def get_delivery_event_for_job(self, job_id: str) -> DeliveryEvent | None:
        row = self.database.execute_one(
            """
            select * from delivery_outbox
             where job_id = ?
             order by created_at desc, id desc
             limit 1
            """,
            (job_id,),
        )
        return self._delivery_event_from_row(row) if row else None

    def list_delivery_events(self, job_id: str) -> list[dict[str, Any]]:
        """Return the safe, read-only Delivery lifecycle for a Job.

        The frozen binding and artifact body are deliberately not returned.
        Only the adapter identity and already-redacted target summary cross the
        API boundary.
        """
        self.get_job(job_id)
        rows = self.database.execute(
            """
            select id, job_id, result_artifact_id,
                   application_publication_id, delivery_binding_json,
                   target_summary, correlation_id, status,
                   attempt_count, max_attempts, replay_count, max_replay_count,
                   next_attempt_at, last_error_code, last_error_summary,
                   started_at, finished_at, dead_at,
                   last_replayed_at, created_at, updated_at
              from delivery_outbox
             where job_id = ?
             order by created_at, id
            """,
            (job_id,),
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            binding = self._json_from_text(str(row.pop("delivery_binding_json", "{}") or "{}"))
            if not isinstance(binding, dict):
                binding = {}
            target_summary = self._json_from_text(str(row.get("target_summary") or "{}"))
            events.append(
                {
                    **row,
                    "route_type": str(binding.get("route_type") or "none"),
                    "connector_id": str(binding.get("connector_id") or ""),
                    "delivery_kind": str(binding.get("delivery_kind") or "result"),
                    "target_summary": (target_summary if isinstance(target_summary, dict) else {}),
                    "terminal": str(row["status"]) in {"SUCCEEDED", "FAILED", "DEAD", "SKIPPED"},
                    "delivered": str(row["status"]) == "SUCCEEDED",
                }
            )
        return events

    def delivery_metrics(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in DeliveryStatus}
        for row in self.database.execute(
            """
            select status, count(*) as count
              from delivery_outbox
             group by status
            """
        ):
            counts[str(row["status"])] = int(row["count"])
        active = (
            self.database.execute_one(
                """
            select min(next_attempt_at) as oldest_due_at,
                   max(attempt_count) as max_attempt_count
              from delivery_outbox
             where status in ('PENDING', 'RETRY_WAIT', 'RUNNING')
            """
            )
            or {}
        )
        return {
            "counts": counts,
            "active_count": sum(counts[status] for status in ("PENDING", "RETRY_WAIT", "RUNNING")),
            "terminal_failure_count": counts["FAILED"] + counts["DEAD"],
            "oldest_due_at": active.get("oldest_due_at"),
            "max_attempt_count": int(active.get("max_attempt_count") or 0),
        }

    def replay_dead_delivery(
        self,
        *,
        delivery_id: str,
        actor_id: str,
    ) -> DeliveryEvent:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update delivery_outbox
               set status = 'PENDING',
                   attempt_count = 0,
                   replay_count = replay_count + 1,
                   next_attempt_at = ?,
                   claimed_by = '',
                   claim_token = '',
                   claimed_at = null,
                   claim_expires_at = null,
                   last_error_code = '',
                   last_error_summary = '',
                   started_at = null,
                   finished_at = null,
                   dead_at = null,
                   last_replayed_at = ?,
                   last_replayed_by = ?,
                   updated_at = ?
             where id = ?
               and status = 'DEAD'
               and replay_count < max_replay_count
               and exists (
                 select 1
                   from agent_job
                  where agent_job.id = delivery_outbox.job_id
                    and agent_job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
               )
            returning *
            """,
            (
                timestamp,
                timestamp,
                actor_id[:200],
                timestamp,
                delivery_id,
            ),
        )
        if rows:
            return self._delivery_event_from_row(rows[0])
        current = self.get_delivery_event(delivery_id)
        if current.status != DeliveryStatus.DEAD:
            raise NonRetryableExecutionError(
                "Only DEAD Delivery events can be replayed",
                safe_message="只有 DEAD 投递事件可以重放",
                error_code="delivery_replay_status_invalid",
            )
        if current.replay_count >= current.max_replay_count:
            raise NonRetryableExecutionError(
                "Delivery replay limit is exhausted",
                safe_message="投递事件已达到允许的重放次数上限",
                error_code="delivery_replay_limit_exhausted",
            )
        job = self.get_job(current.job_id)
        raise NonRetryableExecutionError(
            f"Job is not terminal in status {job.status.value}",
            safe_message="任务尚未结束，不能重放投递",
            error_code="delivery_replay_job_not_terminal",
        )

    def claim_delivery_event(
        self,
        *,
        worker_id: str,
        claim_timeout_seconds: int,
        now: str | None = None,
    ) -> DeliveryEvent | None:
        timestamp = now or now_iso()
        now_value = datetime.fromisoformat(timestamp)
        if now_value.tzinfo is None:
            now_value = now_value.replace(tzinfo=UTC)
        claim_expires_at = (
            now_value + timedelta(seconds=max(1, int(claim_timeout_seconds)))
        ).isoformat()
        claim_token = new_id("delivery_claim")
        with self.database.unit_of_work():
            if self.database.engine == "postgres":
                rows = self.database.execute(
                    """
                    with candidate as (
                      select outbox.id
                        from delivery_outbox outbox
                        join agent_job job on job.id = outbox.job_id
                       where outbox.status in ('PENDING', 'RETRY_WAIT')
                         and outbox.next_attempt_at <= ?
                         and outbox.attempt_count < outbox.max_attempts
                         and job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
                       order by outbox.next_attempt_at,
                                outbox.created_at,
                                outbox.id
                       for update of outbox skip locked
                       limit 1
                    )
                    update delivery_outbox
                       set status = 'RUNNING',
                           claimed_by = ?,
                           claim_token = ?,
                           claimed_at = ?,
                           claim_expires_at = ?,
                           started_at = coalesce(started_at, ?),
                           attempt_count = attempt_count + 1,
                           updated_at = ?
                     where id = (select id from candidate)
                    returning *
                    """,
                    (
                        timestamp,
                        worker_id,
                        claim_token,
                        timestamp,
                        claim_expires_at,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                rows = self.database.execute(
                    """
                    update delivery_outbox
                       set status = 'RUNNING',
                           claimed_by = ?,
                           claim_token = ?,
                           claimed_at = ?,
                           claim_expires_at = ?,
                           started_at = coalesce(started_at, ?),
                           attempt_count = attempt_count + 1,
                           updated_at = ?
                     where id = (
                       select outbox.id
                         from delivery_outbox outbox
                         join agent_job job on job.id = outbox.job_id
                        where outbox.status in ('PENDING', 'RETRY_WAIT')
                          and outbox.next_attempt_at <= ?
                          and outbox.attempt_count < outbox.max_attempts
                          and job.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
                        order by outbox.next_attempt_at,
                                 outbox.created_at,
                                 outbox.id
                        limit 1
                     )
                       and status in ('PENDING', 'RETRY_WAIT')
                    returning *
                    """,
                    (
                        worker_id,
                        claim_token,
                        timestamp,
                        claim_expires_at,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
        return self._delivery_event_from_row(rows[0]) if rows else None

    def create_delivery_attempt(
        self,
        *,
        event: DeliveryEvent,
    ) -> dict[str, Any]:
        attempt_id = new_id("delivery")
        idempotency_key = f"delivery.attempt:{event.id}:{event.replay_count}:{event.attempt_count}"
        timestamp = now_iso()
        self.database.execute(
            """
            insert into delivery_attempt
              (id, job_id, route_type, connector_id, target_summary,
               status, error_message, created_at, finished_at,
               delivery_outbox_id, replay_no, attempt_no, correlation_id,
               idempotency_key, error_code)
            values (?, ?, ?, ?, ?, 'RUNNING', null, ?, null, ?, ?, ?, ?, ?, '')
            on conflict(idempotency_key) do nothing
            """,
            (
                attempt_id,
                event.job_id,
                str(event.delivery_binding.get("route_type") or "none"),
                str(event.delivery_binding.get("connector_id") or ""),
                json.dumps(
                    event.target_summary,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
                event.id,
                event.replay_count,
                event.attempt_count,
                event.correlation_id,
                idempotency_key,
            ),
        )
        row = self.database.execute_one(
            f"""
            select * from delivery_attempt
             where idempotency_key = ?
            """,
            (idempotency_key,),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "Delivery attempt could not be persisted",
                safe_message="投递尝试保存失败",
                error_code="delivery_attempt_persistence_failed",
            )
        return row

    def has_successful_delivery_chunk(
        self,
        *,
        delivery_id: str,
        chunk_index: int,
        payload_hash: str,
    ) -> bool:
        row = self.database.execute_one(
            f"""
            select payload_hash
              from delivery_chunk
             where delivery_outbox_id = ?
               and chunk_index = ?
               and status = 'SUCCEEDED'
            """,
            (delivery_id, chunk_index),
        )
        if row is None:
            return False
        if str(row["payload_hash"]) != payload_hash:
            raise NonRetryableExecutionError(
                "Successful Delivery chunk payload hash changed",
                safe_message="投递分片内容与已成功记录不一致",
                error_code="delivery_chunk_payload_drift",
            )
        return True

    def record_delivery_chunk(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
        chunk_index: int,
        chunk_count: int,
        payload_hash: str,
        payload_summary: dict[str, Any],
        status: str,
        error_message: str = "",
    ) -> str:
        existing = self.database.execute_one(
            """
            select id from delivery_chunk
             where delivery_outbox_id = ?
               and replay_no = ?
               and attempt_no = ?
               and chunk_index = ?
            """,
            (
                event.id,
                event.replay_count,
                event.attempt_count,
                chunk_index,
            ),
        )
        sent_at = now_iso() if status == "SUCCEEDED" else None
        if existing is not None:
            self.database.execute(
                """
                update delivery_chunk
                   set status = ?, payload_summary = ?, error_message = ?,
                       payload_hash = ?, sent_at = ?
                 where id = ?
                """,
                (
                    status,
                    json.dumps(
                        payload_summary,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    error_message or None,
                    payload_hash,
                    sent_at,
                    str(existing["id"]),
                ),
            )
            return str(existing["id"])
        chunk_id = new_id("chunk")
        self.database.execute(
            """
            insert into delivery_chunk
              (id, attempt_id, chunk_index, chunk_count, status,
               payload_summary, error_message, created_at,
               delivery_outbox_id, replay_no, attempt_no, idempotency_key,
               payload_hash, sent_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                attempt_id,
                chunk_index,
                chunk_count,
                status,
                json.dumps(
                    payload_summary,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                error_message or None,
                now_iso(),
                event.id,
                event.replay_count,
                event.attempt_count,
                f"delivery.chunk:{event.id}:{chunk_index}:{payload_hash}",
                payload_hash,
                sent_at,
            ),
        )
        return chunk_id

    def mark_delivery_succeeded(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
    ) -> DeliveryEvent:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = 'SUCCEEDED',
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       last_error_code = '',
                       last_error_summary = '',
                       finished_at = ?,
                       updated_at = ?
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                returning *
                """,
                (
                    timestamp,
                    timestamp,
                    event.id,
                    event.claimed_by,
                    event.claim_token,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Delivery claim ownership was lost",
                    safe_message="投递事件领取权已失效",
                    error_code="delivery_claim_lost",
                )
            self.database.execute(
                """
                update delivery_attempt
                   set status = 'SUCCEEDED', error_code = '',
                       error_message = null, finished_at = ?
                 where id = ? and delivery_outbox_id = ?
                """,
                (timestamp, attempt_id, event.id),
            )
        return self._delivery_event_from_row(rows[0])

    def mark_delivery_skipped(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
    ) -> DeliveryEvent:
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = 'SKIPPED',
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       finished_at = ?,
                       updated_at = ?
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                returning *
                """,
                (
                    timestamp,
                    timestamp,
                    event.id,
                    event.claimed_by,
                    event.claim_token,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Delivery claim ownership was lost",
                    safe_message="投递事件领取权已失效",
                    error_code="delivery_claim_lost",
                )
            self.database.execute(
                """
                update delivery_attempt
                   set status = 'SKIPPED', finished_at = ?
                 where id = ? and delivery_outbox_id = ?
                """,
                (timestamp, attempt_id, event.id),
            )
        return self._delivery_event_from_row(rows[0])

    def mark_delivery_failed(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
        retryable: bool,
        error_code: str,
        error_summary: str,
        retry_base_seconds: int,
    ) -> DeliveryEvent:
        with self.database.unit_of_work():
            current = self.database.execute_one(
                """
                select * from delivery_outbox
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                """,
                (event.id, event.claimed_by, event.claim_token),
            )
            if current is None:
                raise NonRetryableExecutionError(
                    "Delivery claim ownership was lost",
                    safe_message="投递事件领取权已失效",
                    error_code="delivery_claim_lost",
                )
            attempt_count = int(current["attempt_count"])
            max_attempts = int(current["max_attempts"])
            exhausted = retryable and attempt_count >= max_attempts
            if not retryable:
                target = DeliveryStatus.FAILED
            elif exhausted:
                target = DeliveryStatus.DEAD
            else:
                target = DeliveryStatus.RETRY_WAIT
            timestamp = now_iso()
            delay_seconds = min(
                max(1, int(retry_base_seconds)) * (2 ** max(attempt_count - 1, 0)),
                3600,
            )
            next_attempt_at = (
                timestamp
                if target.terminal
                else (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
            )
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = ?,
                       next_attempt_at = ?,
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       last_error_code = ?,
                       last_error_summary = ?,
                       finished_at = ?,
                       dead_at = ?,
                       updated_at = ?
                 where id = ? and status = 'RUNNING'
                   and claimed_by = ? and claim_token = ?
                returning *
                """,
                (
                    target.value,
                    next_attempt_at,
                    error_code[:100],
                    error_summary[:500],
                    timestamp if target.terminal else None,
                    timestamp if target == DeliveryStatus.DEAD else None,
                    timestamp,
                    event.id,
                    event.claimed_by,
                    event.claim_token,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Delivery failure state could not be saved",
                    safe_message="投递失败状态保存失败",
                    error_code="delivery_claim_lost",
                )
            self.database.execute(
                """
                update delivery_attempt
                   set status = 'FAILED', error_code = ?,
                       error_message = ?, finished_at = ?
                 where id = ? and delivery_outbox_id = ?
                """,
                (
                    error_code[:100],
                    error_summary[:500],
                    timestamp,
                    attempt_id,
                    event.id,
                ),
            )
        return self._delivery_event_from_row(rows[0])

    def recover_stale_delivery_claims(self, *, now: str | None = None) -> tuple[int, int]:
        timestamp = now or now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update delivery_outbox
                   set status = case
                         when attempt_count >= max_attempts then 'DEAD'
                         else 'RETRY_WAIT'
                       end,
                       next_attempt_at = ?,
                       claimed_by = '',
                       claim_token = '',
                       claimed_at = null,
                       claim_expires_at = null,
                       last_error_code = 'delivery_claim_expired',
                       last_error_summary =
                         'Delivery Dispatcher claim expired before completion',
                       finished_at = case
                         when attempt_count >= max_attempts then ?
                         else null
                       end,
                       dead_at = case
                         when attempt_count >= max_attempts then ?
                         else dead_at
                       end,
                       updated_at = ?
                 where status = 'RUNNING'
                   and claim_expires_at is not null
                   and claim_expires_at <= ?
                returning id, status
                """,
                (
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            for row in rows:
                self.database.execute(
                    """
                    update delivery_attempt
                       set status = 'FAILED',
                           error_code = 'delivery_claim_expired',
                           error_message =
                             'Delivery Dispatcher claim expired before completion',
                           finished_at = ?
                     where delivery_outbox_id = ? and status = 'RUNNING'
                    """,
                    (timestamp, str(row["id"])),
                )
        return (
            sum(row["status"] == DeliveryStatus.RETRY_WAIT.value for row in rows),
            sum(row["status"] == DeliveryStatus.DEAD.value for row in rows),
        )

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
        invocation_id: str | None = None,
        runtime_tool_call_id: str | None = None,
        tool_origin: str = "unknown",
        server_code: str | None = None,
        mcp_call_id: str | None = None,
        persisted_by: str = "worker",
    ) -> str:
        tool_call_id = new_id("tool")
        safe_request = sanitize_for_persistence(request_payload)
        safe_response = sanitize_for_persistence(response_summary)
        response = (
            safe_response
            if isinstance(safe_response, str)
            else json.dumps(safe_response, ensure_ascii=False)
        )
        self.database.execute(
            """
            insert into agent_tool_call
              (id, job_id, tool_name, request_payload, response_summary, status,
               duration_ms, risk_level, audit_id, created_at, invocation_id,
               runtime_tool_call_id, tool_origin, server_code, mcp_call_id,
               persisted_by)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool_call_id,
                job_id,
                tool_name,
                json.dumps(safe_request, ensure_ascii=False),
                response,
                status,
                duration_ms,
                risk_level,
                audit_id,
                now_iso(),
                invocation_id,
                runtime_tool_call_id,
                tool_origin,
                server_code,
                mcp_call_id,
                persisted_by,
            ),
        )
        return tool_call_id

    def upsert_runtime_tool_call(
        self,
        *,
        job_id: str,
        invocation_id: str,
        runtime_tool_call_id: str,
        tool_origin: str,
        server_code: str | None,
        tool_name: str,
        request_payload: dict[str, Any],
        response_summary: dict[str, Any] | str,
        status: str,
        duration_ms: int,
        risk_level: str,
        mcp_call_id: str | None = None,
        persisted_tool_call_id: str | None = None,
    ) -> str | None:
        safe_request = sanitize_for_persistence(request_payload)
        safe_response = sanitize_for_persistence(response_summary)
        response = (
            safe_response
            if isinstance(safe_response, str)
            else json.dumps(safe_response, ensure_ascii=False)
        )
        if tool_origin == "mcp":
            if not mcp_call_id or not persisted_tool_call_id:
                # The MCP Server already owns the durable row. Missing metadata
                # is an explicit unlinked condition, never a reason to guess.
                return None
            rows = self.database.execute(
                """
                update agent_tool_call
                   set invocation_id = ?, runtime_tool_call_id = ?,
                       response_summary = case
                         when status = 'STARTED' then ? else response_summary end,
                       status = case when status = 'STARTED' then ? else status end,
                       duration_ms = case
                         when status = 'STARTED' then ? else duration_ms end
                 where id = ? and job_id = ? and mcp_call_id = ?
                   and tool_origin = 'mcp' and persisted_by = 'mcp_server'
                   and server_code = ? and tool_name = ?
                   and (invocation_id is null or invocation_id = ?)
                   and (runtime_tool_call_id is null or runtime_tool_call_id = ?)
                returning id
                """,
                (
                    invocation_id,
                    runtime_tool_call_id,
                    response,
                    status,
                    max(0, duration_ms),
                    persisted_tool_call_id,
                    job_id,
                    mcp_call_id,
                    server_code,
                    tool_name,
                    invocation_id,
                    runtime_tool_call_id,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "MCP Runtime metadata did not match its server-first Tool Call",
                    safe_message="MCP 工具调用关联不一致",
                    error_code="mcp_tool_call_link_mismatch",
                )
            return str(rows[0]["id"])

        if server_code is not None or mcp_call_id is not None or persisted_tool_call_id is not None:
            raise NonRetryableExecutionError(
                "Non-MCP Runtime Tool Event carried MCP-only identity",
                safe_message="Runtime 工具来源与关联信息不一致",
                error_code="runtime_tool_origin_invalid",
            )
        tool_call_id = new_id("tool")
        rows = self.database.execute(
            """
            insert into agent_tool_call
              (id, job_id, tool_name, request_payload, response_summary, status,
               duration_ms, risk_level, audit_id, created_at, invocation_id,
               runtime_tool_call_id, tool_origin, server_code, mcp_call_id,
               persisted_by)
            values (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, NULL, 'worker')
            on conflict(job_id, invocation_id, runtime_tool_call_id)
              where invocation_id is not null and runtime_tool_call_id is not null
            do update set
              response_summary = excluded.response_summary,
              status = case
                when agent_tool_call.status = 'STARTED' then excluded.status
                else agent_tool_call.status
              end,
              duration_ms = case
                when agent_tool_call.status = 'STARTED' then excluded.duration_ms
                else agent_tool_call.duration_ms
              end
            returning id
            """,
            (
                tool_call_id,
                job_id,
                tool_name,
                json.dumps(safe_request, ensure_ascii=False),
                response,
                status,
                max(0, duration_ms),
                risk_level,
                now_iso(),
                invocation_id,
                runtime_tool_call_id,
                tool_origin,
            ),
        )
        return str(rows[0]["id"])

    def complete_tool_call(
        self,
        tool_call_id: str,
        *,
        response_summary: dict[str, Any] | str,
        status: str,
        duration_ms: int,
    ) -> None:
        safe_response = sanitize_for_persistence(response_summary)
        response = (
            safe_response
            if isinstance(safe_response, str)
            else json.dumps(safe_response, ensure_ascii=False)
        )
        changed = self.database.execute(
            """
            update agent_tool_call
               set response_summary = ?, status = ?, duration_ms = ?
             where id = ?
            returning id
            """,
            (
                response,
                status,
                max(0, duration_ms),
                tool_call_id,
            ),
        )
        if not changed:
            raise NotFound(f"Agent tool call not found: {tool_call_id}")

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
            routing_context=self._json_from_text(row.get("routing_context_json") or "{}"),
            reply_route=self._json_from_text(row.get("reply_route_json") or "{}"),
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
            session_policy=self._json_from_text(row.get("session_policy_json") or "{}"),
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
            "business_application_route_decision": self._json_from_text(
                row.get("business_application_route_decision_json") or "{}"
            ),
            "execution_policy": self._json_from_text(row.get("execution_policy_json") or "{}"),
            "model_runtime_provenance": self._json_from_text(
                row.get("model_runtime_provenance_json") or "{}"
            ),
            "agent_runtime_kind": row.get("agent_runtime_kind") or "python-v1",
            "agent_runtime_protocol_version": (row.get("agent_runtime_protocol_version") or "1.0"),
            "tool_call_count": int(row.get("execution_policy_tool_call_count") or 0),
            "execution_policy_exhausted": bool(row.get("execution_policy_exhausted") or False),
            "routing_context": self._json_from_text(row.get("routing_context_json") or "{}"),
            "reply_route": self._json_from_text(row.get("reply_route_json") or "{}"),
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

    def list_tool_calls(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        rows = self.database.execute(
            """
            select id, job_id, tool_name, request_payload, response_summary,
                   status, duration_ms, risk_level, audit_id, created_at,
                   invocation_id, runtime_tool_call_id, tool_origin,
                   server_code, mcp_call_id, persisted_by
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
                timestamp
                if status in {"SUCCEEDED", "FAILED", "SKIPPED", "BLOCKED_BY_AUTHORIZATION"}
                else None,
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
                now_iso()
                if status in {"SUCCEEDED", "FAILED", "SKIPPED", "BLOCKED_BY_AUTHORIZATION"}
                else None,
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
                   error_message, created_at, finished_at,
                   delivery_outbox_id, replay_no, attempt_no, correlation_id,
                   idempotency_key, error_code
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
                   c.payload_summary, c.error_message, c.created_at,
                   c.delivery_outbox_id, c.replay_no, c.attempt_no, c.idempotency_key,
                   c.payload_hash, c.sent_at
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
                or (? = 1 and status = ? and agent_runtime_kind in ('python-v1', 'typescript-v1'))
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
            job_id=str(row["job_id"]),
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
            failure_code=str(row.get("failure_code") or ""),
        )

    def _dispatch_event_from_row(self, row: dict[str, Any]) -> JobDispatchEvent:
        return JobDispatchEvent(
            id=str(row["id"]),
            event_key=str(row["event_key"]),
            idempotency_key=str(row["idempotency_key"]),
            job_id=str(row["job_id"]),
            correlation_id=str(row["correlation_id"]),
            status=JobDispatchStatus(str(row["status"])),
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            replay_count=int(row["replay_count"]),
            max_replay_count=int(row["max_replay_count"]),
            next_attempt_at=str(row["next_attempt_at"]),
            claimed_by=str(row.get("claimed_by") or ""),
            claimed_at=row.get("claimed_at"),
            published_at=row.get("published_at"),
            dead_at=row.get("dead_at"),
            last_replayed_at=row.get("last_replayed_at"),
            last_replayed_by=str(row.get("last_replayed_by") or ""),
            last_error_code=str(row.get("last_error_code") or ""),
            last_error_summary=str(row.get("last_error_summary") or ""),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _delivery_event_from_row(self, row: dict[str, Any]) -> DeliveryEvent:
        return DeliveryEvent(
            id=str(row["id"]),
            event_key=str(row["event_key"]),
            job_id=str(row["job_id"]),
            result_artifact_id=str(row["result_artifact_id"]),
            application_publication_id=str(row.get("application_publication_id") or ""),
            delivery_binding=self._json_from_text(row.get("delivery_binding_json") or "{}"),
            target_summary=self._json_from_text(row.get("target_summary") or "{}"),
            correlation_id=str(row.get("correlation_id") or ""),
            status=DeliveryStatus(str(row["status"])),
            attempt_count=int(row.get("attempt_count") or 0),
            max_attempts=int(row["max_attempts"]),
            replay_count=int(row.get("replay_count") or 0),
            max_replay_count=int(row.get("max_replay_count") or 0),
            next_attempt_at=str(row["next_attempt_at"]),
            claimed_by=str(row.get("claimed_by") or ""),
            claim_token=str(row.get("claim_token") or ""),
            claimed_at=(str(row["claimed_at"]) if row.get("claimed_at") else None),
            claim_expires_at=(
                str(row["claim_expires_at"]) if row.get("claim_expires_at") else None
            ),
            last_error_code=str(row.get("last_error_code") or ""),
            last_error_summary=str(row.get("last_error_summary") or ""),
            started_at=(str(row["started_at"]) if row.get("started_at") else None),
            finished_at=(str(row["finished_at"]) if row.get("finished_at") else None),
            dead_at=str(row["dead_at"]) if row.get("dead_at") else None,
            last_replayed_at=(
                str(row["last_replayed_at"]) if row.get("last_replayed_at") else None
            ),
            last_replayed_by=str(row.get("last_replayed_by") or ""),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
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
            business_application_route_decision=self._json_from_text(
                row.get("business_application_route_decision_json") or "{}"
            ),
            execution_policy=self._json_from_text(row.get("execution_policy_json") or "{}"),
            execution_policy_tool_call_count=int(row.get("execution_policy_tool_call_count") or 0),
            execution_policy_exhausted=bool(row.get("execution_policy_exhausted") or False),
            model_runtime_provenance=self._json_from_text(
                row.get("model_runtime_provenance_json") or "{}"
            ),
            agent_runtime_kind=row.get("agent_runtime_kind") or "python-v1",
            agent_runtime_protocol_version=(row.get("agent_runtime_protocol_version") or "1.0"),
        )

    def _tool_call_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "tool_name": row["tool_name"],
            "request_payload": sanitize_for_persistence(
                self._json_from_text(row["request_payload"])
            ),
            "response_summary": sanitize_for_persistence(
                self._json_from_text(row["response_summary"])
            ),
            "status": row["status"],
            "duration_ms": int(row["duration_ms"]),
            "risk_level": row["risk_level"],
            "audit_id": row.get("audit_id"),
            "invocation_id": row.get("invocation_id"),
            "runtime_tool_call_id": row.get("runtime_tool_call_id"),
            "tool_origin": row.get("tool_origin") or "unknown",
            "server_code": row.get("server_code"),
            "mcp_call_id": row.get("mcp_call_id"),
            "persisted_by": row.get("persisted_by") or "worker",
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
        safe_summary = redact_sensitive_text(summary)
        safe_payload = sanitize_for_persistence(payload_summary or {})
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
        row["metadata"] = self._json_from_text(str(row.get("metadata") or "{}"))
        return row

    def _json_from_text(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
