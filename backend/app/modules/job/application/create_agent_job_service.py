from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
import hashlib
import json
from pathlib import Path

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
from app.modules.document_processing import resolve_document_processing_profile
from app.modules.file_workspace.manifest_service import (
    JobFileManifestService,
    is_task_text_name,
)
from app.modules.job.application.agent_binding import AgentBinding, bind_agent_publication
from app.modules.job.application.file_context import (
    AdmissionFileReference,
    CurrentMessageAttachment,
    FileAdmissionPlan,
    WorkspaceFileCandidate,
    plan_file_admission,
    render_file_admission_notice,
)
from app.modules.job.domain.agent_job import AgentJob, AgentSession
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.job.domain.execution_policy import (
    EffectiveExecutionPolicyResolver,
    JobExecutionPolicySnapshot,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.attachment_repository import AttachmentRepository
from app.modules.job.infrastructure.dispatch_repository import JobDispatchRepository
from app.modules.delivery.infrastructure.repository import DeliveryRepository
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.job.infrastructure.session_repository import SessionRepository
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.message_bus.application.message_publisher import MessagePublisher
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import AttachmentSettings, ExecutionSettings, QueueSettings
from app.shared.database import require_shared_database
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


def _is_supported_workspace_attachment(
    file_name: str,
    *,
    document_processing_profile_code: object,
) -> bool:
    if is_task_text_name(file_name):
        return True
    profile = resolve_document_processing_profile(document_processing_profile_code)
    if profile is None:
        return False
    extension = Path(file_name).suffix.lower()
    return any(extension in definition.extensions for definition in profile.source_formats)


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
    document_processing_profile_code: str = "NONE"
    task_file_features: dict[str, bool] = field(default_factory=dict)
    file_references: tuple[ChannelFileReference, ...] = ()
    requests_file_output: bool = False
    quoted_external_message_id: str = ""
    resolver_text: str = ""

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


@dataclass(frozen=True)
class SystemNoticeIntake:
    session_id: str
    message_id: str
    delivery_id: str
    reason_code: str
    task_workspace_id: str = ""


@dataclass(frozen=True)
class _ChannelRouting:
    requester_id: str
    source_channel: str
    external_conversation_id: str
    project_code: str
    reply_route: dict[str, Any]

    @classmethod
    def from_command(
        cls,
        command: CreateAgentJobCommand,
        *,
        isolate_conversation: bool,
    ) -> _ChannelRouting:
        source_channel = command.effective_source_channel
        external_conversation_id = command.effective_conversation_id
        if (
            isolate_conversation
            and not external_conversation_id
            and source_channel in ISOLATED_SESSION_SOURCE_CHANNELS
        ):
            external_conversation_id = _isolated_conversation_id(
                source_channel=source_channel,
                idempotency_key=command.idempotency_key,
            )
        project_code = command.effective_routing_context.get("project_code", command.project_code)
        return cls(
            requester_id=command.effective_requester_id,
            source_channel=source_channel,
            external_conversation_id=external_conversation_id,
            project_code=str(project_code or command.project_code),
            reply_route=command.effective_reply_route,
        )


@dataclass(frozen=True)
class _BusinessAuthorization:
    authorized: bool
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class _SessionIsolation:
    execution_scope_hash: str
    session_key: str


@dataclass(frozen=True)
class _FileAdmission:
    plan: FileAdmissionPlan
    workspace: dict[str, Any] | None

    @property
    def workspace_id(self) -> str:
        return str(self.workspace["id"]) if self.workspace else ""


class CreateAgentJobService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        dispatch_repository: JobDispatchRepository,
        delivery_repository: DeliveryRepository,
        attachment_repository: AttachmentRepository,
        session_repository: SessionRepository,
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
        delivery_service: Any = None,
    ) -> None:
        require_shared_database(
            repository,
            dispatch_repository,
            delivery_repository,
            attachment_repository,
            session_repository,
        )
        self.repository = repository
        self.dispatch_repository = dispatch_repository
        self.delivery_repository = delivery_repository
        self.attachment_repository = attachment_repository
        self.session_repository = session_repository
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
        self.delivery_service = delivery_service

    def stage_attachments(self, command: CreateAgentJobCommand) -> StagedAttachmentIntake:
        """Persist a file-only channel event without manufacturing an Agent Job."""

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
        if not all(
            _is_supported_workspace_attachment(
                item.file_name,
                document_processing_profile_code=command.document_processing_profile_code,
            )
            for item in command.attachments
        ):
            raise NonRetryableExecutionError(
                "Attachment format is outside the frozen task-workspace policy",
                safe_message="当前任务工作区不支持此文本格式",
                error_code="file_workspace_type_unsupported",
            )
        self._validate_attachments(command)
        credential_cipher = self._require_credential_cipher()
        if not self._continuous_conversation_enabled(command):
            raise NonRetryableExecutionError(
                "Attachment staging requires continuous channel conversation",
                safe_message="请先启用连续会话再使用任务文件工作区",
                error_code="attachment_stage_continuous_session_required",
            )
        routing = _ChannelRouting.from_command(command, isolate_conversation=False)
        self._assert_connectors_allowed(command, routing.reply_route)
        execution_scope_hash = _execution_scope_hash(command.effective_routing_context)
        if not execution_scope_hash or not routing.external_conversation_id:
            raise NonRetryableExecutionError(
                "Attachment staging session isolation facts are incomplete",
                safe_message="会话隔离上下文不完整",
                error_code="session_isolation_incomplete",
            )
        session_key = _channel_session_key(command, routing, execution_scope_hash)
        attachment_ids: list[str] = []
        new_attachment_ids: list[str] = []
        with self.repository.database.unit_of_work():
            session = self._create_session(
                command,
                routing,
                session_key=session_key,
                execution_scope_hash=execution_scope_hash,
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
                requester_id=routing.requester_id,
                conversation_type=command.conversation_type,
                enterprise_id=command.enterprise_id,
                connector_id=command.source_connector_id,
                conversation_id=routing.external_conversation_id,
                sender_staff_id=command.sender_staff_id,
                publication_id=command.business_application_publication_id,
                retention_period=command.task_workspace_retention_period,
                attachments=command.attachments,
                file_references=(),
                requests_file_output=False,
            )
            if workspace is None:
                raise NonRetryableExecutionError(
                    "Task file workspace could not be resolved for attachment intake",
                    safe_message="无法创建任务文件工作区",
                    error_code="file_workspace_unavailable",
                )
            message_id = self.session_repository.add_message(
                session_id=session.id,
                job_id=None,
                role="user",
                content="",
                external_message_id=(command.external_message_id or command.external_event_id),
                sender_id=routing.requester_id,
                sender_display_name=command.requester_display_name,
                message_type="attachment_intake",
                content_status="PENDING",
                safe_metadata={"attachment_intake": True},
            )
            for ordinal, attachment in enumerate(command.attachments, start=1):
                attachment_row, attachment_created = (
                    self.attachment_repository.add_or_get_attachment(
                        message_id=message_id,
                        job_id=None,
                        task_workspace_id=str(workspace["id"]),
                        ordinal=ordinal,
                        media_type=attachment.media_type,
                        file_name=attachment.file_name,
                        declared_mime=attachment.declared_mime,
                        declared_size=attachment.declared_size,
                        credential_ciphertext=credential_cipher.encrypt(
                            attachment.source_credential
                        ),
                        credential_type=attachment.source_credential_type,
                        credential_expires_at=attachment.source_credential_expires_at,
                    )
                )
                attachment_ids.append(attachment_row.id)
                if attachment_created:
                    new_attachment_ids.append(attachment_row.id)
            self.audit_service.record(
                "attachment.intake.staged",
                status="SUCCEEDED",
                summary="File-only channel message staged without an Agent job",
                actor_id=routing.requester_id,
                payload={
                    "session_id": session.id,
                    "task_workspace_id": str(workspace["id"]),
                    "attachment_count": len(attachment_ids),
                    "new_attachment_count": len(new_attachment_ids),
                    "external_event_id": command.external_event_id,
                },
            )
        correlation_id = command.correlation_id or new_correlation_id()
        for attachment_id in new_attachment_ids:
            self.publisher.publish_attachment(attachment_id, correlation_id)
        return StagedAttachmentIntake(
            session_id=session.id,
            task_workspace_id=str(workspace["id"]),
            message_id=message_id,
            attachment_ids=tuple(attachment_ids),
        )

    def execute(self, command: CreateAgentJobCommand) -> AgentJob | SystemNoticeIntake:
        replayed = self._replay(command)
        if replayed is not None:
            return replayed
        if command.conversation_mode in {"application", "actor"}:
            raise NonRetryableExecutionError(
                "Legacy shared session mode cannot create new Jobs",
                safe_message="旧共享会话模式已停用，请将应用重新发布为按渠道会话",
                error_code="session_mode_unsupported",
            )
        self._validate_attachments(command)
        routing = _ChannelRouting.from_command(command, isolate_conversation=True)
        self._assert_connectors_allowed(command, routing.reply_route)
        authorization = self._authorize_job_creation(command, routing)
        agent = self._bind_agent(command, routing, authorization)
        correlation_id = command.correlation_id or new_correlation_id()
        execution_policy = self._resolve_execution_policy(command, agent)
        if command.attachments:
            self._require_credential_cipher()
        isolation = self._session_isolation(command, routing)
        with self.repository.database.unit_of_work():
            runtime_authorization = self._capture_runtime_authorization(command, routing)
            session = self._open_session(command, routing, isolation)
            admission = self._admit_files(command, routing, session)
            if admission.plan.gate.action == "system_notice":
                return self._persist_system_notice(
                    command=command,
                    session=session,
                    workspace_id=admission.workspace_id,
                    reply_route=routing.reply_route,
                    file_plan=admission.plan,
                    correlation_id=correlation_id,
                    requester_id=routing.requester_id,
                )
            job = self._create_job(
                command,
                routing,
                session=session,
                admission=admission,
                authorization=authorization,
                runtime_authorization=runtime_authorization,
                agent=agent,
                execution_policy=execution_policy,
            )
            mcp_tool_snapshot = self._freeze_mcp_tools(
                command,
                routing,
                job=job,
                admission=admission,
                authorization=authorization,
                runtime_authorization=runtime_authorization,
                agent=agent,
            )
            attachment_ids = self._add_message_attachments(command, job, admission)
            self._claim_bound_attachments(routing, session=session, job=job, admission=admission)
            file_manifest = self._register_file_manifest(command, routing, job, admission)
            job = self._release_if_sources_ready(job)
            self._enqueue_dispatch(
                command,
                routing,
                job=job,
                admission=admission,
                agent=agent,
                correlation_id=correlation_id,
                mcp_tool_snapshot=mcp_tool_snapshot,
                file_manifest=file_manifest,
            )
        for attachment_id in attachment_ids:
            self.publisher.publish_attachment(attachment_id, correlation_id)
        return job

    def _replay(self, command: CreateAgentJobCommand) -> AgentJob | SystemNoticeIntake | None:
        existing = self.repository.get_job_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            if self.mcp_tool_snapshot_service is not None:
                self.mcp_tool_snapshot_service.verify(existing.id)
            return existing
        existing_notice = self.delivery_repository.get_system_notice_by_idempotency_key(
            command.idempotency_key
        )
        if existing_notice is None:
            return None
        binding = json.loads(str(existing_notice.get("delivery_binding_json") or "{}"))
        if not isinstance(binding, dict):
            binding = {}
        return SystemNoticeIntake(
            session_id=str(existing_notice.get("session_id") or ""),
            message_id=str(binding.get("user_message_id") or ""),
            delivery_id=str(existing_notice.get("id") or ""),
            reason_code=str(binding.get("reason_code") or "file_readable_content_not_ready"),
            task_workspace_id=str(binding.get("task_workspace_id") or ""),
        )

    def _authorize_job_creation(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
    ) -> _BusinessAuthorization:
        authorization = _BusinessAuthorization(authorized=False, snapshot={})
        if command.business_application_id:
            if routing.source_channel in {"dingding", "dingding_stream"}:
                snapshot: dict[str, Any] = {
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
                    user_id=routing.requester_id,
                    application_id=command.business_application_id,
                    stage="job_create",
                )
                snapshot = dict(business_decision)
            authorization = _BusinessAuthorization(authorized=True, snapshot=snapshot)
            self.audit_service.record(
                "authorization.business.job_create",
                status="SUCCEEDED",
                summary="Business authorization allowed Agent job creation",
                actor_id=routing.requester_id,
                payload=authorization.snapshot,
            )
        self.audit_service.record(
            "permission.job_create.start",
            status="STARTED",
            summary="Checking user permission for Agent job creation",
            actor_id=routing.requester_id,
            payload={
                "project_code": routing.project_code,
                "source_channel": routing.source_channel,
                "source_connector_id": command.source_connector_id,
                "delivery_type": routing.reply_route.get("type"),
                "delivery_connector_id": routing.reply_route.get("connector_id"),
            },
        )
        if not authorization.authorized:
            self.permission_service.assert_user_can_create_job(
                user_id=routing.requester_id,
                project_code=routing.project_code,
            )
        return authorization

    def _bind_agent(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        authorization: _BusinessAuthorization,
    ) -> AgentBinding:
        if not (self.published_agent_runtime_enabled or command.fixed_agent_publication_id):
            return AgentBinding()
        return bind_agent_publication(
            agent_config_service=self.agent_config_service,
            permission_service=self.permission_service,
            database=self.repository.database,
            runtime_readiness_guard=self.runtime_readiness_guard,
            agent_code=command.agent_code or self.default_agent_code,
            requester_id=routing.requester_id,
            agent_permission_required=not authorization.authorized,
            fixed_publication_id=command.fixed_agent_publication_id,
            fixed_revision=command.fixed_agent_revision,
            fixed_config_hash=command.fixed_agent_config_hash,
            business_application_job=bool(command.business_application_id),
            source_channel=routing.source_channel,
            source_connector_id=command.source_connector_id,
            reply_route=routing.reply_route,
        )

    def _resolve_execution_policy(
        self,
        command: CreateAgentJobCommand,
        agent: AgentBinding,
    ) -> JobExecutionPolicySnapshot:
        return self.execution_policy_resolver.resolve(
            application_policy=command.application_execution_policy or None,
            agent_snapshot=agent.snapshot,
            sources={
                "business_application_id": command.business_application_id,
                "business_application_publication_id": (
                    command.business_application_publication_id
                ),
                "business_application_config_hash": (command.business_application_config_hash),
                "agent_publication_id": agent.publication_id,
                "agent_revision": agent.revision,
                "agent_config_hash": agent.config_hash,
            },
        )

    def _session_isolation(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
    ) -> _SessionIsolation:
        continuous_enabled = self._continuous_conversation_enabled(command)
        if routing.source_channel in ISOLATED_SESSION_SOURCE_CHANNELS:
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
        return _SessionIsolation(
            execution_scope_hash=execution_scope_hash,
            session_key=(
                _channel_session_key(command, routing, execution_scope_hash)
                if continuous_enabled
                else ""
            ),
        )

    def _capture_runtime_authorization(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
    ) -> dict[str, Any]:
        if not command.business_application_id:
            return {}
        assert self.business_authorization_service is not None
        return self.business_authorization_service.capture_runtime_facts(
            user_id=routing.requester_id,
            application_id=command.business_application_id,
            publication_id=command.business_application_publication_id,
            publication_config_hash=command.business_application_config_hash,
        )

    def _open_session(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        isolation: _SessionIsolation,
    ) -> AgentSession:
        if command.continue_session_id:
            return self._require_continuable_session(
                command=command,
                requester_id=routing.requester_id,
                execution_scope_hash=isolation.execution_scope_hash,
            )
        return self._create_session(
            command,
            routing,
            session_key=isolation.session_key,
            execution_scope_hash=isolation.execution_scope_hash,
        )

    def _admit_files(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        session: AgentSession,
    ) -> _FileAdmission:
        workspace_feature_enabled = bool(command.task_file_features.get("workspace_enabled"))
        active_workspace = (
            self.file_manifest_service.active_workspace(session.id)
            if self.file_manifest_service is not None and workspace_feature_enabled
            else None
        )
        file_plan = self._plan_file_admission(
            command=command,
            session_id=session.id,
            active_workspace_id=(str(active_workspace.get("id") or "") if active_workspace else ""),
            workspace_feature_enabled=workspace_feature_enabled,
        )
        file_workspace = (
            self.file_manifest_service.resolve_workspace(
                tenant_id=command.tenant_id,
                session_id=session.id,
                requester_id=routing.requester_id,
                conversation_type=command.conversation_type,
                enterprise_id=command.enterprise_id,
                connector_id=command.source_connector_id,
                conversation_id=routing.external_conversation_id,
                sender_staff_id=command.sender_staff_id,
                publication_id=command.business_application_publication_id,
                retention_period=command.task_workspace_retention_period,
                attachments=command.attachments,
                file_references=command.file_references,
                requests_file_output=file_plan.effective_output_intent,
                force_create=file_plan.workspace_requirement == "force_create",
            )
            if self.file_manifest_service is not None and file_plan.workspace_requirement != "none"
            else None
        )
        return _FileAdmission(plan=file_plan, workspace=file_workspace)

    def _create_job(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        *,
        session: AgentSession,
        admission: _FileAdmission,
        authorization: _BusinessAuthorization,
        runtime_authorization: dict[str, Any],
        agent: AgentBinding,
        execution_policy: JobExecutionPolicySnapshot,
    ) -> AgentJob:
        return self.repository.create_job(
            session_id=session.id,
            idempotency_key=command.idempotency_key,
            project_code=routing.project_code,
            source_channel=routing.source_channel,
            source_connector_id=command.source_connector_id,
            requester_id=routing.requester_id,
            input_message=command.user_message,
            max_retry_count=self.queue_settings.max_retry_count,
            external_event_id=command.external_event_id,
            external_message_id=(command.external_message_id or command.external_event_id),
            requester_display_name=command.requester_display_name,
            message_type="multimodal" if command.attachments else "text",
            message_content_status="PENDING" if command.attachments else "READY",
            routing_context=command.effective_routing_context,
            reply_route=routing.reply_route,
            initial_status=(
                JobStatus.WAITING_INPUT
                if admission.plan.gate.action == "wait_source" or command.attachments
                else JobStatus.PENDING
            ),
            internal_user_id=routing.requester_id,
            external_identity_id=command.external_identity_id,
            agent_definition_id=agent.definition_id,
            agent_publication_id=agent.publication_id,
            agent_revision=agent.revision,
            agent_config_hash=agent.config_hash,
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
                "authorization_snapshot": authorization.snapshot,
                "runtime_authorization": runtime_authorization,
                "file_turn_dependencies": admission.plan.dependency_payloads(),
            },
            execution_policy=execution_policy.to_dict(),
            model_runtime_provenance=agent.model_runtime_provenance,
            agent_runtime_kind=agent.runtime_kind,
            agent_runtime_protocol_version=agent.runtime_protocol_version,
            task_workspace_id=admission.workspace_id,
            quoted_external_message_id=command.quoted_external_message_id,
        )

    def _freeze_mcp_tools(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        *,
        job: AgentJob,
        admission: _FileAdmission,
        authorization: _BusinessAuthorization,
        runtime_authorization: dict[str, Any],
        agent: AgentBinding,
    ) -> dict[str, Any]:
        if self.mcp_tool_snapshot_service is None:
            return {}
        if command.business_application_id:
            file_server_enabled_for_job = bool(
                admission.workspace is not None and admission.plan.file_mcp_enabled
            )
            return self.mcp_tool_snapshot_service.freeze(
                job_id=job.id,
                requester_id=routing.requester_id,
                application_id=command.business_application_id,
                application_publication_id=(command.business_application_publication_id),
                application_config_hash=(command.business_application_config_hash),
                agent_publication_id=agent.publication_id,
                routing_context=command.effective_routing_context,
                business_authorization=authorization.snapshot,
                runtime_authorization=runtime_authorization,
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
        if agent.publication_id:
            return self.mcp_tool_snapshot_service.freeze_agent_only(
                job_id=job.id,
                requester_id=routing.requester_id,
                agent_publication_id=agent.publication_id,
                routing_context=command.effective_routing_context,
                business_authorization=authorization.snapshot,
                runtime_authorization=runtime_authorization,
            )
        return {}

    def _add_message_attachments(
        self,
        command: CreateAgentJobCommand,
        job: AgentJob,
        admission: _FileAdmission,
    ) -> list[str]:
        attachment_ids: list[str] = []
        for ordinal, attachment in enumerate(command.attachments, start=1):
            assert self.credential_cipher is not None
            created = self.attachment_repository.add_attachment(
                message_id=job.input_message_id,
                job_id=job.id,
                task_workspace_id=admission.workspace_id,
                ordinal=ordinal,
                media_type=attachment.media_type,
                file_name=attachment.file_name,
                declared_mime=attachment.declared_mime,
                declared_size=attachment.declared_size,
                credential_ciphertext=self.credential_cipher.encrypt(attachment.source_credential),
                credential_type=attachment.source_credential_type,
                credential_expires_at=attachment.source_credential_expires_at,
            )
            attachment_ids.append(created.id)
        return attachment_ids

    def _claim_bound_attachments(
        self,
        routing: _ChannelRouting,
        *,
        session: AgentSession,
        job: AgentJob,
        admission: _FileAdmission,
    ) -> None:
        bound_attachment_ids = tuple(
            item.attachment_id
            for item in admission.plan.gate.dependencies
            if item.attachment_id and not item.attachment_id.startswith("current:")
        )
        workspace = admission.workspace
        if not bound_attachment_ids or workspace is None:
            return
        claimed = self.attachment_repository.claim_staged_attachments(
            session_id=session.id,
            task_workspace_id=str(workspace["id"]),
            job_id=job.id,
            attachment_ids=bound_attachment_ids,
        )
        self.audit_service.record(
            "attachment.intake.claimed",
            status="SUCCEEDED",
            summary="A text-triggered Agent job claimed bound staged attachments",
            job_id=job.id,
            actor_id=routing.requester_id,
            payload={
                "attachment_count": len(claimed),
                "task_workspace_id": str(workspace["id"]),
            },
        )

    def _register_file_manifest(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        job: AgentJob,
        admission: _FileAdmission,
    ) -> dict[str, Any]:
        workspace = admission.workspace
        if workspace is None or not admission.plan.file_mcp_enabled:
            return {}
        assert self.file_manifest_service is not None
        manifest_references = tuple(
            ChannelFileReference(
                file_id=item.file_id,
                version_id=item.version_id,
                auto_materialize=item.auto_materialize,
            )
            for item in admission.plan.manifest_bindings
        )
        self.file_manifest_service.register_request(
            job_id=job.id,
            workspace=workspace,
            requester_id=routing.requester_id,
            publication_id=command.business_application_publication_id,
            file_references=manifest_references,
        )
        if self.file_manifest_service.has_pending_text_attachments(job.id):
            return {}
        return self.file_manifest_service.finalize(job.id) or {}

    def _release_if_sources_ready(self, job: AgentJob) -> AgentJob:
        job_attachments = self.attachment_repository.list_attachments(job.id)
        if (
            job.status == JobStatus.WAITING_INPUT
            and job_attachments
            and all(item.status in TERMINAL_ATTACHMENT_STATUSES for item in job_attachments)
        ):
            return self.repository.transition_job(
                job_id=job.id,
                target=JobStatus.PENDING,
            )
        return job

    def _enqueue_dispatch(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        *,
        job: AgentJob,
        admission: _FileAdmission,
        agent: AgentBinding,
        correlation_id: str,
        mcp_tool_snapshot: dict[str, Any],
        file_manifest: dict[str, Any],
    ) -> None:
        file_workspace = admission.workspace
        dispatch_event = self.dispatch_repository.create_dispatch_event(
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
            actor_id=routing.requester_id,
            payload={
                "idempotency_key": command.idempotency_key,
                "source_channel": routing.source_channel,
                "source_connector_id": command.source_connector_id,
                "external_event_id": command.external_event_id,
                "agent_publication_id": agent.publication_id,
                "agent_revision": agent.revision,
                "agent_config_hash": agent.config_hash,
                "model_runtime_provenance": agent.model_runtime_provenance,
                "agent_runtime_kind": job.agent_runtime_kind,
                "agent_runtime_protocol_version": (job.agent_runtime_protocol_version),
                "webhook_event_id": command.webhook_event_id,
                "webhook_trigger_id": command.webhook_trigger_id,
                "webhook_trigger_publication_id": command.webhook_trigger_publication_id,
                "business_application_code": command.business_application_code,
                "business_application_publication_id": (
                    command.business_application_publication_id
                ),
                "business_application_deployment_id": (command.business_application_deployment_id),
                "business_application_route_id": (command.business_application_route_id),
                "business_application_runtime_status": (
                    command.business_application_runtime_status
                ),
                "mcp_tool_snapshot_id": str(mcp_tool_snapshot.get("id") or ""),
                "mcp_tool_snapshot_hash": str(mcp_tool_snapshot.get("snapshot_hash") or ""),
                "task_workspace_id": str(file_workspace.get("id") or "") if file_workspace else "",
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
            actor_id=routing.requester_id,
            payload={
                "event_id": dispatch_event.id,
                "event_key": dispatch_event.event_key,
                "correlation_id": dispatch_event.correlation_id,
            },
        )

    def _plan_file_admission(
        self,
        *,
        command: CreateAgentJobCommand,
        session_id: str,
        active_workspace_id: str,
        workspace_feature_enabled: bool,
    ) -> FileAdmissionPlan:
        observed_at = datetime.now(UTC)
        rows = self.attachment_repository.list_file_turn_candidate_rows(
            session_id=session_id,
            workspace_id=active_workspace_id,
        )
        retained_rows = self.attachment_repository.list_session_retained_attachment_rows(
            session_id=session_id,
            now=observed_at.isoformat(),
        )
        return plan_file_admission(
            text=command.resolver_text or command.user_message,
            output_intent_hint=command.requests_file_output,
            workspace_enabled=workspace_feature_enabled,
            workspace_adapter_available=self.file_manifest_service is not None,
            has_active_workspace=bool(active_workspace_id),
            file_mcp_enabled=bool(command.task_file_features.get("file_mcp_enabled")),
            current_attachments=tuple(
                CurrentMessageAttachment(file_name=item.file_name, ordinal=ordinal)
                for ordinal, item in enumerate(command.attachments, start=1)
            ),
            explicit_references=tuple(
                AdmissionFileReference(
                    file_id=item.file_id,
                    version_id=item.version_id,
                    auto_materialize=item.auto_materialize,
                )
                for item in command.file_references
            ),
            quoted_external_message_id=command.quoted_external_message_id,
            candidates=self._workspace_file_candidates(rows),
            retained_candidates=self._workspace_file_candidates(retained_rows),
            now=observed_at,
        )

    @staticmethod
    def _workspace_file_candidates(
        rows: list[dict[str, Any]],
    ) -> tuple[WorkspaceFileCandidate, ...]:
        return tuple(
            WorkspaceFileCandidate(
                file_id=str(row.get("file_id") or ""),
                version_id=str(row.get("version_id") or ""),
                display_name=str(row.get("display_name") or ""),
                attachment_id=str(row.get("attachment_id") or ""),
                message_external_id=str(row.get("message_external_id") or ""),
                source_status=str(row.get("source_status") or ""),
                readability_status=str(row.get("readability_status") or "NOT_REQUIRED"),
                error_code=str(row.get("error_code") or ""),
                source_ready_at=(
                    str(row["source_ready_at"]) if row.get("source_ready_at") else None
                ),
                source_received_at=(
                    str(row["source_received_at"]) if row.get("source_received_at") else None
                ),
                content_available=(
                    str(row.get("file_status") or "ACTIVE") == "ACTIVE"
                    and str(row.get("version_status") or "AVAILABLE") in {"AVAILABLE", "CONFLICT"}
                ),
            )
            for row in rows
        )

    def _persist_system_notice(
        self,
        *,
        command: CreateAgentJobCommand,
        session: AgentSession,
        workspace_id: str,
        reply_route: dict[str, Any],
        file_plan: FileAdmissionPlan,
        correlation_id: str,
        requester_id: str,
    ) -> SystemNoticeIntake:
        gate = file_plan.gate
        names = file_plan.notice_names
        title, markdown = render_file_admission_notice(
            notice_kind=gate.notice_kind or "pending",
            display_names=names,
        )
        message_id = self.session_repository.add_message(
            session_id=session.id,
            job_id=None,
            role="user",
            content=command.user_message,
            external_message_id=(command.external_message_id or command.external_event_id),
            sender_id=requester_id,
            sender_display_name=command.requester_display_name,
            message_type="text",
            content_status="READY",
            quoted_external_message_id=command.quoted_external_message_id,
            safe_metadata={"file_turn_admission": gate.reason_code},
        )
        delivery_id = ""
        if self.delivery_service is not None:
            delivery_id = self.delivery_service.enqueue_system_notice(
                idempotency_key=command.idempotency_key,
                session_id=session.id,
                reply_route=reply_route or session.reply_route or {"type": "none"},
                title=title,
                markdown=markdown,
                reason_code=gate.reason_code,
                correlation_id=correlation_id,
                application_publication_id=command.business_application_publication_id,
                principal_user_id=requester_id,
                agent_publication_id=command.fixed_agent_publication_id,
                notice_kind=gate.notice_kind,
                user_message_id=message_id,
                task_workspace_id=workspace_id,
            )
        version_ids = tuple(item.version_id for item in gate.dependencies if item.version_id)
        if workspace_id and gate.reason_code == "file_readable_content_not_ready" and version_ids:
            self.attachment_repository.record_file_readiness_blocked_turn(
                session_id=session.id,
                workspace_id=workspace_id,
                user_message_id=message_id,
                reason_code=gate.reason_code,
                version_ids=version_ids,
                expires_at=(datetime.now(UTC) + timedelta(hours=24)).isoformat(),
            )
        self.audit_service.record(
            "file.turn.admission.blocked",
            status="SUCCEEDED",
            summary="File turn admission ended without an Agent job",
            actor_id=requester_id,
            payload={
                "session_id": session.id,
                "reason_code": gate.reason_code,
                "version_ids": [item.version_id for item in gate.dependencies if item.version_id],
                "delivery_id": delivery_id,
            },
        )
        return SystemNoticeIntake(
            session_id=session.id,
            message_id=message_id,
            delivery_id=delivery_id,
            reason_code=gate.reason_code,
            task_workspace_id=workspace_id,
        )

    def _validate_attachments(self, command: CreateAgentJobCommand) -> None:
        attachments = command.attachments
        enabled = (
            self.attachment_settings.enabled
            if command.attachments_enabled is None
            else command.attachments_enabled
        )
        if attachments and not enabled:
            raise NonRetryableExecutionError(
                "message_attachments_disabled",
                safe_message="此业务应用未启用附件",
            )
        if len(attachments) > self.attachment_settings.max_count:
            raise NonRetryableExecutionError(
                "attachment_count_exceeded", safe_message="附件数量过多"
            )
        profile = resolve_document_processing_profile(command.document_processing_profile_code)
        document_extensions = frozenset(
            extension
            for definition in (profile.source_formats if profile is not None else ())
            for extension in definition.extensions
        )
        total = 0
        for attachment in attachments:
            extension = Path(attachment.file_name).suffix.lower()
            if (
                extension not in self.attachment_settings.allowed_extensions
                and extension not in document_extensions
            ):
                raise NonRetryableExecutionError(
                    "unsupported_attachment_type", safe_message="不支持此附件类型"
                )
            if not attachment.source_credential:
                raise NonRetryableExecutionError(
                    "attachment_source_missing", safe_message="缺少附件来源"
                )
            size = int(attachment.declared_size or 0)
            is_workspace_text = is_task_text_name(attachment.file_name)
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

    def _continuous_conversation_enabled(self, command: CreateAgentJobCommand) -> bool:
        return (
            self.continuous_enabled
            if command.continuous_conversation_enabled is None
            else command.continuous_conversation_enabled
        )

    def _require_credential_cipher(self) -> AttachmentCredentialCipher:
        if self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "Attachment credential encryption is unavailable",
                safe_message="尚未配置附件处理能力",
            )
        return self.credential_cipher

    def _create_session(
        self,
        command: CreateAgentJobCommand,
        routing: _ChannelRouting,
        *,
        session_key: str,
        execution_scope_hash: str,
    ) -> AgentSession:
        return self.session_repository.create_session(
            project_code=routing.project_code,
            source_channel=routing.source_channel,
            source_connector_id=command.source_connector_id,
            external_conversation_id=routing.external_conversation_id,
            requester_id=routing.requester_id,
            requester_display_name=command.requester_display_name,
            routing_context=command.effective_routing_context,
            reply_route=routing.reply_route,
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
            session = self.session_repository.get_session(command.continue_session_id)
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


def _channel_session_key(
    command: CreateAgentJobCommand,
    routing: _ChannelRouting,
    execution_scope_hash: str,
) -> str:
    return _session_key(
        source_channel=routing.source_channel,
        connector_id=command.source_connector_id,
        project_code=routing.project_code,
        conversation_type=command.conversation_type,
        conversation_id=routing.external_conversation_id,
        requester_id=routing.requester_id,
        bot_identity=command.bot_identity,
        external_identity_id=command.external_identity_id,
        business_application_id=command.business_application_id,
        business_application_publication_id=command.business_application_publication_id,
        execution_scope_hash=execution_scope_hash,
        conversation_mode=command.conversation_mode,
    )


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
