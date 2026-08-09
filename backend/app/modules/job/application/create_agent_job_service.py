from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from app.modules.agent_config.application import AgentConfigService
from app.modules.authorization_center.application import BusinessAuthorizationService
from app.modules.audit.application.audit_service import AuditService
from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.channel.domain.channel_event import ChannelAttachment, ReplyRoute, RoutingContext
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.job.domain.agent_job import AgentJob, AgentSession
from app.modules.job.domain.execution_policy import EffectiveExecutionPolicyResolver
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.identity.infrastructure.repository import IdentityRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.modules.mcp_runtime.bindings import McpJobBindingService
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import AttachmentSettings, ExecutionSettings, QueueSettings
from app.shared.exceptions import NonRetryableExecutionError, NotFound, PermissionDenied
from app.shared.logging import new_correlation_id

DEFAULT_DINGTALK_SOURCE_CONNECTOR_ID = "connector-dingtalk-stream-default"
DEFAULT_DINGTALK_DELIVERY_CONNECTOR_ID = "connector-dingtalk-enterprise-default"
ISOLATED_SESSION_SOURCE_CHANNELS = {
    "debug_api",
    "grafana_alert",
    "managed_webhook",
    "webhook",
}


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
    business_application_id: str = ""
    business_application_code: str = ""
    business_application_publication_id: str = ""
    business_application_deployment_id: str = ""
    business_application_route_id: str = ""
    business_application_config_hash: str = ""
    business_application_runtime_status: str = ""
    business_application_route_decision: dict[str, Any] = field(default_factory=dict)
    conversation_mode: str = "legacy"
    recent_message_limit: int | None = None
    session_policy: dict[str, Any] = field(default_factory=dict)
    application_execution_policy: dict[str, Any] = field(default_factory=dict)
    continue_session_id: str = ""

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
        execution_settings: ExecutionSettings,
        connector_registry: ConnectorRegistry | None = None,
        credential_cipher: AttachmentCredentialCipher | None = None,
        continuous_enabled: bool = False,
        attachment_settings: AttachmentSettings | None = None,
        agent_config_service: AgentConfigService | None = None,
        published_agent_runtime_enabled: bool = False,
        default_agent_code: str = "default-diagnostic-agent",
        business_authorization_service: BusinessAuthorizationService | None = None,
        mcp_binding_service: McpJobBindingService | None = None,
        identity_repository: IdentityRepository | None = None,
        accept_new_jobs: bool = True,
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.audit_service = audit_service
        self.publisher = publisher
        self.queue_settings = queue_settings
        self.execution_policy_resolver = EffectiveExecutionPolicyResolver(execution_settings)
        self.connector_registry = connector_registry
        self.credential_cipher = credential_cipher
        self.continuous_enabled = continuous_enabled
        self.attachment_settings = attachment_settings or AttachmentSettings()
        self.agent_config_service = agent_config_service
        self.published_agent_runtime_enabled = published_agent_runtime_enabled
        self.default_agent_code = default_agent_code
        self.business_authorization_service = business_authorization_service
        self.mcp_binding_service = mcp_binding_service
        self.identity_repository = identity_repository
        self.accept_new_jobs = accept_new_jobs

    def execute(self, command: CreateAgentJobCommand) -> AgentJob:
        existing = self.repository.get_job_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            if self.mcp_binding_service is not None:
                self.mcp_binding_service.freeze(existing)
            return existing
        if not self.accept_new_jobs:
            raise NonRetryableExecutionError(
                "New Agent Jobs are disabled during destructive maintenance",
                safe_message="系统处于维护窗口，暂不接收新的 Agent Job",
                error_code="job_ingress_maintenance",
            )
        if command.conversation_mode in {"application", "actor"}:
            raise NonRetryableExecutionError(
                "Legacy shared session mode cannot create new Jobs",
                safe_message="旧共享会话模式已停用，请将应用重新发布为按渠道会话",
                error_code="session_mode_unsupported",
            )
        attachments_enabled = (
            self.attachment_settings.enabled
            if command.attachments_enabled is None
            else command.attachments_enabled
        )
        self._validate_attachments(
            command.attachments,
            enabled=attachments_enabled,
        )
        requester_id = self._resolve_app_user_id(command.effective_requester_id)
        source_channel = command.effective_source_channel
        project_code = command.effective_routing_context.get("project_code", command.project_code)
        project_code = str(project_code or command.project_code)
        reply_route = command.effective_reply_route
        self._assert_connectors_allowed(command, reply_route)
        business_application_authorized = False
        business_authorization_snapshot: dict[str, Any] = {}
        if command.business_application_id:
            if source_channel in {"dingding", "dingding_stream"}:
                business_application_authorized = True
                business_authorization_snapshot = {
                    "allowed": True,
                    "stage": "job_create",
                    "reason": "dingtalk_active_application_route",
                    "application_id": command.business_application_id,
                    "application_publication_id": (command.business_application_publication_id),
                    "source_connector_id": (command.source_connector_id),
                }
            elif self.business_authorization_service is None:
                raise NonRetryableExecutionError(
                    "Business authorization service is unavailable",
                    safe_message="业务应用授权服务暂时不可用",
                    error_code="business_authorization_unavailable",
                )
            else:
                business_decision = self.business_authorization_service.require(
                    user_id=requester_id,
                    application_id=command.business_application_id,
                    environment=str(command.effective_routing_context.get("environment") or ""),
                    base=str(command.effective_routing_context.get("base") or ""),
                    workshop=str(command.effective_routing_context.get("workshop") or ""),
                    stage="job_create",
                )
                business_application_authorized = True
                business_authorization_snapshot = dict(business_decision)
            self.audit_service.record(
                "authorization.business.job_create",
                status="SUCCEEDED",
                summary="Business authorization allowed Agent job creation",
                actor_id=requester_id,
                payload=business_authorization_snapshot,
            )
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
        if not business_application_authorized:
            self.permission_service.assert_user_can_create_job(
                user_id=requester_id,
                project_code=project_code,
            )
        agent_definition_id = ""
        agent_publication_id = ""
        agent_revision = 0
        agent_config_hash = ""
        agent_snapshot: dict[str, Any] = {}
        model_runtime_provenance: dict[str, Any] = {
            "legacy": True,
            "runtime": "claude_agent_sdk",
        }
        if self.published_agent_runtime_enabled or command.fixed_agent_publication_id:
            if self.agent_config_service is None:
                raise NonRetryableExecutionError(
                    "Published Agent runtime service is unavailable",
                    safe_message="Agent 配置不可用",
                )
            agent_code = command.agent_code or self.default_agent_code
            if not business_application_authorized:
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
                    safe_message="固定的 Agent 配置无效",
                )
            if command.fixed_agent_revision is not None and int(publication["revision"]) != int(
                command.fixed_agent_revision
            ):
                raise NonRetryableExecutionError(
                    "Pinned Agent revision mismatch",
                    safe_message="固定的 Agent 配置完整性校验失败",
                )
            if (
                command.fixed_agent_config_hash
                and str(publication["config_hash"]) != command.fixed_agent_config_hash
            ):
                raise NonRetryableExecutionError(
                    "Pinned Agent hash mismatch",
                    safe_message="固定的 Agent 配置完整性校验失败",
                )
            agent_definition_id = str(definition["id"])
            agent_publication_id = str(publication["id"])
            agent_revision = int(publication["revision"])
            agent_config_hash = str(publication["config_hash"])
            agent_snapshot = dict(publication.get("snapshot") or {})
            model_connection = agent_snapshot.get("model_connection") or {}
            model_config = model_connection.get("config") or {}
            model_runtime_provenance = (
                {
                    "legacy": False,
                    "runtime": "claude_agent_sdk",
                    "connection_id": str(model_connection.get("id") or ""),
                    "connection_code": str(model_connection.get("code") or ""),
                    "connection_revision_id": str(model_connection.get("revision_id") or ""),
                    "connection_revision": int(model_connection.get("revision") or 0),
                    "config_hash": str(model_connection.get("config_hash") or ""),
                    "provider_host": _provider_host(str(model_config.get("base_url") or "")),
                    "model": str(model_config.get("model") or ""),
                    "effort_level": str(model_config.get("effort_level") or ""),
                }
                if model_connection
                else {
                    "legacy": True,
                    "runtime": "claude_agent_sdk",
                    "model": str((agent_snapshot.get("model_policy") or {}).get("model") or ""),
                }
            )
            if (
                source_channel != "debug_api"
                and command.source_connector_id
                and not self.agent_config_service.connector_allowed(
                    publication_id=agent_publication_id,
                    direction="ingress",
                    connector_id=command.source_connector_id,
                )
            ):
                raise NonRetryableExecutionError(
                    "Source connector is not assigned to the Agent publication",
                    safe_message="此渠道无法使用该 Agent",
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
                    safe_message="此渠道尚未配置 Agent 结果投递",
                )
        correlation_id = command.correlation_id or new_correlation_id()
        execution_policy = self.execution_policy_resolver.resolve(
            application_policy=command.application_execution_policy or None,
            agent_snapshot=agent_snapshot,
            sources={
                "business_application_id": command.business_application_id,
                "business_application_publication_id": (
                    command.business_application_publication_id
                ),
                "business_application_config_hash": (command.business_application_config_hash),
                "agent_publication_id": agent_publication_id,
                "agent_revision": agent_revision,
                "agent_config_hash": agent_config_hash,
            },
        )
        if command.attachments and self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "Attachment credential encryption is unavailable",
                safe_message="尚未配置附件处理能力",
            )
        continuous_enabled = (
            self.continuous_enabled
            if command.continuous_conversation_enabled is None
            else command.continuous_conversation_enabled
        )
        if source_channel in ISOLATED_SESSION_SOURCE_CHANNELS:
            continuous_enabled = False
        execution_scope_hash = (
            _execution_scope_hash(command.effective_routing_context)
            if command.business_application_id
            else ""
        )
        if command.business_application_id and (
            not command.business_application_publication_id
            or not execution_scope_hash
            or (continuous_enabled and command.conversation_mode != "channel")
        ):
            raise NonRetryableExecutionError(
                "Business Application session isolation facts are incomplete",
                safe_message="业务应用会话隔离配置不完整，请重新发布应用",
                error_code="session_isolation_incomplete",
            )
        session_key = (
            _session_key(
                source_channel=source_channel,
                connector_id=command.source_connector_id,
                project_code=project_code,
                conversation_type=command.conversation_type,
                conversation_id=command.effective_conversation_id,
                requester_id=requester_id,
                bot_identity=command.bot_identity,
                business_application_id=command.business_application_id,
                business_application_publication_id=(command.business_application_publication_id),
                execution_scope_hash=execution_scope_hash,
                conversation_mode=command.conversation_mode,
            )
            if continuous_enabled
            else ""
        )
        attachment_ids: list[str] = []
        with self.repository.database.unit_of_work():
            runtime_authorization_snapshot: dict[str, Any] = {}
            session = (
                self._require_continuable_session(
                    command=command,
                    requester_id=requester_id,
                    execution_scope_hash=execution_scope_hash,
                )
                if command.continue_session_id
                else self.repository.create_session(
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
                    business_application_id=command.business_application_id,
                    business_application_code=command.business_application_code,
                    application_publication_id=(command.business_application_publication_id),
                    execution_scope_hash=execution_scope_hash,
                    isolation_key_version=2,
                    conversation_mode=command.conversation_mode,
                    recent_message_limit=command.recent_message_limit,
                    session_policy=command.session_policy,
                )
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
                business_application_id=command.business_application_id,
                business_application_code=command.business_application_code,
                business_application_publication_id=(command.business_application_publication_id),
                business_application_deployment_id=(command.business_application_deployment_id),
                business_application_route_id=command.business_application_route_id,
                business_application_config_hash=(command.business_application_config_hash),
                business_application_runtime_status=(command.business_application_runtime_status),
                business_application_route_decision={
                    **command.business_application_route_decision,
                    "authorization_snapshot": business_authorization_snapshot,
                    "runtime_authorization": runtime_authorization_snapshot,
                },
                execution_policy=execution_policy.to_dict(),
                model_runtime_provenance=model_runtime_provenance,
            )
            if self.mcp_binding_service is not None:
                self.mcp_binding_service.freeze(job)
            execution_scope_snapshot: dict[str, Any] = {}
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
            dispatch_event = self.repository.create_dispatch_event(
                job_id=job.id,
                job_idempotency_key=job.idempotency_key,
                correlation_id=correlation_id,
                max_attempts=max(
                    1,
                    self.queue_settings.dispatch_outbox_max_attempts,
                ),
                max_replay_count=max(
                    0,
                    self.queue_settings.dispatch_outbox_max_replays,
                ),
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
                    "agent_publication_id": agent_publication_id,
                    "agent_revision": agent_revision,
                    "agent_config_hash": agent_config_hash,
                    "model_runtime_provenance": model_runtime_provenance,
                    "webhook_event_id": command.webhook_event_id,
                    "webhook_trigger_id": command.webhook_trigger_id,
                    "webhook_trigger_publication_id": command.webhook_trigger_publication_id,
                    "business_application_code": command.business_application_code,
                    "business_application_publication_id": (
                        command.business_application_publication_id
                    ),
                    "business_application_deployment_id": (
                        command.business_application_deployment_id
                    ),
                    "business_application_route_id": (command.business_application_route_id),
                    "business_application_runtime_status": (
                        command.business_application_runtime_status
                    ),
                    "execution_scope_id": str(execution_scope_snapshot.get("id") or ""),
                    "execution_scope_hash": str(execution_scope_snapshot.get("scope_hash") or ""),
                    "mcp_subject_snapshot": "frozen",
                },
            )
            self.audit_service.record(
                "job.dispatch.enqueued",
                status="PENDING",
                summary="Agent job dispatch event persisted",
                job_id=job.id,
                actor_id=requester_id,
                payload={
                    "event_id": dispatch_event.id,
                    "event_key": dispatch_event.event_key,
                    "correlation_id": dispatch_event.correlation_id,
                },
            )
        for attachment_id in attachment_ids:
            self.publisher.publish_attachment(attachment_id, correlation_id)
        return job

    def _resolve_app_user_id(self, claimed_subject: str) -> str:
        if self.identity_repository is None:
            return claimed_subject
        try:
            return str(self.identity_repository.get_user(claimed_subject)["id"])
        except NotFound:
            user = self.identity_repository.get_user_by_username(claimed_subject)
            if user is None:
                raise PermissionDenied(
                    "Job requester is not a known app_user",
                    safe_message="当前用户身份无效",
                )
            return str(user["id"])

    def _validate_attachments(
        self,
        attachments: tuple[ChannelAttachment, ...],
        *,
        enabled: bool,
    ) -> None:
        if attachments and not enabled:
            raise NonRetryableExecutionError(
                "message_attachments_disabled",
                safe_message="此业务应用未启用附件",
            )
        if len(attachments) > self.attachment_settings.max_count:
            raise NonRetryableExecutionError(
                "attachment_count_exceeded", safe_message="附件数量过多"
            )
        total = 0
        for attachment in attachments:
            extension = Path(attachment.file_name).suffix.lower()
            if extension not in self.attachment_settings.allowed_extensions:
                raise NonRetryableExecutionError(
                    "unsupported_attachment_type", safe_message="不支持此附件类型"
                )
            if not attachment.source_credential:
                raise NonRetryableExecutionError(
                    "attachment_source_missing", safe_message="缺少附件来源"
                )
            size = int(attachment.declared_size or 0)
            if size > self.attachment_settings.max_file_bytes:
                raise NonRetryableExecutionError(
                    "attachment_size_exceeded", safe_message="附件过大"
                )
            total += size
        if total > self.attachment_settings.max_message_bytes:
            raise NonRetryableExecutionError(
                "attachment_message_size_exceeded",
                safe_message="附件消息过大",
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

    def _require_continuable_session(
        self,
        *,
        command: CreateAgentJobCommand,
        requester_id: str,
        execution_scope_hash: str,
    ) -> AgentSession:
        try:
            session = self.repository.get_session(command.continue_session_id)
        except NotFound as exc:
            raise PermissionDenied(
                "Debug session cannot be continued",
                safe_message="无法继续该调试会话，请使用当前应用和数据范围创建新会话",
                error_code="session_continue_denied",
            ) from exc
        if (
            command.effective_source_channel != "debug_api"
            or session.source_channel != "debug_api"
            or session.requester_id != requester_id
            or session.source_connector_id != command.source_connector_id
            or session.business_application_id != command.business_application_id
            or session.application_publication_id != command.business_application_publication_id
            or session.execution_scope_hash != execution_scope_hash
            or session.isolation_key_version != 2
            or session.history_read_only
            or session.conversation_mode != "channel"
        ):
            raise PermissionDenied(
                "Debug session cannot be continued in this runtime context",
                safe_message="无法继续该调试会话，请使用当前应用和数据范围创建新会话",
                error_code="session_continue_denied",
            )
        return session


def _session_key(
    *,
    source_channel: str,
    connector_id: str,
    project_code: str,
    conversation_type: str,
    conversation_id: str,
    requester_id: str,
    bot_identity: str,
    business_application_id: str = "",
    business_application_publication_id: str = "",
    execution_scope_hash: str = "",
    conversation_mode: str = "legacy",
) -> str:
    if conversation_mode in {"application", "actor"}:
        raise NonRetryableExecutionError(
            "Legacy shared session mode is unsupported",
            safe_message="旧共享会话模式已停用，请改为按渠道会话",
            error_code="session_mode_unsupported",
        )
    if business_application_id:
        if (
            conversation_mode != "channel"
            or not business_application_publication_id
            or not execution_scope_hash
            or not conversation_id
        ):
            raise NonRetryableExecutionError(
                "Session isolation facts are incomplete",
                safe_message="会话隔离上下文不完整",
                error_code="session_isolation_incomplete",
            )
        requester_scope = "" if conversation_type == "group" else requester_id
        canonical = "|".join(
            [
                "v2",
                business_application_id,
                business_application_publication_id,
                source_channel,
                connector_id,
                conversation_type,
                conversation_id,
                requester_scope,
                execution_scope_hash,
            ]
        )
        return "session-key:v2:" + hashlib.sha256(canonical.encode()).hexdigest()
    if conversation_type == "group":
        identity = conversation_id
    else:
        identity = f"{requester_id}:{bot_identity or connector_id}"
    canonical = "|".join(
        [
            business_application_id or "legacy",
            source_channel,
            connector_id,
            project_code,
            conversation_type,
            conversation_mode,
            identity,
        ]
    )
    return "session-key:" + hashlib.sha256(canonical.encode()).hexdigest()


def _execution_scope_hash(routing_context: dict[str, Any]) -> str:
    fields = (
        "project_code",
        "environment",
        "environment_id",
        "base",
        "base_id",
        "workshop",
        "workshop_id",
        "service",
        "execution_scope_id",
    )
    canonical = {field: str(routing_context.get(field) or "").strip() for field in fields}
    return hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _provider_host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "invalid").lower()[:255]
    except ValueError:
        return "invalid"
