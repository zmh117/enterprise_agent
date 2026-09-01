from __future__ import annotations

import base64
import hashlib
import json
from binascii import Error as BinasciiError
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from app.modules.job.domain.execution_audit import (
    AccountingStatus,
    ExecutionFailureStage,
    ExecutionStatus,
    TOKEN_FIELDS,
    TokenUsage,
    bounded_text,
)
from app.modules.job.infrastructure.repositories import AgentRepository, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


class ExecutionAuditRepository:
    """Safe, replayable projections built only from validated Runtime events."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._runtime_events = AgentRepository(database)

    def record_runtime_event(self, job_id: str, event: dict[str, Any]) -> None:
        with self.database.unit_of_work():
            self._runtime_events.record_runtime_event(job_id, event)
            if event.get("event_type") == "model_call":
                self._upsert_model_call(job_id, event)
            elif event.get("event_type") == "tool_contract_observed":
                self._project_tool_contract(job_id, event)

    def _project_tool_contract(self, job_id: str, event: dict[str, Any]) -> None:
        payload = _dict_payload(event.get("payload"))
        status = str(payload.get("status") or "")
        if status not in {"MATCH", "DRIFT", "NOT_OBSERVED"}:
            raise NonRetryableExecutionError(
                "Runtime Tool contract status is invalid",
                safe_message="Runtime 工具契约状态无效",
                error_code="runtime_tool_contract_observation_invalid",
            )
        current = self.database.execute_one(
            "select tool_contract_status from agent_job where id = ?",
            (job_id,),
        )
        if current is None:
            raise NonRetryableExecutionError(
                "Agent Job does not exist",
                safe_message="未找到 Agent 任务",
                error_code="agent_job_not_found",
            )
        projected_status = (
            "DRIFT"
            if str(current.get("tool_contract_status") or "") == "DRIFT" or status == "DRIFT"
            else status
        )
        prompt = _dict_payload(payload.get("prompt"))
        self.database.execute(
            """
            update agent_job
               set tool_contract_status = ?,
                   tool_contract_last_invocation_id = ?,
                   tool_contract_observation_hash = ?,
                   prompt_template_version = ?,
                   prompt_contract_hash = ?
             where id = ?
            """,
            (
                projected_status,
                str(event.get("invocation_id") or "")[:128],
                str(payload.get("observation_hash") or "")[:64],
                str(prompt.get("template_version") or "")[:128],
                str(prompt.get("contract_hash") or "")[:64],
                job_id,
            ),
        )

    def rebuild_tool_contract_projection(self, job_id: str) -> dict[str, str]:
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                select invocation_id, payload_json
                  from agent_runtime_event
                 where job_id = ? and event_type = 'tool_contract_observed'
                 order by created_at, id
                """,
                (job_id,),
            )
            status = "NOT_OBSERVED"
            last_invocation_id = ""
            observation_hash = ""
            template_version = ""
            prompt_contract_hash = ""
            for row in rows:
                payload = _dict_payload(json.loads(str(row["payload_json"])))
                observed = str(payload.get("status") or "NOT_OBSERVED")
                if status != "DRIFT":
                    status = "DRIFT" if observed == "DRIFT" else observed
                last_invocation_id = str(row.get("invocation_id") or "")
                observation_hash = str(payload.get("observation_hash") or "")
                prompt = _dict_payload(payload.get("prompt"))
                template_version = str(prompt.get("template_version") or "")
                prompt_contract_hash = str(prompt.get("contract_hash") or "")
            updated = self.database.execute_one(
                """
                update agent_job
                   set tool_contract_status = ?,
                       tool_contract_last_invocation_id = ?,
                       tool_contract_observation_hash = ?,
                       prompt_template_version = ?,
                       prompt_contract_hash = ?
                 where id = ?
                returning id
                """,
                (
                    status,
                    last_invocation_id,
                    observation_hash,
                    template_version,
                    prompt_contract_hash,
                    job_id,
                ),
            )
            if updated is None:
                raise NonRetryableExecutionError(
                    "Agent Job does not exist",
                    safe_message="未找到 Agent 任务",
                    error_code="agent_job_not_found",
                )
        return {
            "status": status,
            "last_invocation_id": last_invocation_id,
            "observation_hash": observation_hash,
            "prompt_template_version": template_version,
            "prompt_contract_hash": prompt_contract_hash,
        }

    def _upsert_model_call(self, job_id: str, event: dict[str, Any]) -> None:
        payload = _dict_payload(event.get("payload"))
        usage = TokenUsage.from_payload(payload.get("usage"))
        model_call_id = bounded_text(payload.get("model_call_id"), 128)
        if not model_call_id:
            raise NonRetryableExecutionError(
                "Runtime model call identity is missing",
                safe_message="模型轮次身份无效",
                error_code="runtime_model_call_identity_invalid",
            )
        identity = (
            job_id,
            str(event.get("invocation_id") or ""),
            int(event.get("sequence") or 0),
        )
        previous_events = self._runtime_events.list_runtime_events(
            job_id,
            invocation_id=identity[1],
        )
        previous_same_calls = [
            item
            for item in previous_events
            if item["event_type"] == "model_call"
            and int(item["sequence"]) < identity[2]
            and isinstance(item.get("payload"), dict)
            and bounded_text(item["payload"].get("model_call_id"), 128) == model_call_id
        ]
        if previous_same_calls:
            signature = _model_call_signature(payload)
            if any(
                _model_call_signature(item["payload"]) != signature for item in previous_same_calls
            ):
                raise NonRetryableExecutionError(
                    "Runtime model call identity conflicts with an earlier event",
                    safe_message="模型轮次与已保存记录冲突",
                    error_code="runtime_model_call_conflict",
                )
            for previous in previous_same_calls:
                projected = self.database.execute_one(
                    """
                    select id from agent_model_call
                     where job_id = ? and invocation_id = ? and runtime_sequence = ?
                    """,
                    (job_id, identity[1], int(previous["sequence"])),
                )
                if projected is not None:
                    return
        timestamp = now_iso()
        values: dict[str, Any] = {
            "id": "model_call_"
            + hashlib.sha256(f"{identity[0]}:{identity[1]}:{identity[2]}".encode()).hexdigest()[
                :32
            ],
            "job_id": job_id,
            "invocation_id": identity[1],
            "request_digest": str(event.get("request_digest") or ""),
            "runtime_sequence": identity[2],
            "provider_request_id": bounded_text(payload.get("provider_request_id"), 200),
            "provider_message_id": bounded_text(payload.get("provider_message_id"), 200),
            "model_id": bounded_text(payload.get("model_id"), 200) or "unknown",
            "status": str(payload.get("status") or "FAILED"),
            "started_at": bounded_text(payload.get("started_at"), 64),
            "completed_at": bounded_text(payload.get("completed_at"), 64)
            or bounded_text(event.get("timestamp"), 64)
            or timestamp,
            "duration_ms": _optional_nonnegative(payload.get("duration_ms")),
            "duration_source": str(payload.get("duration_source") or "UNAVAILABLE"),
            **usage.as_dict(),
            "stop_reason": bounded_text(payload.get("stop_reason"), 128),
            "error_code": bounded_text(payload.get("error_code"), 128),
            "error_summary": bounded_text(payload.get("error_summary"), 2048),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if values["duration_source"] == "UNAVAILABLE":
            values["started_at"] = None
            values["duration_ms"] = None
        existing = self.database.execute_one(
            """
            select * from agent_model_call
             where job_id = ? and invocation_id = ? and runtime_sequence = ?
            """,
            identity,
        )
        if existing is not None:
            compared = tuple(key for key in values if key not in {"id", "created_at", "updated_at"})
            if any(_comparable(existing.get(key)) != _comparable(values[key]) for key in compared):
                raise NonRetryableExecutionError(
                    "Runtime model call conflicts with persisted projection",
                    safe_message="模型轮次与已保存记录冲突",
                    error_code="runtime_model_call_conflict",
                )
            return
        columns = tuple(values)
        self.database.execute(
            f"insert into agent_model_call ({', '.join(columns)}) values "
            f"({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )

    def rebuild_summary(self, job_id: str) -> dict[str, Any]:
        self.rebuild_tool_contract_projection(job_id)
        with self.database.unit_of_work():
            job = self.database.execute_one(
                """
                select status, retry_count, max_retry_count, last_error_code,
                       error_message, agent_runtime_protocol_version
                  from agent_job where id = ?
                """,
                (job_id,),
            )
            if job is None:
                raise NonRetryableExecutionError(
                    "Agent Job does not exist",
                    safe_message="未找到 Agent 任务",
                    error_code="agent_job_not_found",
                )
            events = self._runtime_events.list_runtime_events(job_id)
            terminals = [event for event in events if event["event_type"] == "terminal"]
            accounting = [
                event["payload"].get("accounting")
                for event in terminals
                if isinstance(event.get("payload"), dict)
                and isinstance(event["payload"].get("accounting"), dict)
            ]
            model_rows = self.database.execute(
                "select * from agent_model_call where job_id = ? order by invocation_id, runtime_sequence",
                (job_id,),
            )
            aggregate = _aggregate_accounting(accounting, model_rows)
            failure_stage, event_failure_code, event_failure_summary = _classify_failure(events)
            execution_status = _execution_status(str(job.get("status") or ""))
            failure_code = event_failure_code or bounded_text(job.get("last_error_code"), 128)
            failure_summary = event_failure_summary or bounded_text(job.get("error_message"), 2048)
            if execution_status == ExecutionStatus.SUCCEEDED:
                failure_stage = None
                failure_code = None
                failure_summary = None
            timestamp = now_iso()
            values = {
                "job_id": job_id,
                **aggregate,
                "observed_model_turn_count": len(model_rows),
                "api_retry_count": sum(event["event_type"] == "api_retry" for event in events),
                "runtime_invocation_count": len(
                    {
                        str(event["invocation_id"])
                        for event in events
                        if event["event_type"] == "terminal"
                    }
                ),
                "execution_status": execution_status.value,
                "execution_failure_stage": failure_stage.value if failure_stage else None,
                "failure_code": failure_code,
                "failure_summary": failure_summary,
                "retry_exhausted": int(
                    execution_status == ExecutionStatus.FAILED
                    and int(job.get("retry_count") or 0) >= int(job.get("max_retry_count") or 0)
                ),
                "source_protocol_version": str(job.get("agent_runtime_protocol_version") or "1.5"),
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            existing = self.database.execute_one(
                "select created_at from agent_job_execution_summary where job_id = ?",
                (job_id,),
            )
            if existing:
                values["created_at"] = existing["created_at"]
            columns = tuple(values)
            updates = tuple(column for column in columns if column not in {"job_id", "created_at"})
            self.database.execute(
                f"insert into agent_job_execution_summary ({', '.join(columns)}) values "
                f"({', '.join('?' for _ in columns)}) "
                f"on conflict(job_id) do update set {', '.join(f'{column} = excluded.{column}' for column in updates)}",
                tuple(values[column] for column in columns),
            )
        return self.get_summary(job_id)

    def get_summary(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_job_execution_summary where job_id = ?",
            (job_id,),
        )
        if row is None:
            return _unavailable_summary(job_id)
        item = dict(row)
        item["retry_exhausted"] = bool(item["retry_exhausted"])
        item["estimated_cost_usd"] = _decimal_text(item.get("estimated_cost_usd"))
        item["model_usage"] = _json_list(item.pop("model_usage_json", "[]"))
        for field in (
            "observed_model_turn_count",
            "api_retry_count",
            "runtime_invocation_count",
            "total_duration_ms",
            "total_api_duration_ms",
            *TOKEN_FIELDS,
        ):
            item[field] = int(item[field]) if item.get(field) is not None else None
        return item

    def list_model_calls(
        self, job_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        bounded_limit = min(max(int(limit), 1), 100)
        params: list[Any] = [job_id]
        where = "job_id = ?"
        if cursor:
            invocation_id, runtime_sequence, model_call_id = _decode_model_call_cursor(cursor)
            where += """
                and (
                    invocation_id > ?
                    or (invocation_id = ? and runtime_sequence > ?)
                    or (invocation_id = ? and runtime_sequence = ? and id > ?)
                )
            """
            params.extend(
                [
                    invocation_id,
                    invocation_id,
                    runtime_sequence,
                    invocation_id,
                    runtime_sequence,
                    model_call_id,
                ]
            )
        params.append(bounded_limit + 1)
        rows = self.database.execute(
            f"""
            select * from agent_model_call where {where}
             order by invocation_id, runtime_sequence, id limit ?
            """,
            params,
        )
        has_more = len(rows) > bounded_limit
        selected = rows[:bounded_limit]
        items = [_model_call(row) for row in selected]
        next_cursor = None
        if has_more and selected:
            last = selected[-1]
            next_cursor = _encode_model_call_cursor(
                str(last["invocation_id"]),
                int(last["runtime_sequence"]),
                str(last["id"]),
            )
        return {
            "items": items,
            "limit": bounded_limit,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }


def _encode_model_call_cursor(invocation_id: str, runtime_sequence: int, model_call_id: str) -> str:
    payload = json.dumps(
        {
            "invocation_id": invocation_id,
            "runtime_sequence": runtime_sequence,
            "id": model_call_id,
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_model_call_cursor(cursor: str) -> tuple[str, int, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
        invocation_id = str(value["invocation_id"])
        runtime_sequence = int(value["runtime_sequence"])
        model_call_id = str(value["id"])
        if not invocation_id or runtime_sequence < 1 or not model_call_id:
            raise ValueError
        return invocation_id, runtime_sequence, model_call_id
    except (
        BinasciiError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise NonRetryableExecutionError(
            "Model call pagination cursor is invalid",
            safe_message="模型请求分页游标无效，请刷新后重试",
            error_code="invalid_cursor",
            field_errors=[{"field": "cursor", "message": "分页游标无效"}],
        ) from exc


def _aggregate_accounting(
    accounting: list[dict[str, Any]], model_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if accounting:
        statuses = {str(item.get("status") or "UNAVAILABLE") for item in accounting}
        status = (
            AccountingStatus.COMPLETE
            if statuses == {"COMPLETE"}
            else AccountingStatus.PARTIAL
            if statuses & {"COMPLETE", "PARTIAL"}
            else AccountingStatus.UNAVAILABLE
        )
        usages = [TokenUsage.from_payload(item.get("usage")) for item in accounting]
        model_usage = _aggregate_model_usage(accounting)
        return {
            "accounting_status": status.value,
            "total_duration_ms": _sum_optional(accounting, "duration_ms"),
            "total_api_duration_ms": _sum_optional(accounting, "duration_api_ms"),
            **{
                field: _sum_values([getattr(usage, field) for usage in usages])
                for field in TOKEN_FIELDS
            },
            "model_usage_json": json.dumps(model_usage, sort_keys=True, separators=(",", ":")),
            "estimated_cost_usd": _sum_decimal(accounting, "estimated_cost_usd"),
        }
    if model_rows:
        return {
            "accounting_status": AccountingStatus.PARTIAL.value,
            "total_duration_ms": None,
            "total_api_duration_ms": _sum_values([row.get("duration_ms") for row in model_rows]),
            **{
                field: _sum_values([row.get(field) for row in model_rows]) for field in TOKEN_FIELDS
            },
            "model_usage_json": "[]",
            "estimated_cost_usd": None,
        }
    return {
        "accounting_status": AccountingStatus.UNAVAILABLE.value,
        "total_duration_ms": None,
        "total_api_duration_ms": None,
        **{field: None for field in TOKEN_FIELDS},
        "model_usage_json": "[]",
        "estimated_cost_usd": None,
    }


def _aggregate_model_usage(accounting: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregate: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in accounting:
        for model in item.get("model_usage") or []:
            if not isinstance(model, dict):
                continue
            key = (
                bounded_text(model.get("model_id"), 200) or "unknown",
                bounded_text(model.get("canonical_model"), 200) or "",
                bounded_text(model.get("provider"), 100) or "",
            )
            current = aggregate.setdefault(
                key,
                {
                    "model_id": key[0],
                    "canonical_model": key[1],
                    "provider": key[2],
                    "usage": {field: 0 for field in TOKEN_FIELDS},
                    "estimated_cost_usd": Decimal("0"),
                },
            )
            usage = TokenUsage.from_payload(model.get("usage"))
            for field, value in usage.as_dict().items():
                if value is not None:
                    current["usage"][field] += value
            current["estimated_cost_usd"] += _decimal(model.get("estimated_cost_usd")) or Decimal(
                "0"
            )
    result = []
    for key in sorted(aggregate):
        item = aggregate[key]
        item["estimated_cost_usd"] = _decimal_text(item["estimated_cost_usd"])
        result.append(item)
    return result


def _classify_failure(
    events: list[dict[str, Any]],
) -> tuple[ExecutionFailureStage | None, str | None, str | None]:
    for event in reversed(events):
        payload = _dict_payload(event.get("payload"))
        if event["event_type"] == "tool_event" and payload.get("status") in {"DENIED", "FAILED"}:
            stage = (
                ExecutionFailureStage.TOOL_PERMISSION
                if payload.get("status") == "DENIED"
                else ExecutionFailureStage.TOOL_EXECUTION
            )
            return (
                stage,
                bounded_text(payload.get("error_code"), 128),
                bounded_text(payload.get("response_summary"), 2048),
            )
        if event["event_type"] == "model_call" and payload.get("status") == "FAILED":
            return (
                ExecutionFailureStage.MODEL_API,
                bounded_text(payload.get("error_code"), 128),
                bounded_text(payload.get("error_summary"), 2048),
            )
        if event["event_type"] == "runtime_initialized" and any(
            isinstance(server, dict) and server.get("status") == "FAILED"
            for server in payload.get("mcp_servers") or []
        ):
            return ExecutionFailureStage.MCP_CONNECTION, "runtime_mcp_connection_failed", None
        if event["event_type"] == "terminal" and payload.get("status") != "SUCCEEDED":
            failure = _dict_payload(payload.get("failure"))
            code = bounded_text(failure.get("code"), 128)
            summary = bounded_text(failure.get("safe_message"), 2048)
            if code and (
                code.startswith("runtime_protocol")
                or code in {"runtime_event_invalid", "runtime_terminal_missing"}
            ):
                return ExecutionFailureStage.RUNTIME_PROTOCOL, code, summary
            if code in {
                "runtime_transport_error",
                "runtime_kind_mismatch",
                "runtime_model_binding_missing",
                "runtime_publication_binding_missing",
                "agent_runtime_unconfigured",
                "agent_runtime_kind_unsupported",
            }:
                return ExecutionFailureStage.RUNTIME_START, code, summary
            if code and (code.startswith("runtime_mcp") or code.startswith("mcp_")):
                return ExecutionFailureStage.MCP_CONNECTION, code, summary
            if code and code.startswith("runtime_model"):
                return ExecutionFailureStage.MODEL_API, code, summary
            return ExecutionFailureStage.UNKNOWN, code, summary
    return None, None, None


def _execution_status(value: str) -> ExecutionStatus:
    if value == "SUCCEEDED":
        return ExecutionStatus.SUCCEEDED
    if value in {"FAILED", "TIMEOUT"}:
        return ExecutionStatus.FAILED
    if value == "CANCELLED":
        return ExecutionStatus.CANCELLED
    return ExecutionStatus.UNKNOWN


def _optional_nonnegative(value: object) -> int | None:
    try:
        candidate = (
            int(cast(Any, value)) if value is not None and not isinstance(value, bool) else -1
        )
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if 0 <= candidate <= 9_223_372_036_854_775_807 else None


def _dict_payload(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _model_call_signature(payload: dict[str, Any]) -> tuple[object, ...]:
    usage = TokenUsage.from_payload(payload.get("usage"))
    return (
        bounded_text(payload.get("model_call_id"), 128),
        bounded_text(payload.get("provider_request_id"), 200),
        bounded_text(payload.get("provider_message_id"), 200),
        bounded_text(payload.get("model_id"), 200),
        str(payload.get("status") or "FAILED"),
        *(getattr(usage, field) for field in TOKEN_FIELDS),
        bounded_text(payload.get("stop_reason"), 128),
        bounded_text(payload.get("error_code"), 128),
        bounded_text(payload.get("error_summary"), 2048),
    )


def _sum_optional(items: list[dict[str, Any]], field: str) -> int | None:
    return _sum_values([item.get(field) for item in items])


def _sum_values(values: list[object]) -> int | None:
    parsed = [_optional_nonnegative(value) for value in values]
    known = [value for value in parsed if value is not None]
    return sum(known) if known else None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        candidate = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return candidate if candidate.is_finite() and candidate >= 0 else None


def _sum_decimal(items: list[dict[str, Any]], field: str) -> str | None:
    values = [_decimal(item.get(field)) for item in items]
    known = [value for value in values if value is not None]
    return _decimal_text(sum(known, Decimal("0"))) if known else None


def _decimal_text(value: object) -> str | None:
    candidate = _decimal(value)
    return (
        f"{candidate.quantize(Decimal('0.000000000001')):.12f}" if candidate is not None else None
    )


def _json_list(value: object) -> list[dict[str, Any]]:
    try:
        parsed = value if isinstance(value, list) else json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _model_call(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    for field in ("runtime_sequence", "duration_ms", *TOKEN_FIELDS):
        item[field] = int(item[field]) if item.get(field) is not None else None
    return item


def _unavailable_summary(job_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "accounting_status": "UNAVAILABLE",
        "observed_model_turn_count": 0,
        "api_retry_count": 0,
        "runtime_invocation_count": 0,
        "total_duration_ms": None,
        "total_api_duration_ms": None,
        **{field: None for field in TOKEN_FIELDS},
        "model_usage": [],
        "estimated_cost_usd": None,
        "execution_status": "UNKNOWN",
        "execution_failure_stage": None,
        "failure_code": None,
        "failure_summary": None,
        "retry_exhausted": False,
        "source_protocol_version": "1.5",
        "created_at": None,
        "updated_at": None,
    }


def _comparable(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value
