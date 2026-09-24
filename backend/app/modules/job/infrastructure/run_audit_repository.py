from __future__ import annotations

import json
from typing import Any, cast

from app.modules.job.infrastructure.job_status_lookup import require_job_status
from app.modules.job.infrastructure.persistence_values import json_from_text, new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError
from app.shared.secret_redaction import sanitize_for_persistence
from app.shared.tool_contract import canonical_json_sha256
from app.shared.tool_response_summary import MAX_TOOL_SUMMARY_SOURCE_CHARS, tool_response_summary


RUN_AUDIT_FIELD_PAGE_CHARS = 64 * 1024
RUN_AUDIT_FIELD_COLUMNS: dict[str, tuple[str, str]] = {
    "context_manifest": ("context_manifest_json", "json"),
    "system_prompt": ("system_prompt", "text"),
    "user_prompt": ("user_prompt", "text"),
    "tool_definitions": ("tool_definitions_json", "json"),
    "permission_snapshot": ("permission_snapshot_json", "json"),
    "init_snapshot": ("init_snapshot_json", "json"),
    "sdk_messages": ("sdk_messages_json", "json"),
    "api_requests": ("api_requests_json", "json"),
    "api_responses": ("api_responses_json", "json"),
    "tool_executions": ("tool_executions_json", "json"),
    "model_requests": ("model_requests_json", "json"),
    "usage": ("usage_json", "json"),
    "error": ("error_json", "json"),
}


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
    if event_type == "tool_contract_observed":
        return _safe_tool_contract_observation(payload)
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
    if event_type == "audit_chunk":
        content = str(payload.get("content") or "")
        encoded_character_count = payload.get("encoded_character_count")
        return {
            "encoding": str(payload.get("encoding") or "")[:32],
            "chunk_index": _optional_nonnegative_integer(payload.get("chunk_index")),
            "chunk_count": _optional_nonnegative_integer(payload.get("chunk_count")),
            "sha256": str(payload.get("sha256") or "")[:64],
            "content_status": "OMITTED",
            "encoded_character_count": _optional_nonnegative_integer(
                encoded_character_count if encoded_character_count is not None else len(content)
            ),
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
            safe["runtime_provenance"] = sanitize_for_persistence(payload["runtime_provenance"])
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
    sanitized = sanitize_for_persistence(payload)
    return dict(sanitized) if isinstance(sanitized, dict) else {}


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
                "estimated_cost_usd": _optional_nonnegative_number(item.get("estimated_cost_usd")),
            }
        )
    result["model_usage"] = result["model_usage"][:64]
    return result


def _safe_tool_contract_observation(payload: dict[str, Any]) -> dict[str, Any]:
    supplied_hash = str(payload.get("observation_hash") or "")
    unhashed = {key: value for key, value in payload.items() if key != "observation_hash"}
    if len(supplied_hash) != 64 or canonical_json_sha256(unhashed) != supplied_hash:
        raise NonRetryableExecutionError(
            "Runtime Tool contract observation hash is invalid",
            safe_message="Runtime 工具契约观测无效",
            error_code="runtime_tool_contract_observation_invalid",
        )
    frozen = [
        {
            "server_code": str(item.get("server_code") or "")[:128],
            "tool_name": str(item.get("tool_name") or "")[:128],
            "schema_hash": str(item.get("schema_hash") or "")[:64],
        }
        for item in payload.get("frozen_tools") or []
        if isinstance(item, dict)
    ][:128]
    live_source = payload.get("file_mcp_live")
    live_value = live_source if isinstance(live_source, dict) else {}
    live: dict[str, Any] = {
        "status": str(live_value.get("status") or "NOT_OBSERVED")[:32],
        "tools": [
            {
                "server_code": str(item.get("server_code") or "")[:128],
                "tool_name": str(item.get("tool_name") or "")[:128],
                "schema_hash": str(item.get("schema_hash") or "")[:64],
                "status": str(item.get("status") or "")[:32],
            }
            for item in live_value.get("tools") or []
            if isinstance(item, dict)
        ][:128],
    }
    if live_value.get("toolset_hash"):
        live["toolset_hash"] = str(live_value["toolset_hash"])[:64]
    if isinstance(live_value.get("build_identity"), dict):
        live["build_identity"] = _safe_build_identity(live_value["build_identity"])
    effective = [
        {
            **{
                "server_code": str(item.get("server_code") or "")[:128],
                "tool_name": str(item.get("tool_name") or "")[:128],
                "sdk_tool_name": str(item.get("sdk_tool_name") or "")[:256],
                "origin": str(item.get("origin") or "")[:32],
                "schema_hash": str(item.get("schema_hash") or "")[:64],
                "authorization_status": str(item.get("authorization_status") or "")[:32],
            },
            **(
                {"dependency_tool_name": str(item["dependency_tool_name"])[:128]}
                if item.get("dependency_tool_name")
                else {}
            ),
        }
        for item in payload.get("effective_tools") or []
        if isinstance(item, dict)
    ][:128]
    prompt_source = payload.get("prompt")
    prompt_value = prompt_source if isinstance(prompt_source, dict) else {}
    prompt = {
        "template_version": str(prompt_value.get("template_version") or "")[:128],
        "contract_hash": str(prompt_value.get("contract_hash") or "")[:64],
        "declared_tools": [str(value)[:256] for value in prompt_value.get("declared_tools") or []][
            :128
        ],
    }
    rows = [
        {
            "server_code": str(item.get("server_code") or "")[:128],
            "tool_name": str(item.get("tool_name") or "")[:128],
            "status": str(item.get("status") or "")[:32],
        }
        for item in payload.get("rows") or []
        if isinstance(item, dict)
    ][:256]
    identities = [
        _safe_build_identity(item)
        for item in payload.get("component_build_identities") or []
        if isinstance(item, dict)
    ][:4]
    safe = {
        "observation_hash": supplied_hash,
        "snapshot_hash": str(payload.get("snapshot_hash") or "")[:64],
        "status": str(payload.get("status") or "NOT_OBSERVED")[:32],
        "frozen_tools": frozen,
        "file_mcp_live": live,
        "effective_tools": effective,
        "prompt": prompt,
        "rows": rows,
        "component_build_identities": identities,
    }
    if safe != payload:
        raise NonRetryableExecutionError(
            "Runtime Tool contract observation contains unsafe or invalid fields",
            safe_message="Runtime 工具契约观测无效",
            error_code="runtime_tool_contract_observation_invalid",
        )
    return safe


def _safe_build_identity(value: dict[str, Any]) -> dict[str, str]:
    safe = {
        key: str(value.get(key) or "")[:128]
        for key in ("component", "source_revision", "build_id", "platform")
    }
    if value.get("image_digest"):
        safe["image_digest"] = str(value["image_digest"])[:71]
    return safe


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
        candidate = int(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if 0 <= candidate <= 9_223_372_036_854_775_807 else None


def _optional_nonnegative_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        candidate = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if 0 <= candidate < float("inf") else None


def _optional_bounded_string(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:maximum] if text else None


class RunAuditRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record_runtime_event(self, job_id: str, event: dict[str, Any]) -> None:
        invocation_id = str(event.get("invocation_id") or "")
        request_digest = str(event.get("request_digest") or "")
        sequence = int(event.get("sequence") or 0)
        event_type = str(event.get("event_type") or "")
        if (
            not invocation_id
            or len(request_digest) != 64
            or sequence < 1
            or event_type
            not in {
                "execution_started",
                "runtime_initialized",
                "tool_contract_observed",
                "model_call",
                "api_retry",
                "audit_chunk",
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
                "payload": json_from_text(str(row["payload_json"])),
            }
            for row in rows
        ]

    def record_run_audit(
        self,
        *,
        job_id: str,
        invocation_id: str,
        request_digest: str,
        attempt_no: int,
        status: str,
        audit: dict[str, Any],
    ) -> str:
        """Persist one complete Runtime invocation snapshot without content filtering."""
        if status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise NonRetryableExecutionError(
                "Agent run audit status is invalid",
                safe_message="Agent 运行审计状态无效",
                error_code="agent_run_audit_invalid",
            )
        normalized_attempt = max(1, min(int(attempt_no), 32))
        audit_sha256 = canonical_json_sha256(audit)
        timestamp = now_iso()
        audit_id = new_id("run_audit")

        def encoded(field: str, fallback: object) -> str:
            value = audit.get(field, fallback)
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )

        self.database.execute(
            """
            insert into agent_run_audit
              (id, job_id, invocation_id, request_digest, attempt_no, status,
               audit_sha256, context_manifest_json, system_prompt, user_prompt,
               tool_definitions_json, permission_snapshot_json, init_snapshot_json,
               sdk_messages_json, api_requests_json, api_responses_json,
               tool_executions_json, model_requests_json, usage_json, summary_json,
               raw_api_capture_status, provider_thinking_disclosure, error_json,
               started_at, finished_at, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?)
            on conflict(job_id, invocation_id) do nothing
            """,
            (
                audit_id,
                job_id,
                invocation_id,
                request_digest,
                normalized_attempt,
                status,
                audit_sha256,
                encoded("context_manifest", {}),
                str(audit.get("system_prompt") or ""),
                str(audit.get("user_prompt") or ""),
                encoded("tool_definitions", []),
                encoded("permission_snapshot", {}),
                encoded("init_snapshot", {}),
                encoded("sdk_messages", []),
                encoded("api_requests", []),
                encoded("api_responses", []),
                encoded("tool_executions", []),
                encoded("model_requests", []),
                encoded("usage", {}),
                encoded("summary", {}),
                str(audit.get("raw_api_capture_status") or "unavailable"),
                str(audit.get("provider_thinking_disclosure") or ""),
                encoded("error", {}),
                str(audit.get("started_at") or timestamp),
                str(audit.get("finished_at") or timestamp),
                timestamp,
            ),
        )
        persisted = self.database.execute_one(
            """
            select id, request_digest, audit_sha256, attempt_no, status
              from agent_run_audit
             where job_id = ? and invocation_id = ?
            """,
            (job_id, invocation_id),
        )
        if persisted is None:
            raise NonRetryableExecutionError(
                "Agent run audit could not be persisted",
                safe_message="Agent 运行审计保存失败",
                error_code="agent_run_audit_persistence_failed",
            )
        if (
            str(persisted.get("request_digest") or "") != request_digest
            or str(persisted.get("audit_sha256") or "") != audit_sha256
            or int(persisted.get("attempt_no") or 0) != normalized_attempt
            or str(persisted.get("status") or "") != status
        ):
            raise NonRetryableExecutionError(
                "Agent run audit replay conflicts with the persisted invocation",
                safe_message="Agent 运行审计重放冲突",
                error_code="agent_run_audit_conflict",
            )
        return str(persisted["id"])

    def list_run_audits(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from agent_run_audit
             where job_id = ?
             order by attempt_no, invocation_id
            """,
            (job_id,),
        )
        json_fields: dict[str, object] = {
            "context_manifest_json": {},
            "tool_definitions_json": [],
            "permission_snapshot_json": {},
            "init_snapshot_json": {},
            "sdk_messages_json": [],
            "api_requests_json": [],
            "api_responses_json": [],
            "tool_executions_json": [],
            "model_requests_json": [],
            "usage_json": {},
            "summary_json": {},
            "error_json": {},
        }
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for field, fallback in json_fields.items():
                value = json_from_text(str(item.pop(field, "") or ""))
                item[field.removesuffix("_json")] = (
                    value if isinstance(value, type(fallback)) else fallback
                )
            item["attempt_no"] = int(item.get("attempt_no") or 0)
            result.append(item)
        return result

    def list_run_audit_summaries(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id, job_id, invocation_id, request_digest, attempt_no, status,
                   audit_sha256, summary_json, raw_api_capture_status,
                   provider_thinking_disclosure, started_at, finished_at, created_at
              from agent_run_audit
             where job_id = ?
             order by attempt_no, invocation_id
            """,
            (job_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            summary = json_from_text(str(item.pop("summary_json", "") or ""))
            item["summary"] = summary if isinstance(summary, dict) else {}
            item["attempt_no"] = int(item.get("attempt_no") or 0)
            result.append(item)
        return result

    def read_run_audit_field(
        self,
        *,
        job_id: str,
        audit_id: str,
        field: str,
        offset: int,
    ) -> dict[str, Any] | None:
        field_contract = RUN_AUDIT_FIELD_COLUMNS.get(field)
        if field_contract is None:
            raise NonRetryableExecutionError(
                "Agent run audit field is invalid",
                safe_message="Agent 运行审计字段无效",
                error_code="agent_run_audit_field_invalid",
            )
        if offset < 0:
            raise NonRetryableExecutionError(
                "Agent run audit field offset is invalid",
                safe_message="Agent 运行审计分页游标无效",
                error_code="agent_run_audit_cursor_invalid",
            )
        column, content_type = field_contract
        row = self.database.execute_one(
            f"""
            select length(coalesce({column}, '')) as total_chars,
                   substr(coalesce({column}, ''), ?, ?) as content
              from agent_run_audit
             where job_id = ? and id = ?
            """,
            (offset + 1, RUN_AUDIT_FIELD_PAGE_CHARS, job_id, audit_id),
        )
        if row is None:
            return None
        content = str(row.get("content") or "")
        total_chars = int(row.get("total_chars") or 0)
        if offset > total_chars:
            raise NonRetryableExecutionError(
                "Agent run audit field offset exceeds content length",
                safe_message="Agent 运行审计分页游标无效",
                error_code="agent_run_audit_cursor_invalid",
            )
        end_offset = min(offset + len(content), total_chars)
        return {
            "audit_id": audit_id,
            "field": field,
            "content_type": content_type,
            "content": content,
            "start_offset": offset,
            "end_offset": end_offset,
            "total_chars": total_chars,
            "has_more": end_offset < total_chars,
        }

    def count_tool_calls_for_invocation(self, job_id: str, invocation_id: str) -> int:
        row = self.database.execute_one(
            """
            select count(*) as tool_call_count
              from agent_tool_call
             where job_id = ? and invocation_id = ?
            """,
            (job_id, invocation_id),
        )
        return int((row or {}).get("tool_call_count") or 0)

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

    def list_tool_calls(self, job_id: str) -> list[dict[str, Any]]:
        require_job_status(self.database, job_id)
        rows = self.database.execute(
            """
            select id, job_id, tool_name, request_payload,
                   case when length(response_summary) <= ? then response_summary
                        else null end as response_summary,
                   status, duration_ms, risk_level, audit_id, created_at,
                   invocation_id, runtime_tool_call_id, tool_origin,
                   server_code, mcp_call_id, persisted_by
            from agent_tool_call
            where job_id = ?
            order by created_at, id
            """,
            (MAX_TOOL_SUMMARY_SOURCE_CHARS, job_id),
        )
        return [self._tool_call_from_row(row) for row in rows]

    def _tool_call_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "tool_name": row["tool_name"],
            "request_payload": sanitize_for_persistence(json_from_text(row["request_payload"])),
            "response_summary": tool_response_summary(row["response_summary"]),
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
