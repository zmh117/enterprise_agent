from __future__ import annotations

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.domain.channel_event import ChannelEvent
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    CreateAgentJobService,
)
from app.modules.job.domain.agent_job import AgentJob


class ChannelIngressService:
    def __init__(
        self,
        *,
        create_job_service: CreateAgentJobService,
        audit_service: AuditService,
    ) -> None:
        self.create_job_service = create_job_service
        self.audit_service = audit_service

    def accept(self, event: ChannelEvent) -> AgentJob:
        self.audit_service.record(
            "channel.received",
            status="SUCCEEDED",
            summary="Channel event received",
            actor_id=event.source.actor_id,
            payload={
                "source_type": event.source.type,
                "source_connector_id": event.source.connector_id,
                "external_event_id": event.source.event_id,
                "delivery_type": event.delivery.type,
                "delivery_connector_id": event.delivery.connector_id,
            },
        )
        self.audit_service.record(
            "channel.normalized",
            status="SUCCEEDED",
            summary="Channel event normalized",
            actor_id=event.source.actor_id,
            payload=event.raw_payload_summary,
        )
        return self.create_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key=event.effective_idempotency_key,
                requester_id=event.source.actor_id,
                requester_display_name=str(event.source.metadata.get("display_name") or ""),
                external_conversation_id=event.source.conversation_id,
                user_message=event.message,
                project_code=event.routing.project_code,
                source_channel=event.source.type,
                source_connector_id=event.source.connector_id,
                external_event_id=event.source.event_id,
                routing_context=event.routing.to_dict(),
                reply_route=event.delivery.to_dict(),
                correlation_id=event.correlation_id,
            )
        )
