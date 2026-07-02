from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.domain.channel_event import ReplyRoute, RoutingContext
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import QueueSettings
from app.shared.logging import new_correlation_id


@dataclass(frozen=True)
class CreateAgentJobCommand:
    idempotency_key: str
    user_message: str
    requester_id: str = ""
    external_conversation_id: str = ""
    project_code: str = "default"
    source_channel: str = "dingding"
    source_connector_id: str = "connector-dingtalk-enterprise-default"
    external_event_id: str = ""
    requester_display_name: str = ""
    routing_context: dict[str, Any] = field(default_factory=dict)
    reply_route: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    dingding_conversation_id: str | None = None
    dingding_user_id: str | None = None
    source: str | None = None

    @property
    def effective_requester_id(self) -> str:
        return self.requester_id or self.dingding_user_id or "unknown-user"

    @property
    def effective_conversation_id(self) -> str:
        return self.external_conversation_id or self.dingding_conversation_id or ""

    @property
    def effective_source_channel(self) -> str:
        return self.source_channel or self.source or "dingding"

    @property
    def effective_routing_context(self) -> dict[str, Any]:
        if self.routing_context:
            return self.routing_context
        return RoutingContext(project_code=self.project_code).to_dict()

    @property
    def effective_reply_route(self) -> dict[str, Any]:
        if self.reply_route:
            return self.reply_route
        if self.effective_source_channel == "debug_api":
            return ReplyRoute(type="none").to_dict()
        return ReplyRoute(
            type="dingtalk_conversation",
            connector_id=self.source_connector_id,
            target={"conversation_id": self.effective_conversation_id},
        ).to_dict()


class CreateAgentJobService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        permission_service: PermissionService,
        audit_service: AuditService,
        publisher: MessagePublisher,
        queue_settings: QueueSettings,
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.audit_service = audit_service
        self.publisher = publisher
        self.queue_settings = queue_settings
        self.connector_registry = connector_registry

    def execute(self, command: CreateAgentJobCommand) -> AgentJob:
        existing = self.repository.get_job_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            return existing
        requester_id = command.effective_requester_id
        source_channel = command.effective_source_channel
        project_code = command.effective_routing_context.get("project_code", command.project_code)
        project_code = str(project_code or command.project_code)
        reply_route = command.effective_reply_route
        self._assert_connectors_allowed(command, reply_route)
        self.audit_service.record(
            "permission.job_create.start",
            status="STARTED",
            summary="Checking user permission for Agent job creation",
            actor_id=requester_id,
            payload={
                "project_code": project_code,
                "source_channel": source_channel,
                "source_connector_id": command.source_connector_id,
                "delivery_type": reply_route.get("type"),
                "delivery_connector_id": reply_route.get("connector_id"),
            },
        )
        self.permission_service.assert_user_can_create_job(
            user_id=requester_id,
            project_code=project_code,
        )
        session = self.repository.create_session(
            dingding_conversation_id=command.effective_conversation_id,
            dingding_user_id=requester_id,
            source=source_channel,
            project_code=project_code,
            source_channel=source_channel,
            source_connector_id=command.source_connector_id,
            external_conversation_id=command.effective_conversation_id,
            requester_id=requester_id,
            requester_display_name=command.requester_display_name,
            routing_context=command.effective_routing_context,
            reply_route=reply_route,
        )
        job = self.repository.create_job(
            session_id=session.id,
            idempotency_key=command.idempotency_key,
            user_id=requester_id,
            project_code=project_code,
            source=source_channel,
            user_message=command.user_message,
            max_retry_count=self.queue_settings.max_retry_count,
            source_channel=source_channel,
            source_connector_id=command.source_connector_id,
            external_event_id=command.external_event_id,
            requester_id=requester_id,
            routing_context=command.effective_routing_context,
            reply_route=reply_route,
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
            actor_id=requester_id,
            payload={
                "idempotency_key": command.idempotency_key,
                "source_channel": source_channel,
                "source_connector_id": command.source_connector_id,
                "external_event_id": command.external_event_id,
            },
        )
        self.publisher.publish_agent_job(job.id, command.correlation_id or new_correlation_id())
        self.audit_service.record(
            "queue.dispatched",
            status="SUCCEEDED",
            summary="Agent job dispatched to message bus",
            job_id=job.id,
            actor_id=requester_id,
        )
        return job

    def _assert_connectors_allowed(
        self, command: CreateAgentJobCommand, reply_route: dict[str, Any]
    ) -> None:
        if self.connector_registry is None:
            return
        source_connector_id = command.source_connector_id
        if source_connector_id:
            self.connector_registry.require_ingress(source_connector_id)
            self.audit_service.record(
                "permission.connector_ingress",
                status="SUCCEEDED",
                summary="Connector ingress allowed",
                actor_id=command.effective_requester_id,
                payload={"connector_id": source_connector_id},
            )
        route = ReplyRoute.from_dict(reply_route)
        if route.type != "none" and route.connector_id:
            self.connector_registry.require_delivery(route.connector_id)
            self.audit_service.record(
                "permission.connector_delivery",
                status="SUCCEEDED",
                summary="Connector delivery allowed",
                actor_id=command.effective_requester_id,
                payload={"connector_id": route.connector_id, "route_type": route.type},
            )
