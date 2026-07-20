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
    session_key: str = ""
    conversation_type: str = "direct"
    bot_identity: str = ""
    summary_text: str = ""
    summary_through_sequence: int = 0
    summary_version: int = 0
    external_identity_id: str = ""


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
    last_error_code: str = ""
    last_error_at: str | None = None
    next_retry_at: str | None = None
    source_channel: str = "dingding"
    source_connector_id: str = "connector-dingtalk-enterprise-default"
    external_event_id: str = ""
    requester_id: str = ""
    routing_context: dict[str, Any] | None = None
    reply_route: dict[str, Any] | None = None
    internal_user_id: str = ""
    external_identity_id: str = ""
    agent_definition_id: str = ""
    agent_publication_id: str = ""
    agent_revision: int | None = None
    agent_config_hash: str = ""
    webhook_event_id: str = ""
    webhook_trigger_id: str = ""
    webhook_trigger_publication_id: str = ""


@dataclass(frozen=True)
class MessageAttachment:
    id: str
    message_id: str
    job_id: str
    ordinal: int
    media_type: str
    file_name: str
    declared_mime: str
    status: str
    detected_mime: str = ""
    declared_size: int | None = None
    size_bytes: int | None = None
    sha256: str = ""
    object_bucket: str = ""
    object_key: str = ""
    failure_code: str = ""
