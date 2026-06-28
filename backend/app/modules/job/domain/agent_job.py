from __future__ import annotations

from dataclasses import dataclass

from app.modules.job.domain.job_status import JobStatus


@dataclass(frozen=True)
class AgentSession:
    id: str
    dingding_conversation_id: str
    dingding_user_id: str
    source: str
    project_code: str


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
