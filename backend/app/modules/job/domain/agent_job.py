from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.job.domain.job_status import JobStatus


@dataclass(frozen=True)
class AgentSession:
    id: str
    dingding_conversation_id: str
    dingding_user_id: str
    source: str
    project_code: str
    source_channel: str = "dingding"
    source_connector_id: str = "connector-dingtalk-enterprise-default"
    external_conversation_id: str = ""
    requester_id: str = ""
    requester_display_name: str = ""
    routing_context: dict[str, Any] | None = None
    reply_route: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentJob:
    id: str
    session_id: str
    idempotency_key: str
    user_id: str
    project_code: str
    source: str
    user_message: str
    status: JobStatus
    retry_count: int
    max_retry_count: int
    result: str | None = None
    error_message: str | None = None
    source_channel: str = "dingding"
    source_connector_id: str = "connector-dingtalk-enterprise-default"
    external_event_id: str = ""
    requester_id: str = ""
    routing_context: dict[str, Any] | None = None
    reply_route: dict[str, Any] | None = None
