from __future__ import annotations

from dataclasses import dataclass

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import QueueSettings
from app.shared.logging import new_correlation_id


@dataclass(frozen=True)
class CreateAgentJobCommand:
    idempotency_key: str
    dingding_conversation_id: str
    dingding_user_id: str
    user_message: str
    project_code: str = "default"
    source: str = "dingding"
    correlation_id: str | None = None


class CreateAgentJobService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        permission_service: PermissionService,
        audit_service: AuditService,
        publisher: MessagePublisher,
        queue_settings: QueueSettings,
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.audit_service = audit_service
        self.publisher = publisher
        self.queue_settings = queue_settings

    def execute(self, command: CreateAgentJobCommand) -> AgentJob:
        existing = self.repository.get_job_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            return existing
        self.audit_service.record(
            "permission.job_create.start",
            status="STARTED",
            summary="Checking user permission for Agent job creation",
            actor_id=command.dingding_user_id,
            payload={"project_code": command.project_code},
        )
        self.permission_service.assert_user_can_create_job(
            user_id=command.dingding_user_id,
            project_code=command.project_code,
        )
        session = self.repository.create_session(
            dingding_conversation_id=command.dingding_conversation_id,
            dingding_user_id=command.dingding_user_id,
            source=command.source,
            project_code=command.project_code,
        )
        job = self.repository.create_job(
            session_id=session.id,
            idempotency_key=command.idempotency_key,
            user_id=command.dingding_user_id,
            project_code=command.project_code,
            source=command.source,
            user_message=command.user_message,
            max_retry_count=self.queue_settings.max_retry_count,
        )
        self.repository.add_message(
            session_id=session.id,
            job_id=job.id,
            role="user",
            content=command.user_message,
        )
        self.audit_service.record(
            "job.created",
            status="SUCCEEDED",
            summary="Agent job created",
            job_id=job.id,
            actor_id=command.dingding_user_id,
            payload={"idempotency_key": command.idempotency_key},
        )
        self.publisher.publish_agent_job(job.id, command.correlation_id or new_correlation_id())
        self.audit_service.record(
            "queue.dispatched",
            status="SUCCEEDED",
            summary="Agent job dispatched to message bus",
            job_id=job.id,
            actor_id=command.dingding_user_id,
        )
        return job
