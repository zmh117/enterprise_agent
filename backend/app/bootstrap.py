from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
import time
from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.conversation_context import ConversationContextService
from app.modules.agent.application.agent_executor import AgentExecutor
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.infrastructure.stub_runtime_client import StubAgentRuntimeClient
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.routed_runtime_client import (
    AgentRuntimeClient,
    RuntimeClientRegistry,
)
from app.modules.agent.infrastructure.runtime_readiness import AgentRuntimeReadinessGuard
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.agent.infrastructure.typescript_runtime_client import (
    AgentRuntimeHttpClient,
    RuntimeClientSettings,
    RuntimeGrantIssuer,
)
from app.modules.agent_config.application import AgentConfigService
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center import (
    AuthorizationCenterRepository,
    AuthorizationCenterService,
    BusinessAuthorizationService,
)
from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.attachments.dingtalk_downloader import DingTalkMediaDownloader
from app.modules.attachments.domain import ObjectStorage
from app.modules.attachments.extraction import SafeAttachmentExtractor
from app.modules.attachments.file_service_client import FileServiceAttachmentImporter
from app.modules.attachments.service import AttachmentProcessingService
from app.modules.attachments.storage import InMemoryObjectStorage
from app.modules.business_application.application import (
    BusinessApplicationResolver,
    BusinessApplicationService,
)
from app.modules.business_application.domain import RuntimeReadinessEvaluator
from app.modules.business_application.infrastructure import BusinessApplicationRepository
from app.modules.business_application.infrastructure.adapters import (
    AgentPublicationAdapter,
    ChannelConnectorAdapter,
    IdentitySubjectAdapter,
    WorkflowPublicationAdapter,
)
from app.modules.channel.application.channel_ingress_service import ChannelIngressService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.delivery.application.report_chunker import ReportChunker
from app.modules.delivery.application.delivery_dispatch_service import (
    DeliveryOutboxDispatcher,
)
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.delivery.infrastructure.adapters import (
    DingTalkConversationDeliveryAdapter,
    DingTalkEnterpriseAppDeliveryAdapter,
    DingTalkStreamSessionWebhookDeliveryAdapter,
    DingTalkStreamSessionRejectionNotifier,
    DingTalkWebhookRobotDeliveryAdapter,
    HttpDeliveryAdapter,
    NoneDeliveryAdapter,
)
from app.modules.delivery.infrastructure.file_delivery_sender import (
    DingTalkFileDeliverySender,
    FileServiceDeliveryClient,
)
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
from app.modules.file_workspace.manifest_service import JobFileManifestService
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.workspace_service import TaskWorkspaceService
from app.modules.dingding.application.dingding_message_service import DingTalkMessageService
from app.modules.dingding.application.dingtalk_stream_service import (
    DingTalkStreamMessageService,
)
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.modules.mcp_tool_runtime.service import ReadOnlyToolService
from app.modules.mcp_tool_runtime.contracts import (
    FakeReadOnlyToolExecutor,
    ReadOnlyToolExecutor,
)
from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.resource_resolver import DirectResourceResolver
from app.modules.identity.application import (
    AuthService,
    AuthorizationEvaluator,
    IdentityAdminService,
    IdentityService,
    PrincipalSigningKey,
    PrincipalTokenIssuer,
    ServicePrincipalTokenClient,
    ServicePrincipalTokenIssuer,
)
from app.modules.identity.application.ones_identity_binding import (
    OnesIdentityBindingService,
)
from app.modules.identity.infrastructure import (
    ExternalIdentityCredentialCipher,
    ExternalIdentityCredentialRepository,
    IdentityRepository,
    OnesIdentityChallengeRepository,
    UrllibOnesIdentityVerifier,
)
from app.modules.identity_discovery import (
    DingTalkIdentityDiscoveryRepository,
    DingTalkIdentityDiscoveryService,
)
from app.modules.job.application.create_agent_job_service import CreateAgentJobService
from app.modules.job.application.debug_job_access_service import DebugJobAccessService
from app.modules.job.application.job_dispatch_service import JobDispatchOutboxDispatcher
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.modules.job.application.job_retry_service import JobRetryService
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.infrastructure.repositories import (
    AgentRepository,
    AuditRepository,
    ConfigurationRepository,
)
from app.modules.job.infrastructure.execution_audit_repository import (
    ExecutionAuditRepository,
)
from app.modules.message_bus.application.message_publisher import MessageConsumer, MessagePublisher
from app.modules.message_bus.infrastructure.in_memory_bus import InMemoryMessageBus
from app.modules.message_bus.infrastructure.rabbitmq_consumer import RabbitMQConsumer
from app.modules.message_bus.infrastructure.rabbitmq_publisher import RabbitMQPublisher
from app.modules.managed_channel import (
    ChannelDispatchService,
    ChannelOutboxPublisher,
    ManagedChannelRepository,
    ManagedChannelService,
    ManagedWebhookProviderAdapter,
    RuntimeControlService,
)
from app.modules.managed_channel.application.service import (
    UnavailableChannelCredentialCipher,
)
from app.modules.model_connection import (
    ModelConnectionRepository,
    ModelConnectionService,
    RuntimeModelProbeClient,
    RuntimeModelProbeSettings,
    UnavailableModelSecretProvider,
)
from app.modules.permission.application.permission_service import PermissionService
from app.modules.platform_config.application import PlatformConfigService
from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.runtime_config_loader import load_settings_with_db_overlay
from app.modules.workflow.application import WorkflowService
from app.modules.workflow.infrastructure import WorkflowRepository
from app.modules.webhook.application import (
    TriggerValidator,
    WebhookAuthenticator,
    WebhookDispatcher,
    WebhookIngressService,
    WebhookMapper,
    WebhookOutboxPublisher,
    WebhookTriggerService,
)
from app.modules.webhook.infrastructure import (
    WebhookEventRepository,
    WebhookTriggerRepository,
)


@dataclass
class Container:
    settings: Settings
    database: Database
    agent_repository: AgentRepository
    identity_repository: IdentityRepository
    identity_service: IdentityService
    ones_identity_binding_service: OnesIdentityBindingService
    external_identity_credential_repository: ExternalIdentityCredentialRepository | None
    principal_token_issuer: PrincipalTokenIssuer | None
    identity_discovery_repository: DingTalkIdentityDiscoveryRepository
    identity_discovery_service: DingTalkIdentityDiscoveryService
    identity_admin_service: IdentityAdminService
    auth_service: AuthService
    authorization_evaluator: AuthorizationEvaluator
    authorization_center_repository: AuthorizationCenterRepository
    authorization_center_service: AuthorizationCenterService
    business_authorization_service: BusinessAuthorizationService
    agent_config_service: AgentConfigService
    model_connection_service: ModelConnectionService
    audit_service: AuditService
    audit_repository: AuditRepository
    permission_service: PermissionService
    publisher: MessagePublisher
    consumer: MessageConsumer | None
    message_bus: InMemoryMessageBus | None
    tool_executor: ReadOnlyToolExecutor
    tool_service: ReadOnlyToolService
    connector_registry: ConnectorRegistry
    platform_config_service: PlatformConfigService
    workflow_service: WorkflowService
    business_application_repository: BusinessApplicationRepository
    business_application_service: BusinessApplicationService
    business_application_resolver: BusinessApplicationResolver
    debug_job_access_service: DebugJobAccessService
    channel_ingress_service: ChannelIngressService
    create_agent_job_service: CreateAgentJobService
    job_dispatcher: JobDispatchOutboxDispatcher
    mcp_tool_snapshot_service: JobMcpToolSnapshotService
    dingtalk_message_service: DingTalkMessageService
    dingtalk_stream_message_service: DingTalkStreamMessageService
    result_delivery_service: ResultDeliveryService
    delivery_dispatcher: DeliveryOutboxDispatcher
    agent_executor: AgentExecutor
    retry_service: JobRetryService
    object_storage: ObjectStorage
    attachment_service: AttachmentProcessingService | None
    webhook_trigger_repository: WebhookTriggerRepository
    webhook_event_repository: WebhookEventRepository
    webhook_trigger_service: WebhookTriggerService
    webhook_ingress_service: WebhookIngressService
    webhook_outbox_publisher: WebhookOutboxPublisher
    webhook_dispatcher: WebhookDispatcher
    managed_channel_repository: ManagedChannelRepository
    managed_channel_service: ManagedChannelService
    runtime_control_service: RuntimeControlService
    channel_outbox_publisher: ChannelOutboxPublisher
    channel_dispatch_service: ChannelDispatchService
    service_principal_token_issuer: ServicePrincipalTokenIssuer | None = None


ContainerFactory = Callable[[Settings], Container]
PermissionServiceFactory = Callable[
    [ConfigurationRepository, AuthorizationEvaluator],
    PermissionService,
]


def build_api_container(settings: Settings, *, seed: bool = False) -> Container:
    settings = load_settings_with_db_overlay(settings, service_name="api-server")
    publisher = RabbitMQPublisher(settings.rabbitmq_url, settings.queue)
    return _build_container(
        settings=settings,
        service_name="api-server",
        publisher=publisher,
        consumer=None,
        message_bus=None,
        seed=seed,
        use_real_claude=settings.feature_configuration.real_claude_enabled,
    )


def build_worker_container(
    settings: Settings,
    *,
    seed: bool = False,
    service_name: str = "agent-worker",
    runtime_clients: Mapping[str, AgentRuntimeClient] | None = None,
) -> Container:
    settings = load_settings_with_db_overlay(settings, service_name=service_name)
    publisher = RabbitMQPublisher(settings.rabbitmq_url, settings.queue)
    consumer = RabbitMQConsumer(
        settings.rabbitmq_url,
        settings.queue,
        heartbeat_seconds=max(
            settings.queue.consumer_heartbeat_seconds,
            settings.execution.timeout_seconds + 60,
        ),
    )
    return _build_container(
        settings=settings,
        service_name=service_name,
        publisher=publisher,
        consumer=consumer,
        message_bus=None,
        seed=seed,
        use_real_claude=settings.feature_configuration.real_claude_enabled,
        runtime_clients_override=runtime_clients,
    )


def build_test_container(
    settings: Settings,
    *,
    migrate: bool = True,
    seed: bool = False,
    configure_seed_secrets: bool = True,
    service_name: str = "test-runtime",
    permission_service_factory: PermissionServiceFactory | None = None,
) -> Container:
    database = Database(settings.database_dsn)
    try:
        if migrate:
            Migrator(
                database,
                default_migrations_dir(),
                migrator_build="test-runtime",
            ).run()
        settings = load_settings_with_db_overlay(
            settings,
            service_name=("api-server" if service_name == "test-runtime" else service_name),
            database=database,
        )
    except Exception:
        database.close()
        raise
    message_bus = InMemoryMessageBus()

    runtime = _build_container(
        settings=settings,
        service_name=service_name,
        publisher=message_bus,
        consumer=message_bus,
        message_bus=message_bus,
        database=database,
        seed=seed,
        use_real_claude=False,
        permission_service_factory=permission_service_factory,
    )
    if seed and configure_seed_secrets:
        _configure_test_seed_secrets(runtime)
    return runtime


def build_container(
    settings: Settings,
    *,
    migrate: bool = True,
    seed: bool = False,
    configure_seed_secrets: bool = True,
) -> Container:
    return build_test_container(
        settings,
        migrate=migrate,
        seed=seed,
        configure_seed_secrets=configure_seed_secrets,
    )


def _configure_test_seed_secrets(runtime: Container) -> None:
    if not runtime.settings.app_config_master_key:
        return
    for code, value in (
        ("dingtalk_client_id", "test-dingtalk-client-id"),
        ("dingtalk_client_secret", "test-dingtalk-client-secret"),
        (
            "dingtalk_webhook_robot_secret",
            "test-dingtalk-webhook-robot-secret",
        ),
        (
            "dingtalk_webhook_robot_url",
            "https://oapi.dingtalk.com/robot/send?access_token=test-only",
        ),
        (
            "grafana_webhook_token",
            "test-grafana-token-0123456789abcdefABCDEF",
        ),
    ):
        runtime.platform_config_service.secret_provider.create_secret(
            code=code,
            value=value,
            actor_id="test-fixture",
        )
    runtime.database.execute("delete from platform_secret_change_event")


def _runtime_model_probe_for_service(
    settings: Settings,
    service_name: str,
) -> RuntimeModelProbeClient | None:
    return _runtime_model_probes_for_service(settings, service_name).get("python-v1")


def _runtime_model_probes_for_service(
    settings: Settings,
    service_name: str,
) -> dict[str, RuntimeModelProbeClient]:
    # This bearer credential belongs to the control-plane probe only. The
    # worker resolves execution grants independently and must never receive it.
    if service_name != "api-server":
        return {}
    token_file = settings.agent_runtime.model_probe_auth_token_file
    if not token_file:
        return {}
    runtime_settings = (
        (
            "python-v1",
            settings.agent_runtime.python_base_url,
            settings.agent_runtime.python_allowed_hosts,
        ),
        (
            "typescript-v1",
            settings.agent_runtime.typescript_base_url,
            settings.agent_runtime.typescript_allowed_hosts,
        ),
    )
    return {
        runtime_kind: RuntimeModelProbeClient(
            RuntimeModelProbeSettings(
                base_url=base_url,
                allowed_hosts=allowed_hosts,
                auth_token_file=token_file,
                master_key=settings.app_config_master_key,
                allow_insecure_internal_http=(settings.agent_runtime.allow_insecure_internal_http),
                runtime_kind=runtime_kind,
            )
        )
        for runtime_kind, base_url, allowed_hosts in runtime_settings
        if base_url
    }


def _acceptance_after_runtime_result_hook(
    environment: str,
) -> Callable[[], None] | None:
    raw = os.getenv("AGENT_RUNTIME_ACCEPTANCE_AFTER_RESULT_PAUSE_SECONDS", "").strip()
    if not raw or raw == "0":
        return None
    if environment not in {"test", "testing"}:
        raise RuntimeError("AGENT_RUNTIME_ACCEPTANCE_AFTER_RESULT_PAUSE_SECONDS is test-only")
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise RuntimeError("Agent Runtime acceptance pause must be numeric") from exc
    if seconds < 1 or seconds > 60:
        raise RuntimeError("Agent Runtime acceptance pause must be between 1 and 60 seconds")
    return lambda: time.sleep(seconds)


def _build_container(
    *,
    settings: Settings,
    service_name: str,
    publisher: MessagePublisher,
    consumer: MessageConsumer | None,
    message_bus: InMemoryMessageBus | None,
    database: Database | None = None,
    seed: bool,
    use_real_claude: bool,
    permission_service_factory: PermissionServiceFactory | None = None,
    runtime_clients_override: Mapping[str, AgentRuntimeClient] | None = None,
) -> Container:
    database = database or Database(settings.database_dsn)
    if seed:
        seed_path = default_migrations_dir().parent / "seeds" / "local_seed.sql"
        database.execute_script(seed_path.read_text())

    agent_repository = AgentRepository(database)
    audit_repository = AuditRepository(database)
    config_repository = ConfigurationRepository(database)
    identity_repository = IdentityRepository(database)
    platform_config_repository = PlatformConfigRepository(database)
    agent_config_repository = AgentConfigRepository(database)
    model_connection_repository = ModelConnectionRepository(database)
    workflow_repository = WorkflowRepository(database)
    business_application_repository = BusinessApplicationRepository(database)
    webhook_trigger_repository = WebhookTriggerRepository(database)
    webhook_event_repository = WebhookEventRepository(database)
    managed_channel_repository = ManagedChannelRepository(database)
    identity_discovery_repository = DingTalkIdentityDiscoveryRepository(database)
    audit_service = AuditService(
        audit_repository,
        max_chars=settings.execution.max_tool_response_chars,
    )
    model_secret_provider = (
        EncryptedDbSecretProvider(
            platform_config_repository,
            master_key=settings.app_config_master_key,
        )
        if settings.app_config_master_key
        else UnavailableModelSecretProvider()
    )
    connector_registry = ConnectorRegistry(
        config_repository,
        reference_resolver=model_secret_provider.resolve,
    )
    external_identity_credential_cipher = (
        ExternalIdentityCredentialCipher(settings.app_config_master_key)
        if settings.app_config_master_key
        else None
    )
    external_identity_credential_repository = (
        ExternalIdentityCredentialRepository(
            database,
            external_identity_credential_cipher,
        )
        if external_identity_credential_cipher is not None
        else None
    )
    identity_service = IdentityService(
        identity_repository,
        audit_service,
        connector_registry,
        credential_repository=external_identity_credential_repository,
    )
    ones_identity_binding_service = OnesIdentityBindingService(
        identity_repository=identity_repository,
        challenge_repository=OnesIdentityChallengeRepository(
            database,
            external_identity_credential_cipher,
        ),
        credential_repository=external_identity_credential_repository,
        verifier=UrllibOnesIdentityVerifier(
            settings.ones_identity,
            environment=settings.environment,
        ),
        audit_service=audit_service,
        instance_code=settings.ones_identity.instance_code,
        display_name=settings.ones_identity.display_name,
        challenge_ttl_seconds=settings.ones_identity.challenge_ttl_seconds,
    )
    authorization_evaluator = AuthorizationEvaluator(identity_repository, audit_service)
    authorization_center_repository = AuthorizationCenterRepository(database)
    authorization_center_service = AuthorizationCenterService(
        authorization_center_repository,
        identity_repository,
        authorization_evaluator,
        audit_service,
    )
    business_authorization_service = BusinessAuthorizationService(
        authorization_center_repository,
        identity_repository,
        audit_service=audit_service,
    )
    identity_discovery_service = DingTalkIdentityDiscoveryService(
        store=identity_discovery_repository,
        database=database,
        identity_repository=identity_repository,
        identity_service=identity_service,
        audit_service=audit_service,
        authorization=authorization_evaluator,
        authorization_repository=authorization_center_repository,
    )
    permission_service = (
        permission_service_factory(
            config_repository,
            authorization_evaluator,
        )
        if permission_service_factory is not None
        else PermissionService(
            config_repository,
            authorization_evaluator=authorization_evaluator,
        )
    )
    auth_service = AuthService(
        identity_repository,
        audit_service,
        settings.identity,
    )
    identity_admin_service = IdentityAdminService(
        identity_repository,
        identity_service,
        authorization_evaluator,
        audit_service,
    )
    platform_config_service = PlatformConfigService(
        platform_config_repository,
        permission_service,
        model_secret_provider,
        environment=settings.environment,
    )
    model_connection_service = ModelConnectionService(
        model_connection_repository,
        platform_config_repository,
        model_secret_provider,
        authorization_evaluator,
        audit_service,
        allowed_hosts=set(settings.model_provider_host_allowlist),
        runtime_probes=_runtime_model_probes_for_service(settings, service_name),
    )
    model_connection_service.ensure_default_connection(
        config={
            "protocol": "anthropic_compatible",
            "base_url": settings.anthropic_base_url or "https://api.deepseek.com/anthropic",
            "model": settings.claude_model,
            "default_opus_model": os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL", settings.claude_model),
            "default_sonnet_model": os.getenv(
                "ANTHROPIC_DEFAULT_SONNET_MODEL", settings.claude_model
            ),
            "default_haiku_model": os.getenv(
                "ANTHROPIC_DEFAULT_HAIKU_MODEL", settings.claude_model
            ),
            "subagent_model": os.getenv("CLAUDE_CODE_SUBAGENT_MODEL", settings.claude_model),
            "effort_level": os.getenv("CLAUDE_CODE_EFFORT_LEVEL", "max"),
        }
    )
    agent_config_service = AgentConfigService(
        agent_config_repository,
        authorization_evaluator,
        audit_service,
        SkillLoader(),
        model_connection_service=model_connection_service,
        allowed_models={settings.claude_model},
    )
    workflow_service = WorkflowService(
        workflow_repository,
        permission_service,
    )
    business_application_runtime_evaluator = RuntimeReadinessEvaluator(
        data_plane_enabled=(settings.feature_configuration.published_agent_runtime_enabled),
        runtime_environment="local",
    )
    agent_runtime_readiness_guard = AgentRuntimeReadinessGuard.from_settings(settings)
    business_application_service = BusinessApplicationService(
        business_application_repository,
        authorization_evaluator,
        audit_service,
        AgentPublicationAdapter(agent_config_repository),
        WorkflowPublicationAdapter(workflow_repository),
        ChannelConnectorAdapter(connector_registry),
        IdentitySubjectAdapter(identity_repository),
        business_application_runtime_evaluator,
        runtime_readiness_guard=agent_runtime_readiness_guard,
    )
    business_application_resolver = BusinessApplicationResolver(
        business_application_repository,
        business_application_runtime_evaluator,
    )
    credential_cipher = (
        AttachmentCredentialCipher(settings.app_config_master_key)
        if settings.app_config_master_key
        else None
    )
    mcp_tool_snapshot_service = JobMcpToolSnapshotService(
        database,
    )
    file_workspace_repository = FileWorkspaceRepository(database)
    file_manifest_service = JobFileManifestService(
        file_workspace_repository,
        TaskWorkspaceService(file_workspace_repository),
    )
    principal_token_issuer: PrincipalTokenIssuer | None = None
    if service_name == "agent-worker" and runtime_clients_override is None:
        principal_token_issuer = PrincipalTokenIssuer(
            database,
            mcp_tool_snapshot_service,
            business_authorization_service,
            PrincipalSigningKey.from_file(
                settings.principal_jwt.signing_private_key_file,
                environment=settings.environment,
            ),
            audit_service,
            ttl_seconds=settings.principal_jwt.ttl_seconds,
        )
    service_principal_token_issuer: ServicePrincipalTokenIssuer | None = None
    if service_name == "api-server" and settings.service_principal.enabled:
        service_principal_token_issuer = ServicePrincipalTokenIssuer.from_files(
            signing_private_key_file=(
                settings.principal_jwt.signing_private_key_file
            ),
            file_worker_bootstrap_file=(
                settings.service_principal.file_worker_bootstrap_token_file
            ),
            delivery_worker_bootstrap_file=(
                settings.service_principal.delivery_worker_bootstrap_token_file
            ),
            audit_service=audit_service,
            environment=settings.environment,
            ttl_seconds=settings.service_principal.ttl_seconds,
        )
    create_job_service = CreateAgentJobService(
        repository=agent_repository,
        permission_service=permission_service,
        audit_service=audit_service,
        publisher=publisher,
        queue_settings=settings.queue,
        execution_settings=settings.execution,
        connector_registry=connector_registry,
        credential_cipher=credential_cipher,
        continuous_enabled=settings.conversation.enabled,
        attachment_settings=settings.attachments,
        agent_config_service=agent_config_service,
        published_agent_runtime_enabled=(
            settings.feature_configuration.published_agent_runtime_enabled
        ),
        default_agent_code=settings.identity.default_agent_code,
        business_authorization_service=business_authorization_service,
        identity_repository=identity_repository,
        mcp_tool_snapshot_service=mcp_tool_snapshot_service,
        runtime_readiness_guard=agent_runtime_readiness_guard,
        file_manifest_service=file_manifest_service,
    )
    job_dispatcher = JobDispatchOutboxDispatcher(
        repository=agent_repository,
        publisher=publisher,
        audit_service=audit_service,
        settings=settings.queue,
        worker_id=f"{service_name}-job-dispatch-outbox",
        mcp_tool_snapshot_service=mcp_tool_snapshot_service,
    )
    debug_job_access_service = DebugJobAccessService(
        database=database,
        agent_repository=agent_repository,
        identity_repository=identity_repository,
        authorization_center_repository=authorization_center_repository,
        authorization_evaluator=authorization_evaluator,
        create_job_service=create_job_service,
    )
    channel_ingress_service = ChannelIngressService(
        create_job_service=create_job_service,
        audit_service=audit_service,
        identity_service=(
            identity_service if settings.feature_configuration.unified_identity_enabled else None
        ),
        unified_identity_enabled=(settings.feature_configuration.unified_identity_enabled),
        business_application_resolver=(
            business_application_resolver
            if settings.feature_configuration.published_agent_runtime_enabled
            else None
        ),
        runtime_environment="local",
    )
    webhook_mapper = WebhookMapper(
        max_message_chars=settings.webhooks.max_message_chars,
        max_summary_chars=settings.webhooks.max_summary_chars,
    )
    webhook_validator = TriggerValidator(
        repository=webhook_trigger_repository,
        identity_repository=identity_repository,
        connector_registry=connector_registry,
        agent_config_service=agent_config_service,
    )
    webhook_trigger_service = WebhookTriggerService(
        repository=webhook_trigger_repository,
        identity_repository=identity_repository,
        authorization=authorization_evaluator,
        audit_service=audit_service,
        validator=webhook_validator,
        mapper=webhook_mapper,
    )
    webhook_ingress_service = WebhookIngressService(
        trigger_repository=webhook_trigger_repository,
        event_repository=webhook_event_repository,
        authenticator=WebhookAuthenticator(
            connector_registry=connector_registry,
        ),
        connector_registry=connector_registry,
        mapper=webhook_mapper,
        audit_service=audit_service,
        settings=settings.webhooks,
    )
    webhook_outbox_publisher = WebhookOutboxPublisher(
        repository=webhook_event_repository,
        publisher=publisher,
        audit_service=audit_service,
        settings=settings.webhooks,
    )
    webhook_dispatcher = WebhookDispatcher(
        event_repository=webhook_event_repository,
        trigger_repository=webhook_trigger_repository,
        identity_repository=identity_repository,
        agent_config_service=agent_config_service,
        channel_ingress_service=channel_ingress_service,
        audit_service=audit_service,
    )
    dingtalk_service = DingTalkMessageService(
        secret=settings.dingtalk.secret,
        channel_ingress_service=channel_ingress_service,
        callback_client=DingTalkCallbackClient(
            callback_url=settings.dingtalk.callback_url,
            host_allowlist=settings.dingtalk.callback_host_allowlist,
        ),
        default_delivery_type=settings.dingtalk.default_delivery_type,
        default_delivery_connector_id=settings.dingtalk.default_delivery_connector_id,
        default_source_connector_id=settings.dingtalk.default_source_connector_id,
        default_project_code=settings.dingtalk.default_project_code,
        default_environment=settings.dingtalk.default_environment,
        default_base=settings.dingtalk.default_base,
        default_workshop=settings.dingtalk.default_workshop,
        default_service=settings.dingtalk.default_service,
        default_open_conversation_id=settings.dingtalk.default_open_conversation_id,
        default_robot_code=settings.dingtalk.default_robot_code,
    )
    dingtalk_stream_session_webhook_adapter = DingTalkStreamSessionWebhookDeliveryAdapter(
        timeout_seconds=settings.delivery.timeout_seconds,
    )
    dingtalk_stream_service = DingTalkStreamMessageService(
        channel_ingress_service=channel_ingress_service,
        audit_service=audit_service,
        default_delivery_type=settings.dingtalk.default_delivery_type,
        default_delivery_connector_id=settings.dingtalk.default_delivery_connector_id,
        default_source_connector_id=settings.dingtalk.stream_connector_id,
        default_project_code=settings.dingtalk.default_project_code,
        default_environment=settings.dingtalk.default_environment,
        default_base=settings.dingtalk.default_base,
        default_workshop=settings.dingtalk.default_workshop,
        default_service=settings.dingtalk.default_service,
        default_open_conversation_id=settings.dingtalk.default_open_conversation_id,
        default_robot_code=settings.dingtalk.default_robot_code,
        attachments_enabled=credential_cipher is not None,
        attachment_credential_ttl_seconds=settings.attachments.credential_ttl_seconds,
        connector_registry=connector_registry,
        default_tenant_code=settings.identity.dingtalk_tenant_code,
        rejection_notifier=DingTalkStreamSessionRejectionNotifier(
            dingtalk_stream_session_webhook_adapter
        ),
        identity_discovery_service=identity_discovery_service,
        enterprise_connector_resolver=managed_channel_repository.get_connector,
    )
    channel_credential_cipher = (
        AttachmentCredentialCipher(settings.app_config_master_key)
        if settings.app_config_master_key
        else UnavailableChannelCredentialCipher()
    )
    managed_channel_service = ManagedChannelService(
        repository=managed_channel_repository,
        webhook_provider=ManagedWebhookProviderAdapter(
            repository=webhook_trigger_repository,
            service=webhook_trigger_service,
            connector_registry=connector_registry,
        ),
        secret_provider=model_secret_provider,
        connector_registry=connector_registry,
        audit_service=audit_service,
        stale_seconds=settings.managed_channels.stale_seconds,
    )
    runtime_control_service = RuntimeControlService(
        repository=managed_channel_repository,
        secret_resolver=connector_registry.resolve_reference,
        credential_cipher=channel_credential_cipher,
        audit_service=audit_service,
        max_event_bytes=settings.managed_channels.max_event_bytes,
        lease_ttl_seconds=settings.managed_channels.lease_ttl_seconds,
    )
    channel_outbox_publisher = ChannelOutboxPublisher(
        repository=managed_channel_repository,
        publisher=publisher,
        max_attempts=settings.managed_channels.outbox_max_attempts,
        retry_base_seconds=settings.managed_channels.outbox_retry_base_seconds,
    )
    channel_dispatch_service = ChannelDispatchService(
        repository=managed_channel_repository,
        stream_service=dingtalk_stream_service,
        credential_cipher=channel_credential_cipher,
        identity_discovery_service=identity_discovery_service,
    )
    tool_executor: ReadOnlyToolExecutor = FakeReadOnlyToolExecutor()
    if service_name == "tool-mcp":
        tool_executor = DirectReadOnlyToolExecutor(
            DirectResourceResolver(
                database,
                secret_provider=EncryptedDbSecretProvider(
                    platform_config_repository,
                    master_key=settings.app_config_master_key,
                ),
            ),
            limits=settings.execution,
        )
    tool_service = ReadOnlyToolService(
        tool_executor=tool_executor,
        permission_service=permission_service,
        audit_service=audit_service,
        repository=agent_repository,
        limits=settings.execution,
        business_authorization_service=business_authorization_service,
        mcp_tool_snapshot_service=mcp_tool_snapshot_service,
    )
    tool_registry = ToolRegistry(tool_service)
    runtime_clients: dict[str, AgentRuntimeClient] = {}
    if service_name == "agent-worker" and runtime_clients_override is not None:
        runtime_clients = dict(runtime_clients_override)
    elif service_name == "agent-worker":
        grant_issuer = RuntimeGrantIssuer.from_file(settings.agent_runtime.grant_private_key_file)
        configured_runtimes = (
            (
                "python-v1",
                settings.agent_runtime.python_base_url,
                settings.agent_runtime.python_allowed_hosts,
            ),
            (
                "typescript-v1",
                settings.agent_runtime.typescript_base_url,
                settings.agent_runtime.typescript_allowed_hosts,
            ),
        )
        for runtime_kind, base_url, allowed_hosts in configured_runtimes:
            if not base_url:
                continue
            runtime_clients[runtime_kind] = AgentRuntimeHttpClient(
                settings=RuntimeClientSettings(
                    base_url=base_url,
                    allowed_runtime_hosts=allowed_hosts,
                    runtime_kind=runtime_kind,
                    allow_insecure_internal_http=(
                        settings.agent_runtime.allow_insecure_internal_http
                    ),
                ),
                grant_issuer=grant_issuer,
                event_sink=ExecutionAuditRepository(database).record_runtime_event,
                principal_token_issuer=principal_token_issuer,
            )
    else:
        stub_runtime = StubAgentRuntimeClient()
        runtime_clients = {
            "python-v1": stub_runtime,
            "typescript-v1": stub_runtime,
        }
    claude_client = RuntimeClientRegistry(
        runtime_clients,
    )
    dingtalk_conversation_adapter = DingTalkConversationDeliveryAdapter(
        fallback_callback_url=settings.dingtalk.callback_url,
        host_allowlist=settings.dingtalk.callback_host_allowlist,
    )
    dingtalk_enterprise_adapter = DingTalkEnterpriseAppDeliveryAdapter(
        connector_registry=connector_registry,
        timeout_seconds=settings.delivery.timeout_seconds,
    )
    dingtalk_webhook_robot_adapter = DingTalkWebhookRobotDeliveryAdapter(
        connector_registry=connector_registry,
        timeout_seconds=settings.delivery.timeout_seconds,
    )
    http_adapter = HttpDeliveryAdapter(timeout_seconds=settings.delivery.timeout_seconds)
    result_delivery_service = ResultDeliveryService(
        repository=agent_repository,
        audit_service=audit_service,
        connector_registry=connector_registry,
        adapters={
            "none": NoneDeliveryAdapter(),
            "dingtalk_conversation": dingtalk_conversation_adapter,
            "dingtalk_stream_session_webhook": dingtalk_stream_session_webhook_adapter,
            "dingtalk_webhook_robot": dingtalk_webhook_robot_adapter,
            "dingtalk_enterprise_robot": dingtalk_enterprise_adapter,
            "email": http_adapter,
            "webhook": http_adapter,
        },
        chunker=ReportChunker(settings.delivery.chunk_max_chars),
        settings=settings.delivery,
        business_authorization_service=business_authorization_service,
    )
    file_version_delivery_service = FileVersionDeliveryService(
        file_workspace_repository,
        agent_repository,
        settings.delivery,
    )
    file_delivery_sender = None
    if service_name == "delivery-dispatch-worker":
        if not settings.service_principal.enabled:
            raise RuntimeError("Delivery Worker Service Principal is disabled")
        delivery_token_provider = ServicePrincipalTokenClient(
            base_url=settings.service_principal.identity_base_url,
            allowed_hosts=settings.service_principal.identity_allowed_hosts,
            bootstrap_credential_file=(
                settings.service_principal.delivery_worker_bootstrap_token_file
            ),
            timeout_seconds=settings.service_principal.timeout_seconds,
            refresh_skew_seconds=settings.service_principal.refresh_skew_seconds,
        )
        file_delivery_sender = DingTalkFileDeliverySender(
            file_service=FileServiceDeliveryClient(
                base_url=settings.file_service.internal_base_url,
                allowed_hosts=settings.file_service.internal_allowed_hosts,
                token_provider=delivery_token_provider,
                timeout_seconds=settings.file_service.internal_timeout_seconds,
            ),
            connector_registry=connector_registry,
            timeout_seconds=settings.delivery.timeout_seconds,
        )
    delivery_dispatcher = DeliveryOutboxDispatcher(
        repository=agent_repository,
        delivery_service=result_delivery_service,
        audit_service=audit_service,
        settings=settings.delivery,
        worker_id=f"{service_name}-delivery-dispatcher",
        file_delivery_sender=file_delivery_sender,
        file_delivery_service=file_version_delivery_service,
    )
    object_storage: ObjectStorage | None = InMemoryObjectStorage(settings.object_storage.bucket)
    attachment_importer = None
    if service_name == "file-worker" and message_bus is None:
        if not settings.service_principal.enabled:
            raise RuntimeError("File Worker Service Principal is disabled")
        object_storage = None
        file_worker_token_provider = ServicePrincipalTokenClient(
            base_url=settings.service_principal.identity_base_url,
            allowed_hosts=settings.service_principal.identity_allowed_hosts,
            bootstrap_credential_file=(settings.service_principal.file_worker_bootstrap_token_file),
            timeout_seconds=settings.service_principal.timeout_seconds,
            refresh_skew_seconds=settings.service_principal.refresh_skew_seconds,
        )
        attachment_importer = FileServiceAttachmentImporter(
            base_url=settings.file_service.internal_base_url,
            allowed_hosts=settings.file_service.internal_allowed_hosts,
            token_provider=file_worker_token_provider,
            timeout_seconds=settings.file_service.internal_timeout_seconds,
        )
    attachment_service: AttachmentProcessingService | None = None
    if credential_cipher is not None and (service_name == "file-worker" or message_bus is not None):

        def resolve_dingtalk_media_credentials(
            connector_id: str,
        ) -> tuple[str, str, str]:
            connector = connector_registry.require_dingtalk_stream_ingress(connector_id)
            return (
                connector_registry.resolve_metadata_reference(connector, "client_id_ref")
                or connector_registry.metadata_value(connector, "client_id"),
                connector_registry.resolve_secret(connector),
                connector_registry.metadata_value(connector, "default_robot_code"),
            )

        attachment_service = AttachmentProcessingService(
            repository=agent_repository,
            publisher=publisher,
            audit_service=audit_service,
            credential_cipher=credential_cipher,
            downloader=DingTalkMediaDownloader(
                credential_resolver=resolve_dingtalk_media_credentials,
                robot_code=settings.dingtalk.default_robot_code,
                timeout_seconds=settings.attachments.timeout_seconds,
            ),
            storage=object_storage,
            importer=attachment_importer,
            extractor=SafeAttachmentExtractor(settings.attachments),
            settings=settings.attachments,
            delivery_service=result_delivery_service,
            file_manifest_service=file_manifest_service,
        )
    agent_executor = AgentExecutor(
        repository=agent_repository,
        audit_service=audit_service,
        status_service=JobStatusService(agent_repository),
        context_builder=AgentContextBuilder(
            tool_registry=tool_registry,
            skill_loader=SkillLoader(),
            conversation_service=ConversationContextService(
                agent_repository, settings.conversation
            ),
            agent_config_service=agent_config_service,
            file_manifest_service=file_manifest_service,
        ),
        claude_client=claude_client,
        tool_registry=tool_registry,
        result_service=AgentResultService(agent_repository),
        delivery_service=result_delivery_service,
        business_authorization_service=business_authorization_service,
        mcp_tool_snapshot_service=mcp_tool_snapshot_service,
        after_runtime_result_hook=_acceptance_after_runtime_result_hook(settings.environment),
    )
    retry_service = JobRetryService(
        repository=agent_repository,
        queue_settings=settings.queue,
        audit_service=audit_service,
        delivery_service=result_delivery_service,
        mcp_tool_snapshot_service=mcp_tool_snapshot_service,
    )
    return Container(
        settings=settings,
        database=database,
        agent_repository=agent_repository,
        identity_repository=identity_repository,
        identity_service=identity_service,
        ones_identity_binding_service=ones_identity_binding_service,
        external_identity_credential_repository=external_identity_credential_repository,
        principal_token_issuer=principal_token_issuer,
        service_principal_token_issuer=service_principal_token_issuer,
        identity_discovery_repository=identity_discovery_repository,
        identity_discovery_service=identity_discovery_service,
        identity_admin_service=identity_admin_service,
        auth_service=auth_service,
        authorization_evaluator=authorization_evaluator,
        authorization_center_repository=authorization_center_repository,
        authorization_center_service=authorization_center_service,
        business_authorization_service=business_authorization_service,
        agent_config_service=agent_config_service,
        model_connection_service=model_connection_service,
        audit_service=audit_service,
        audit_repository=audit_repository,
        permission_service=permission_service,
        publisher=publisher,
        consumer=consumer,
        message_bus=message_bus,
        tool_executor=tool_executor,
        tool_service=tool_service,
        connector_registry=connector_registry,
        platform_config_service=platform_config_service,
        workflow_service=workflow_service,
        business_application_repository=business_application_repository,
        business_application_service=business_application_service,
        business_application_resolver=business_application_resolver,
        debug_job_access_service=debug_job_access_service,
        channel_ingress_service=channel_ingress_service,
        create_agent_job_service=create_job_service,
        job_dispatcher=job_dispatcher,
        mcp_tool_snapshot_service=mcp_tool_snapshot_service,
        dingtalk_message_service=dingtalk_service,
        dingtalk_stream_message_service=dingtalk_stream_service,
        result_delivery_service=result_delivery_service,
        delivery_dispatcher=delivery_dispatcher,
        agent_executor=agent_executor,
        retry_service=retry_service,
        object_storage=object_storage,
        attachment_service=attachment_service,
        webhook_trigger_repository=webhook_trigger_repository,
        webhook_event_repository=webhook_event_repository,
        webhook_trigger_service=webhook_trigger_service,
        webhook_ingress_service=webhook_ingress_service,
        webhook_outbox_publisher=webhook_outbox_publisher,
        webhook_dispatcher=webhook_dispatcher,
        managed_channel_repository=managed_channel_repository,
        managed_channel_service=managed_channel_service,
        runtime_control_service=runtime_control_service,
        channel_outbox_publisher=channel_outbox_publisher,
        channel_dispatch_service=channel_dispatch_service,
    )
