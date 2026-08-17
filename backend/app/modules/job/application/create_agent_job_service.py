from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from app.modules.agent.infrastructure.runtime_readiness import AgentRuntimeReadinessGuard
from app.modules.agent_config.application import AgentConfigService
from app.modules.authorization_center.application import BusinessAuthorizationService
from app.modules.audit.application.audit_service import AuditService
from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.channel.domain.channel_event import (
    ChannelAttachment,
    ChannelFileReference,
    ReplyRoute,
    RoutingContext,
)
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.file_workspace.manifest_service import (
    JobFileManifestService,
    is_explicit_text_output_request,
    is_task_text_name,
)
from app.modules.file_workspace.text_format_policy import (
    FileFormatPolicyVersion,
    normalize_file_format_policy_version,
    policy_runtime_protocol_version,
)
from app.modules.job.domain.agent_job import AgentJob, AgentSession
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.job.domain.execution_policy import EffectiveExecutionPolicyResolver
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
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
TERMINAL_ATTACHMENT_STATUSES = {"READY", "REJECTED", "FAILED", "stored_not_interpreted"}


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
    tenant_id: str = ""
    enterprise_id: str = ""
    sender_staff_id: str = ""
    task_workspace_retention_period: str = "WEEK"
    file_format_policy_version: str = "text-v1"
    task_file_features: dict[str, bool] = field(default_factory=dict)
    file_references: tuple[ChannelFileReference, ...] = ()
    requests_file_output: bool = False

    @property
    def effective_requester_id(self) -> str:
        return self.requester_id or "unknown-user"

    @property
    def effective_conversation_id(self) -> str:
        return self.external_conversation_id

    @property
    def effective_source_channel(self) -> str:
        return self.source_channel

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


@dataclass(frozen=True)
class StagedAttachmentIntake:
    session_id: str
    task_workspace_id: str
    message_id: str
    attachment_ids: tuple[str, ...]


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
        identity_repository: IdentityRepository | None = None,
        mcp_tool_snapshot_service: JobMcpToolSnapshotService | None = None,
        runtime_readiness_guard: AgentRuntimeReadinessGuard | None = None,
        file_manifest_service: JobFileManifestService | None = None,
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
        self.identity_repository = identity_repository
        self.mcp_tool_snapshot_service = mcp_tool_snapshot_service
        self.runtime_readiness_guard = runtime_readiness_guard
        self.file_manifest_service = file_manifest_service

    def stage_attachments(self, command: CreateAgentJobCommand) -> StagedAttachmentIntake:
        """Persist a file-only channel event without manufacturing an Agent Job."""

        self._assert_application_runtime_available(command)
        if command.user_message.strip() or not command.attachments:
            raise NonRetryableExecutionError(
                "Attachment staging requires a file-only message",
                safe_message="附件暂存请求无效",
                error_code="attachment_stage_invalid",
            )
        if command.conversation_mode != "channel":
            raise NonRetryableExecutionError(
                "Attachment staging requires channel-isolated sessions",
                safe_message="业务应用会话模式不支持附件暂存",
                error_code="attachment_stage_session_mode_invalid",
            )
        if not command.business_application_id or not command.business_application_publication_id:
            raise NonRetryableExecutionError(
                "Attachment staging requires a frozen Business Application publication",
                safe_message="业务应用发布信息不完整",
                error_code="attachment_stage_publication_missing",
            )
        if not (
            command.task_file_features.get("workspace_enabled")
            and command.task_file_features.get("file_mcp_enabled")
        ):
            raise NonRetryableExecutionError(
                "Attachment staging requires the governed workspace and File MCP",
                safe_message="此业务应用未启用任务文件工作区",
                error_code="attachment_stage_workspace_disabled",
            )
        policy_version = normalize_file_format_policy_version(command.file_format_policy_version)
        if not all(
            is_task_text_name(item.file_name, policy_version=policy_version)
            for item in command.attachments
        ):
            raise NonRetryableExecutionError(
                "Attachment format is outside the frozen task-workspace policy",
                safe_message="当前任务工作区不支持此文本格式",
                error_code="file_workspace_type_unsupported",
            )
        attachments_enabled = (
            self.attachment_settings.enabled
            if command.attachments_enabled is None
            else command.attachments_enabled
        )
        self._validate_attachments(
            command.attachments,
            enabled=attachments_enabled,
            file_format_policy_version=policy_version,
        )
        if self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "Attachment credential encryption is unavailable",
                safe_message="尚未配置附件处理能力",
            )
        continuous_enabled = (
            self.continuous_enabled
            if command.continuous_conversation_enabled is None
            else command.continuous_conversation_enabled
        )
        if not continuous_enabled:
            raise NonRetryableExecutionError(
                "Attachment staging requires continuous channel conversation",
                safe_message="请先启用连续会话再使用任务文件工作区",
                error_code="attachment_stage_continuous_session_required",
            )
        requester_id = command.effective_requester_id
        source_channel = command.effective_source_channel
        external_conversation_id = command.effective_conversation_id
        project_code = str(
            command.effective_routing_context.get("project_code", command.project_code)
            or command.project_code
        )
        reply_route = command.effective_reply_route
        self._assert_connectors_allowed(command, reply_route)
        execution_scope_hash = _execution_scope_hash(command.effective_routing_context)
        if not execution_scope_hash or not external_conversation_id:
            raise NonRetryableExecutionError(
                "Attachment staging session isolation facts are incomplete",
                safe_message="会话隔离上下文不完整",
                error_code="session_isolation_incomplete",
            )
        session_key = _session_key(
            source_channel=source_channel,
            connector_id=command.source_connector_id,
            project_code=project_code,
            conversation_type=command.conversation_type,
            conversation_id=external_conversation_id,
            requester_id=requester_id,
            bot_identity=command.bot_identity,
            external_identity_id=command.external_identity_id,
            business_application_id=command.business_application_id,
            business_application_publication_id=command.business_application_publication_id,
            execution_scope_hash=execution_scope_hash,
            conversation_mode=command.conversation_mode,
        )
        attachment_ids: list[str] = []
        with self.repository.database.unit_of_work():
            session = self.repository.create_session(
                project_code=project_code,
                source_channel=source_channel,
                source_connector_id=command.source_connector_id,
                external_conversation_id=external_conversation_id,
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
                application_publication_id=command.business_application_publication_id,
                execution_scope_hash=execution_scope_hash,
                isolation_key_version=2,
                conversation_mode=command.conversation_mode,
                recent_message_limit=command.recent_message_limit,
                session_policy=command.session_policy,
            )
            if self.file_manifest_service is None:
                raise NonRetryableExecutionError(
                    "Task file workspace service is unavailable",
                    safe_message="任务文件工作区暂时不可用",
                    error_code="file_workspace_unavailable",
                )
            workspace = self.file_manifest_service.resolve_workspace(
                tenant_id=command.tenant_id,
                session_id=session.id,
                requester_id=requester_id,
                conversation_type=command.conversation_type,
                enterprise_id=command.enterprise_id,
                connector_id=command.source_connector_id,
                conversation_id=external_conversation_id,
                sender_staff_id=command.sender_staff_id,
                publication_id=command.business_application_publication_id,
                retention_period=command.task_workspace_retention_period,
                attachments=command.attachments,
                file_references=(),
                requests_file_output=False,
                file_format_policy_version=policy_version,
            )
            if workspace is None:
                raise NonRetryableExecutionError(
                    "Task file workspace could not be resolved for attachment intake",
                    safe_message="无法创建任务文件工作区",
                    error_code="file_workspace_unavailable",
                )
            message_id = self.repository.add_message(
                session_id=session.id,
                job_id=None,
                role="user",
                content="",
                external_message_id=(command.external_message_id or command.external_event_id),
                sender_id=requester_id,
                sender_display_name=command.requester_display_name,
                message_type="attachment_intake",
                content_status="PENDING",
                safe_metadata={"attachment_intake": True},
            )
            for ordinal, attachment in enumerate(command.attachments, start=1):
                created = self.repository.add_attachment(
                    message_id=message_id,
                    job_id=None,
                    task_workspace_id=str(workspace["id"]),
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
                "attachment.intake.staged",
                status="SUCCEEDED",
                summary="File-only channel message staged without an Agent job",
                actor_id=requester_id,
                payload={
                    "session_id": session.id,
                    "task_workspace_id": str(workspace["id"]),
                    "attachment_count": len(attachment_ids),
                    "external_event_id": command.external_event_id,
                },
            )
        correlation_id = command.correlation_id or new_correlation_id()
        for attachment_id in attachment_ids:
            self.publisher.publish_attachment(attachment_id, correlation_id)
        return StagedAttachmentIntake(
            session_id=session.id,
            task_workspace_id=str(workspace["id"]),
            message_id=message_id,
            attachment_ids=tuple(attachment_ids),
        )

    def execute(self, command: CreateAgentJobCommand) -> AgentJob:
        existing = self.repository.get_job_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            if self.mcp_tool_snapshot_service is not None:
                self.mcp_tool_snapshot_service.verify(existing.id)
            return existing
        self._assert_application_runtime_available(command)
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
        policy_version = normalize_file_format_policy_version(command.file_format_policy_version)
        self._validate_attachments(
            command.attachments,
            enabled=attachments_enabled,
            file_format_policy_version=policy_version,
        )
        requester_id = command.effective_requester_id
        source_channel = command.effective_source_channel
        external_conversation_id = command.effective_conversation_id
        if not external_conversation_id and source_channel in ISOLATED_SESSION_SOURCE_CHANNELS:
            external_conversation_id = _isolated_conversation_id(
                source_channel=source_channel,
                idempotency_key=command.idempotency_key,
            )
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
        agent_runtime_kind = "python-v1"
        agent_runtime_protocol_version = "1.0"
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
            agent_runtime_kind = str(publication.get("runtime_kind") or "")
            if agent_runtime_kind == "typescript-v1":
                raise NonRetryableExecutionError(
                    "TypeScript Agent Runtime publications cannot create new Jobs",
                    safe_message=("TypeScript Agent Runtime 已退役；请先迁移到 Python Publication"),
                    error_code="typescript_agent_runtime_retired",
                )
            if agent_runtime_kind != "python-v1":
                raise NonRetryableExecutionError(
                    "Pinned Agent publication runtime is unsupported",
                    safe_message="固定的 Agent Runtime 配置无效",
                    error_code="agent_runtime_kind_unsupported",
                )
            agent_runtime_protocol_version = policy_runtime_protocol_version(policy_version)
            agent_snapshot = dict(publication.get("snapshot") or {})
            supported_protocols = tuple(
                str(item) for item in agent_snapshot.get("supported_runtime_protocol_versions", [])
            )
            if not supported_protocols:
                supported_protocols = ("1.0", "1.1", "1.2")
            if agent_runtime_protocol_version not in supported_protocols:
                raise NonRetryableExecutionError(
                    "Pinned Agent publication does not support the required Runtime protocol",
                    safe_message="固定的 Agent 发布版本不支持文件策略所需 Runtime 协议",
                    error_code="agent_runtime_protocol_unsupported",
                )
            if self.runtime_readiness_guard is not None:
                self.runtime_readiness_guard.require_ready(agent_runtime_kind)
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
                conversation_id=external_conversation_id,
                requester_id=requester_id,
                bot_identity=command.bot_identity,
                external_identity_id=command.external_identity_id,
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
            if command.business_application_id:
                assert self.business_authorization_service is not None
                runtime_authorization_snapshot = (
                    self.business_authorization_service.capture_runtime_facts(
                        user_id=requester_id,
                        application_id=command.business_application_id,
                        publication_id=command.business_application_publication_id,
                        publication_config_hash=command.business_application_config_hash,
                    )
                )
            session = (
                self._require_continuable_session(
                    command=command,
                    requester_id=requester_id,
                    execution_scope_hash=execution_scope_hash,
                )
                if command.continue_session_id
                else self.repository.create_session(
                    project_code=project_code,
                    source_channel=source_channel,
                    source_connector_id=command.source_connector_id,
                    external_conversation_id=external_conversation_id,
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
            file_workspace = (
                self.file_manifest_service.resolve_workspace(
                    tenant_id=command.tenant_id,
                    session_id=session.id,
                    requester_id=requester_id,
                    conversation_type=command.conversation_type,
                    enterprise_id=command.enterprise_id,
                    connector_id=command.source_connector_id,
                    conversation_id=external_conversation_id,
                    sender_staff_id=command.sender_staff_id,
                    publication_id=command.business_application_publication_id,
                    retention_period=command.task_workspace_retention_period,
                    attachments=command.attachments,
                    file_references=command.file_references,
                    requests_file_output=(
                        command.requests_file_output
                        or is_explicit_text_output_request(
                            command.user_message,
                            policy_version=command.file_format_policy_version,
                        )
                    ),
                    file_format_policy_version=command.file_format_policy_version,
                )
                if (
                    self.file_manifest_service is not None
                    and bool(command.task_file_features.get("workspace_enabled"))
                )
                else None
            )
            staged_attachments = (
                self.repository.list_staged_attachments(
                    session_id=session.id,
                    task_workspace_id=str(file_workspace["id"]),
                )
                if file_workspace is not None
                and bool(command.task_file_features.get("file_mcp_enabled"))
                else []
            )
            job = self.repository.create_job(
                session_id=session.id,
                idempotency_key=command.idempotency_key,
                project_code=project_code,
                source_channel=source_channel,
                source_connector_id=command.source_connector_id,
                requester_id=requester_id,
                input_message=command.user_message,
                max_retry_count=self.queue_settings.max_retry_count,
                external_event_id=command.external_event_id,
                external_message_id=(command.external_message_id or command.external_event_id),
                requester_display_name=command.requester_display_name,
                message_type="multimodal" if command.attachments else "text",
                message_content_status="PENDING" if command.attachments else "READY",
                routing_context=command.effective_routing_context,
                reply_route=reply_route,
                initial_status=(
                    JobStatus.WAITING_INPUT
                    if command.attachments or staged_attachments
                    else JobStatus.PENDING
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
                    **(
                        {"task_file_features": dict(command.task_file_features)}
                        if command.task_file_features
                        else {}
                    ),
                    "file_format_policy_version": normalize_file_format_policy_version(
                        command.file_format_policy_version
                    ).value,
                    "authorization_snapshot": business_authorization_snapshot,
                    "runtime_authorization": runtime_authorization_snapshot,
                },
                execution_policy=execution_policy.to_dict(),
                model_runtime_provenance=model_runtime_provenance,
                agent_runtime_kind=agent_runtime_kind,
                agent_runtime_protocol_version=agent_runtime_protocol_version,
                task_workspace_id=(str(file_workspace["id"]) if file_workspace else ""),
            )
            mcp_tool_snapshot: dict[str, Any] = {}
            if command.business_application_id and self.mcp_tool_snapshot_service is not None:
                file_server_enabled_for_job = bool(
                    file_workspace is not None
                    and command.task_file_features.get("file_mcp_enabled")
                )
                mcp_tool_snapshot = self.mcp_tool_snapshot_service.freeze(
                    job_id=job.id,
                    requester_id=requester_id,
                    application_id=command.business_application_id,
                    application_publication_id=(command.business_application_publication_id),
                    application_config_hash=(command.business_application_config_hash),
                    agent_publication_id=agent_publication_id,
                    routing_context=command.effective_routing_context,
                    business_authorization=business_authorization_snapshot,
                    runtime_authorization=runtime_authorization_snapshot,
                    allowed_server_codes=(
                        None
                        if file_server_enabled_for_job
                        else frozenset(
                            definition.server_code
                            for definition in MCP_TOOL_MANIFEST.values()
                            if definition.server_code != "file-service"
                        )
                    ),
                )
            elif agent_publication_id and self.mcp_tool_snapshot_service is not None:
                mcp_tool_snapshot = self.mcp_tool_snapshot_service.freeze_agent_only(
                    job_id=job.id,
                    requester_id=requester_id,
                    agent_publication_id=agent_publication_id,
                    routing_context=command.effective_routing_context,
                    business_authorization=business_authorization_snapshot,
                    runtime_authorization=runtime_authorization_snapshot,
                )
            for ordinal, attachment in enumerate(command.attachments, start=1):
                assert self.credential_cipher is not None
                created = self.repository.add_attachment(
                    message_id=job.input_message_id,
                    job_id=job.id,
                    task_workspace_id=(str(file_workspace["id"]) if file_workspace else ""),
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
            if staged_attachments and file_workspace is not None:
                claimed = self.repository.claim_staged_attachments(
                    session_id=session.id,
                    task_workspace_id=str(file_workspace["id"]),
                    job_id=job.id,
                )
                self.audit_service.record(
                    "attachment.intake.claimed",
                    status="SUCCEEDED",
                    summary="A text-triggered Agent job claimed staged attachments",
                    job_id=job.id,
                    actor_id=requester_id,
                    payload={
                        "attachment_count": len(claimed) - len(command.attachments),
                        "task_workspace_id": str(file_workspace["id"]),
                    },
                )
            file_manifest: dict[str, Any] = {}
            if file_workspace is not None and bool(
                command.task_file_features.get("file_mcp_enabled")
            ):
                assert self.file_manifest_service is not None
                self.file_manifest_service.register_request(
                    job_id=job.id,
                    workspace=file_workspace,
                    requester_id=requester_id,
                    publication_id=command.business_application_publication_id,
                    file_references=command.file_references,
                    file_format_policy_version=command.file_format_policy_version,
                )
                if not self.file_manifest_service.has_pending_text_attachments(job.id):
                    file_manifest = self.file_manifest_service.finalize(job.id) or {}
            job_attachments = self.repository.list_attachments(job.id)
            if job.status == JobStatus.WAITING_INPUT and all(
                item.status in TERMINAL_ATTACHMENT_STATUSES for item in job_attachments
            ):
                job = self.repository.transition_job(
                    job_id=job.id,
                    target=JobStatus.PENDING,
                )
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
                    "agent_runtime_kind": job.agent_runtime_kind,
                    "agent_runtime_protocol_version": (job.agent_runtime_protocol_version),
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
                    "mcp_tool_snapshot_id": str(mcp_tool_snapshot.get("id") or ""),
                    "mcp_tool_snapshot_hash": str(mcp_tool_snapshot.get("snapshot_hash") or ""),
                    "task_workspace_id": str(file_workspace.get("id") or "")
                    if file_workspace
                    else "",
                    "file_manifest_id": str(file_manifest.get("id") or ""),
                    "file_manifest_hash": str(file_manifest.get("manifest_hash") or ""),
                    "sender_staff_id": command.sender_staff_id,
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

    def _assert_application_runtime_available(
        self,
        command: CreateAgentJobCommand,
    ) -> None:
        del command

    def _validate_attachments(
        self,
        attachments: tuple[ChannelAttachment, ...],
        *,
        enabled: bool,
        file_format_policy_version: object = FileFormatPolicyVersion.TEXT_V1,
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
            is_workspace_text = is_task_text_name(
                attachment.file_name,
                policy_version=file_format_policy_version,
            )
            max_file_bytes = (
                15 * 1024 * 1024 if is_workspace_text else self.attachment_settings.max_file_bytes
            )
            if size > max_file_bytes:
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
    external_identity_id: str = "",
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
                project_code,
                conversation_type,
                conversation_id,
                requester_scope,
                external_identity_id,
                execution_scope_hash,
            ]
        )
        return "session-key:v2:" + hashlib.sha256(canonical.encode()).hexdigest()
    if conversation_type == "group":
        requester_scope = ""
        external_identity_scope = ""
    else:
        requester_scope = requester_id
        external_identity_scope = external_identity_id
    canonical = "|".join(
        [
            business_application_id or "legacy",
            source_channel,
            connector_id,
            project_code,
            conversation_type,
            conversation_mode,
            conversation_id,
            requester_scope,
            external_identity_scope,
            bot_identity or connector_id,
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


def _isolated_conversation_id(*, source_channel: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{source_channel}:{idempotency_key}".encode("utf-8")).hexdigest()
    return f"isolated:{source_channel}:{digest}"


def _provider_host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "invalid").lower()[:255]
    except ValueError:
        return "invalid"
