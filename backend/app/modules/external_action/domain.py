from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError


class ExternalActionStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    FAILED_UNCERTAIN = "FAILED_UNCERTAIN"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class ExternalActionIntentFacts:
    job_id: str
    session_id: str
    actor_user_id: str
    business_application_id: str
    agent_publication_id: str
    application_publication_id: str
    source_connector_id: str
    dingtalk_enterprise_id: str
    target_external_subject_id: str
    target_union_id: str
    server_code: str
    tool_identifier: str
    schema_hash: str
    confirmation_policy: str
    operation_code: str
    confirmation_channel_code: str = "dingtalk"
    execution_provider_code: str = "dingtalk"
    execution_external_identity_id: str = ""
    execution_scope_id: str = ""
    target_resource_type: str = ""
    target_resource_id: str = ""
    precondition: dict[str, Any] | None = None
    field_catalog_version: str = ""
    field_catalog_hash: str = ""
    supersedes_intent_id: str = ""

    def as_repository_facts(self, *, arguments_hash: str) -> dict[str, Any]:
        precondition = dict(self.precondition or {})
        precondition_hash = json_hash(precondition) if precondition else ""
        intent_fingerprint = ""
        if self.execution_provider_code == "ones":
            if (
                not self.execution_external_identity_id
                or not self.execution_scope_id
                or self.target_resource_type != "task"
                or not self.target_resource_id
                or not precondition_hash
                or not self.field_catalog_version
                or len(self.field_catalog_hash) != 64
            ):
                raise _invalid("ONES 外部操作缺少受治理资源快照")
            intent_fingerprint = json_hash(
                {
                    "job_id": self.job_id,
                    "tool_identifier": self.tool_identifier,
                    "arguments_hash": arguments_hash,
                    "execution_external_identity_id": self.execution_external_identity_id,
                    "execution_scope_id": self.execution_scope_id,
                    "target_resource_type": self.target_resource_type,
                    "target_resource_id": self.target_resource_id,
                    "precondition_hash": precondition_hash,
                    "field_catalog_hash": self.field_catalog_hash,
                }
            )
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "actor_user_id": self.actor_user_id,
            "business_application_id": self.business_application_id,
            "agent_publication_id": self.agent_publication_id,
            "application_publication_id": self.application_publication_id,
            "source_connector_id": self.source_connector_id,
            "dingtalk_enterprise_id": self.dingtalk_enterprise_id,
            "target_external_subject_id": self.target_external_subject_id,
            "target_union_id": self.target_union_id,
            "server_code": self.server_code,
            "tool_identifier": self.tool_identifier,
            "schema_hash": self.schema_hash,
            "confirmation_policy": self.confirmation_policy,
            "operation_code": self.operation_code,
            "confirmation_channel_code": self.confirmation_channel_code,
            "execution_provider_code": self.execution_provider_code,
            "execution_external_identity_id": self.execution_external_identity_id,
            "execution_scope_id": self.execution_scope_id,
            "target_resource_type": self.target_resource_type,
            "target_resource_id": self.target_resource_id,
            "precondition": precondition,
            "precondition_hash": precondition_hash,
            "field_catalog_version": self.field_catalog_version,
            "field_catalog_hash": self.field_catalog_hash,
            "intent_fingerprint": intent_fingerprint,
            "supersedes_intent_id": self.supersedes_intent_id,
        }


@dataclass(frozen=True, slots=True)
class NormalizedTodoArguments:
    subject: str
    description: str
    due_time: str
    due_time_ms: int | None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "subject": self.subject,
            "description": self.description,
            "due_time": self.due_time,
        }
        if self.due_time_ms is not None:
            value["due_time_ms"] = self.due_time_ms
        return value


def normalize_todo_arguments(arguments: dict[str, Any]) -> NormalizedTodoArguments:
    allowed = {"subject", "description", "due_time"}
    if set(arguments) - allowed:
        raise _invalid("钉钉待办参数包含未允许字段")
    subject = _bounded_text(arguments.get("subject"), minimum=1, maximum=200, field="subject")
    description = _bounded_text(
        arguments.get("description", ""), minimum=0, maximum=2000, field="description"
    )
    due_time = _bounded_text(arguments.get("due_time", ""), minimum=0, maximum=64, field="due_time")
    due_time_ms: int | None = None
    if due_time:
        try:
            parsed = datetime.fromisoformat(due_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid("截止时间必须是带时区的 ISO-8601 时间") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise _invalid("截止时间必须包含时区")
        due_time_ms = int(parsed.astimezone(UTC).timestamp() * 1000)
        due_time = parsed.isoformat()
    return NormalizedTodoArguments(
        subject=subject,
        description=description,
        due_time=due_time,
        due_time_ms=due_time_ms,
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bounded_text(value: Any, *, minimum: int, maximum: int, field: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} 必须是字符串")
    normalized = " ".join(value.strip().split()) if field == "subject" else value.strip()
    if not minimum <= len(normalized) <= maximum:
        raise _invalid(f"{field} 长度无效")
    return normalized


def _invalid(message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        message,
        safe_message=message,
        error_code="external_action_arguments_invalid",
    )
