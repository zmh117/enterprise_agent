from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.job.domain.job_status import JobStatus


@dataclass(frozen=True)
class AgentSession:
    id: str
    project_code: str
    source_channel: str
    source_connector_id: str
    external_conversation_id: str
    requester_id: str
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
    business_application_id: str = ""
    business_application_code: str = ""
    application_publication_id: str = ""
    execution_scope_hash: str = ""
    isolation_key_version: int = 1
    history_read_only: bool = False
    conversation_mode: str = "legacy"
    recent_message_limit: int | None = None
    session_policy: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentJob:
    id: str
    session_id: str
    idempotency_key: str
    project_code: str
    source_channel: str
    source_connector_id: str
    requester_id: str
    input_message_id: str
    input_message: str | None
    input_message_state: str
    status: JobStatus
    retry_count: int
    max_retry_count: int
    result: str | None = None
    error_message: str | None = None
    last_error_code: str = ""
    last_error_at: str | None = None
    next_retry_at: str | None = None
    external_event_id: str = ""
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
    business_application_id: str = ""
    business_application_code: str = ""
    business_application_publication_id: str = ""
    business_application_deployment_id: str = ""
    business_application_route_id: str = ""
    business_application_config_hash: str = ""
    business_application_runtime_status: str = ""
    business_application_route_decision: dict[str, Any] | None = None
    execution_policy: dict[str, Any] | None = None
    execution_policy_tool_call_count: int = 0
    execution_policy_exhausted: bool = False
    model_runtime_provenance: dict[str, Any] | None = None
    agent_runtime_kind: str = "python-v1"
    agent_runtime_protocol_version: str = "1.3"
    task_workspace_id: str = ""


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
    task_workspace_id: str = ""
    claimed_at: str | None = None
    detected_mime: str = ""
    declared_size: int | None = None
    size_bytes: int | None = None
    sha256: str = ""
    object_bucket: str = ""
    object_key: str = ""
    failure_code: str = ""
    readability_status: str = "NOT_REQUIRED"
    file_processing_run_id: str = ""
    readability_error_code: str = ""
    readability_updated_at: str | None = None
