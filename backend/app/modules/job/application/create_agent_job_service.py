from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib
from pathlib import Path

from app.modules.agent_config.application import AgentConfigService
from app.modules.audit.application.audit_service import AuditService
from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.channel.domain.channel_event import ChannelAttachment, ReplyRoute, RoutingContext
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import AttachmentSettings, QueueSettings
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.logging import new_correlation_id

DEFAULT_DINGTALK_SOURCE_CONNECTOR_ID = "connector-dingtalk-stream-default"
DEFAULT_DINGTALK_DELIVERY_CONNECTOR_ID = "connector-dingtalk-enterprise-default"


@dataclass(frozen=True)
class CreateAgentJobCommand:
    idempotency_key: str
    user_message: str
    requester_id: str = ""
    external_conversation_id: str = ""
    project_code: str = "default"
    source_channel: str = "dingding"
    source_connector_id: str = DEFAULT_DINGTALK_SOURCE_CONNECTOR_ID
    external_event_id: str = ""
    requester_display_name: str = ""
    routing_context: dict[str, Any] = field(default_factory=dict)
    reply_route: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    dingding_conversation_id: str | None = None
    dingding_user_id: str | None = None
    source: str | None = None
    external_message_id: str = ""
    conversation_type: str = "direct"
    bot_identity: str = ""
    attachments: tuple[ChannelAttachment, ...] = ()
    external_identity_id: str = ""
    agent_code: str = ""
    fixed_agent_publication_id: str = ""
    fixed_agent_revision: int | None = None
    fixed_agent_config_hash: str = ""
    webhook_event_id: str = ""
    webhook_trigger_id: str = ""
    webhook_trigger_publication_id: str = ""
    continuous_conversation_enabled: bool | None = None
    attachments_enabled: bool | None = None

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
        delivery_connector_id = self.source_connector_id
        if self.source_connector_id == DEFAULT_DINGTALK_SOURCE_CONNECTOR_ID:
            delivery_connector_id = DEFAULT_DINGTALK_DELIVERY_CONNECTOR_ID
        return ReplyRoute(
            type="dingtalk_conversation",
            connector_id=delivery_connector_id,
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
        credential_cipher: AttachmentCredentialCipher | None = None,
        continuous_enabled: bool = False,
        attachment_settings: AttachmentSettings | None = None,
        agent_config_service: AgentConfigService | None = None,
        published_agent_runtime_enabled: bool = False,
        default_agent_code: str = "default-diagnostic-agent",
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.audit_service = audit_service
        self.publisher = publisher
        self.queue_settings = queue_settings
        self.connector_registry = connector_registry
        self.credential_cipher = credential_cipher
        self.continuous_enabled = continuous_enabled
        self.attachment_settings = attachment_settings or AttachmentSettings()
        self.agent_config_service = agent_config_service
        self.published_agent_runtime_enabled = published_agent_runtime_enabled
        self.default_agent_code = default_agent_code

    def execute(self, command: CreateAgentJobCommand) -> AgentJob:
        existing = self.repository.get_job_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            return existing
        attachments_enabled = (
            self.attachment_settings.enabled
            if command.attachments_enabled is None
            else command.attachments_enabled
        )
        self._validate_attachments(
            command.attachments,
            enabled=attachments_enabled,
        )
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
        agent_definition_id = ""
        agent_publication_id = ""
        agent_revision = 0
        agent_config_hash = ""
        if self.published_agent_runtime_enabled or command.fixed_agent_publication_id:
            if self.agent_config_service is None:
                raise NonRetryableExecutionError(
                    "Published Agent runtime service is unavailable",
                    safe_message="Agent configuration is unavailable",
                )
            agent_code = command.agent_code or self.default_agent_code
            self.permission_service.require_action(
                user_id=requester_id,
                resource_type="agent",
                resource_code=agent_code,
                action="use",
            )
            definition = self.agent_config_service.repository.get_definition(agent_code)
            publication = (
                self.agent_config_service.publication(command.fixed_agent_publication_id)
                if command.fixed_agent_publication_id
                else self.agent_config_service.current_publication(agent_code)
            )
            if str(publication["agent_id"]) != str(definition["id"]):
                raise NonRetryableExecutionError(
                    "Pinned Agent publication belongs to another Agent",
                    safe_message="Pinned Agent configuration is invalid",
                )
            if command.fixed_agent_revision is not None and int(
                publication["revision"]
            ) != int(command.fixed_agent_revision):
                raise NonRetryableExecutionError(
                    "Pinned Agent revision mismatch",
                    safe_message="Pinned Agent configuration integrity check failed",
                )
            if command.fixed_agent_config_hash and str(
                publication["config_hash"]
            ) != command.fixed_agent_config_hash:
                raise NonRetryableExecutionError(
                    "Pinned Agent hash mismatch",
                    safe_message="Pinned Agent configuration integrity check failed",
                )
            agent_definition_id = str(definition["id"])
            agent_publication_id = str(publication["id"])
            agent_revision = int(publication["revision"])
            agent_config_hash = str(publication["config_hash"])
            if command.source_connector_id and not self.agent_config_service.connector_allowed(
                publication_id=agent_publication_id,
                direction="ingress",
                connector_id=command.source_connector_id,
            ):
                raise NonRetryableExecutionError(
                    "Source connector is not assigned to the Agent publication",
                    safe_message="Agent is not available on this channel",
                )
            delivery_connector_id = str(reply_route.get("connector_id") or "")
            if (
                reply_route.get("type") != "none"
                and delivery_connector_id
                and not self.agent_config_service.connector_allowed(
                    publication_id=agent_publication_id,
                    direction="delivery",
                    connector_id=delivery_connector_id,
                )
            ):
                raise NonRetryableExecutionError(
                    "Delivery connector is not assigned to the Agent publication",
                    safe_message="Agent result delivery is not configured for this channel",
                )
        if command.attachments and self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "Attachment credential encryption is unavailable",
                safe_message="Attachment processing is not configured",
            )
        continuous_enabled = (
            self.continuous_enabled
            if command.continuous_conversation_enabled is None
            else command.continuous_conversation_enabled
        )
        session_key = _session_key(
            source_channel=source_channel,
            connector_id=command.source_connector_id,
            project_code=project_code,
            conversation_type=command.conversation_type,
            conversation_id=command.effective_conversation_id,
            requester_id=requester_id,
            bot_identity=command.bot_identity,
        ) if continuous_enabled else ""
        correlation_id = command.correlation_id or new_correlation_id()
        attachment_ids: list[str] = []
        with self.repository.database.transaction():
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
                session_key=session_key,
                conversation_type=command.conversation_type,
                bot_identity=command.bot_identity,
                external_identity_id=command.external_identity_id,
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
                initial_status=(
                    JobStatus.WAITING_INPUT if command.attachments else JobStatus.PENDING
                ),
                internal_user_id=requester_id,
                external_identity_id=command.external_identity_id,
                agent_definition_id=agent_definition_id,
                agent_publication_id=agent_publication_id,
                agent_revision=agent_revision,
                agent_config_hash=agent_config_hash,
                webhook_event_id=command.webhook_event_id,
                webhook_trigger_id=command.webhook_trigger_id,
                webhook_trigger_publication_id=command.webhook_trigger_publication_id,
            )
            message_id = self.repository.add_message(
                session_id=session.id,
                job_id=job.id,
                role="user",
                content=command.user_message,
                external_message_id=command.external_message_id or command.external_event_id,
                sender_id=requester_id,
                sender_display_name=command.requester_display_name,
                message_type="multimodal" if command.attachments else "text",
                content_status="PENDING" if command.attachments else "READY",
            )
            for ordinal, attachment in enumerate(command.attachments, start=1):
                assert self.credential_cipher is not None
                created = self.repository.add_attachment(
                    message_id=message_id,
                    job_id=job.id,
                    ordinal=ordinal,
                    media_type=attachment.media_type,
                    file_name=attachment.file_name,
                    declared_mime=attachment.declared_mime,
                    declared_size=attachment.declared_size,
                    credential_ciphertext=self.credential_cipher.encrypt(
                        attachment.source_credential
                    ),
                    credential_type=attachment.source_credential_type,
                    credential_expires_at=attachment.source_credential_expires_at,
                )
                attachment_ids.append(created.id)
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
                    "agent_publication_id": agent_publication_id,
                    "agent_revision": agent_revision,
                    "agent_config_hash": agent_config_hash,
                    "webhook_event_id": command.webhook_event_id,
                    "webhook_trigger_id": command.webhook_trigger_id,
                    "webhook_trigger_publication_id": command.webhook_trigger_publication_id,
                },
            )
        for attachment_id in attachment_ids:
            self.publisher.publish_attachment(attachment_id, correlation_id)
        if not command.attachments:
            self.publisher.publish_agent_job(job.id, correlation_id)
            self.audit_service.record(
                "queue.dispatched",
                status="SUCCEEDED",
                summary="Agent job dispatched to message bus",
                job_id=job.id,
                actor_id=requester_id,
            )
        return job

    def _validate_attachments(
        self,
        attachments: tuple[ChannelAttachment, ...],
        *,
        enabled: bool,
    ) -> None:
        if attachments and not enabled:
            raise NonRetryableExecutionError(
                "message_attachments_disabled",
                safe_message="Attachments are not enabled for this application",
            )
        if len(attachments) > self.attachment_settings.max_count:
            raise NonRetryableExecutionError(
                "attachment_count_exceeded", safe_message="Too many attachments"
            )
        total = 0
        for attachment in attachments:
            extension = Path(attachment.file_name).suffix.lower()
            if extension not in self.attachment_settings.allowed_extensions:
                raise NonRetryableExecutionError(
                    "unsupported_attachment_type", safe_message="Unsupported attachment type"
                )
            if not attachment.source_credential:
                raise NonRetryableExecutionError(
                    "attachment_source_missing", safe_message="Attachment source is missing"
                )
            size = int(attachment.declared_size or 0)
            if size > self.attachment_settings.max_file_bytes:
                raise NonRetryableExecutionError(
                    "attachment_size_exceeded", safe_message="Attachment is too large"
                )
            total += size
        if total > self.attachment_settings.max_message_bytes:
            raise NonRetryableExecutionError(
                "attachment_message_size_exceeded",
                safe_message="Attachment message is too large",
            )

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


def _session_key(
    *,
    source_channel: str,
    connector_id: str,
    project_code: str,
    conversation_type: str,
    conversation_id: str,
    requester_id: str,
    bot_identity: str,
) -> str:
    if conversation_type == "group":
        identity = conversation_id
    else:
        identity = f"{requester_id}:{bot_identity or connector_id}"
    canonical = "|".join(
        [source_channel, connector_id, project_code, conversation_type, identity]
    )
    return "session-key:" + hashlib.sha256(canonical.encode()).hexdigest()
