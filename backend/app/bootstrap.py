from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.conversation_context import ConversationContextService
from app.modules.agent.application.agent_executor import AgentExecutor
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.application.runtime_migration_gate import RuntimeMigrationGate
from app.modules.agent.infrastructure.claude_code_agent_client import (
    RealClaudeCodeAgentClient,
    StubClaudeCodeAgentClient,
)
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.agent.infrastructure.routed_runtime_client import RoutedAgentRuntimeClient
from app.modules.agent.infrastructure.typescript_runtime_client import (
    RuntimeClientSettings,
    RuntimeGrantIssuer,
    TypeScriptAgentRuntimeClient,
)
from app.modules.agent_config.application import AgentConfigService
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center import (
    AuthorizationCenterRepository,
    BusinessAuthorizationService,
)
from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.attachments.dingtalk_downloader import DingTalkMediaDownloader
from app.modules.attachments.domain import ObjectStorage
from app.modules.attachments.extraction import SafeAttachmentExtractor
from app.modules.attachments.service import AttachmentProcessingService
from app.modules.attachments.storage import InMemoryObjectStorage, S3ObjectStorage
from app.modules.business_application.application import (
    BusinessApplicationResolver,
    BusinessApplicationService,
)
from app.modules.business_application.domain import RuntimeReadinessEvaluator
from app.modules.business_application.infrastructure import BusinessApplicationRepository
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
from app.modules.dingding.application.dingding_message_service import DingTalkMessageService
from app.modules.dingding.application.dingtalk_stream_service import (
    DingTalkStreamMessageService,
)
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import DingTalkAccessTokenClient
from app.modules.identity.application import (
    AuthService,
    AuthorizationEvaluator,
    IdentityService,
)
from app.modules.identity.application.admin_service import IdentityAdminService
from app.modules.identity.application.external_credentials import (
    ExternalCredentialBindingService,
)
from app.modules.identity.infrastructure import (
    DingTalkBindingChallengeRepository,
    IdentityRepository,
    OnesProviderAuthenticator,
    ProviderCredentialCipher,
    ProviderCredentialRepository,
    ProviderInstanceRepository,
)
from app.modules.identity_discovery import (
    DingTalkIdentityDiscoveryRepository,
    DingTalkIdentityDiscoveryService,
)
from app.modules.identity.infrastructure.ones_identity_verifier import (
    UrllibOnesIdentityVerifier,
)
from app.modules.job.application.create_agent_job_service import CreateAgentJobService
from app.modules.job.application.job_dispatch_service import JobDispatchOutboxDispatcher
from app.modules.job.application.job_retry_service import JobRetryService
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.infrastructure.repositories import (
    AgentRepository,
    AuditRepository,
    ConfigurationRepository,
)
from app.modules.message_bus.application.message_publisher import MessageConsumer, MessagePublisher
from app.modules.mcp_runtime.bindings import McpJobBindingService
from app.modules.mcp_resources import McpResourceService
from app.modules.mcp_tool_publications import McpToolPublicationService
from app.modules.cutover import LegacyPlatformCutoverService
from services.mcp_common import McpTokenIssuer
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
    identity_admin_service: IdentityAdminService
    identity_discovery_repository: DingTalkIdentityDiscoveryRepository
    identity_discovery_service: DingTalkIdentityDiscoveryService
    auth_service: AuthService
    authorization_evaluator: AuthorizationEvaluator
    authorization_center_repository: AuthorizationCenterRepository
    business_authorization_service: BusinessAuthorizationService
    agent_config_service: AgentConfigService
    model_connection_service: ModelConnectionService
    external_credential_binding_service: ExternalCredentialBindingService
    audit_service: AuditService
    audit_repository: AuditRepository
    permission_service: PermissionService
    publisher: MessagePublisher
    consumer: MessageConsumer | None
    message_bus: InMemoryMessageBus | None
    connector_registry: ConnectorRegistry
    platform_config_service: PlatformConfigService
    business_application_repository: BusinessApplicationRepository
    business_application_resolver: BusinessApplicationResolver
    business_application_service: BusinessApplicationService
    channel_ingress_service: ChannelIngressService
    create_agent_job_service: CreateAgentJobService
    job_dispatcher: JobDispatchOutboxDispatcher
    mcp_resource_service: McpResourceService
    mcp_tool_publication_service: McpToolPublicationService
    cutover_service: LegacyPlatformCutoverService
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
    managed_channel_service: ManagedChannelService
    webhook_ingress_service: WebhookIngressService
    webhook_outbox_publisher: WebhookOutboxPublisher
    webhook_dispatcher: WebhookDispatcher
    managed_channel_repository: ManagedChannelRepository
    runtime_control_service: RuntimeControlService
    channel_outbox_publisher: ChannelOutboxPublisher
    channel_dispatch_service: ChannelDispatchService


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
    )


def build_test_container(
    settings: Settings,
    *,
    migrate: bool = True,
    seed: bool = False,
    configure_seed_secrets: bool = True,
) -> Container:
    from app.testing.permission_service import SeedPolicyTestPermissionService

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
            service_name="api-server",
            database=database,
        )
    except Exception:
        database.close()
        raise
    message_bus = InMemoryMessageBus()

    def test_permission_service_factory(
        repository: ConfigurationRepository,
        evaluator: AuthorizationEvaluator,
    ) -> PermissionService:
        return SeedPolicyTestPermissionService(
            repository,
            authorization_evaluator=evaluator,
            unified_enabled=(settings.feature_configuration.unified_identity_enabled),
        )

    runtime = _build_container(
        settings=settings,
        service_name="test-runtime",
        publisher=message_bus,
        consumer=message_bus,
        message_bus=message_bus,
        database=database,
        seed=seed,
        use_real_claude=False,
        permission_service_factory=test_permission_service_factory,
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


def _ensure_trusted_ones_for_service(
    repository: ProviderInstanceRepository,
    *,
    settings: Settings,
    service_name: str,
) -> None:
    if service_name not in {"api-server", "test-runtime"}:
        return
    repository.ensure_trusted_ones(
        code=settings.ones_identity.instance_code,
        display_name=settings.ones_identity.display_name,
        base_url=settings.ones_identity.base_url,
        allowed_hosts=settings.ones_identity.allowed_hosts,
    )


def _runtime_model_probe_for_service(
    settings: Settings,
    service_name: str,
) -> RuntimeModelProbeClient | None:
    # The model probe is a control-plane operation. Workers need model revision
    # metadata for execution, but must not receive the probe bearer token.
    if service_name != "api-server":
        return None
    if not (settings.agent_runtime.base_url and settings.agent_runtime.model_probe_auth_token_file):
        return None
    return RuntimeModelProbeClient(
        RuntimeModelProbeSettings(
            base_url=settings.agent_runtime.base_url,
            allowed_hosts=settings.agent_runtime.allowed_hosts,
            auth_token_file=settings.agent_runtime.model_probe_auth_token_file,
            allow_insecure_internal_http=(settings.agent_runtime.allow_insecure_internal_http),
        )
    )


def _ensure_default_model_connection_for_service(
    service: ModelConnectionService,
    settings: Settings,
    service_name: str,
) -> None:
    # Default configuration is control-plane bootstrap state. Runtime workers
    # consume immutable revisions and intentionally lack bootstrap/secret-table
    # privileges.
    if service_name not in {"api-server", "test-runtime"}:
        return
    service.ensure_default_connection(
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
    provider_instance_repository = ProviderInstanceRepository(database)
    provider_credential_repository = ProviderCredentialRepository(database)
    dingtalk_binding_challenge_repository = DingTalkBindingChallengeRepository(database)
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
    ones_identity_verifier = UrllibOnesIdentityVerifier(
        settings.ones_identity,
        environment=settings.environment,
    )
    _ensure_trusted_ones_for_service(
        provider_instance_repository,
        settings=settings,
        service_name=service_name,
    )
    identity_service = IdentityService(
        identity_repository,
        audit_service,
        connector_registry,
        ones_verifier=ones_identity_verifier,
        ones_instance_code=settings.ones_identity.instance_code,
        ones_display_name=settings.ones_identity.display_name,
    )
    authorization_evaluator = AuthorizationEvaluator(identity_repository, audit_service)
    identity_admin_service = IdentityAdminService(
        identity_repository,
        identity_service,
        authorization_evaluator,
        audit_service,
    )
    authorization_center_repository = AuthorizationCenterRepository(database)
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
    platform_config_service = PlatformConfigService(
        platform_config_repository,
        permission_service,
        model_secret_provider,
        environment=settings.environment,
    )
    runtime_model_probe = _runtime_model_probe_for_service(settings, service_name)
    model_connection_service = ModelConnectionService(
        model_connection_repository,
        platform_config_repository,
        model_secret_provider,
        authorization_evaluator,
        audit_service,
        allowed_hosts=set(settings.model_provider_host_allowlist),
        runtime_probe=runtime_model_probe,
    )
    external_credential_binding_service = ExternalCredentialBindingService(
        identity_repository=identity_repository,
        credential_repository=provider_credential_repository,
        provider_instances=provider_instance_repository,
        credential_cipher=(
            ProviderCredentialCipher(settings.app_config_master_key)
            if settings.app_config_master_key
            else None
        ),
        authenticator=OnesProviderAuthenticator(
            environment=settings.environment,
            timeout_seconds=settings.ones_identity.timeout_seconds,
            max_response_bytes=settings.ones_identity.max_response_bytes,
            allow_insecure_local=settings.ones_identity.allow_insecure_local,
        ),
        audit_service=audit_service,
        authorization=authorization_evaluator,
        provider_instance_code=settings.ones_identity.instance_code,
        dingtalk_challenges=dingtalk_binding_challenge_repository,
    )
    _ensure_default_model_connection_for_service(
        model_connection_service,
        settings,
        service_name,
    )
    mcp_tool_publication_service = McpToolPublicationService(database, audit_service=audit_service)
    agent_config_service = AgentConfigService(
        agent_config_repository,
        authorization_evaluator,
        audit_service,
        SkillLoader(),
        model_connection_service=model_connection_service,
        allowed_models={settings.claude_model},
        mcp_tool_publication_service=mcp_tool_publication_service,
    )
    business_application_runtime_evaluator = RuntimeReadinessEvaluator(
        data_plane_enabled=(settings.feature_configuration.published_agent_runtime_enabled),
        runtime_environment=settings.environment,
    )
    runtime_migration_gate = RuntimeMigrationGate(settings.agent_runtime)
    credential_cipher = (
        AttachmentCredentialCipher(settings.app_config_master_key)
        if settings.app_config_master_key
        else None
    )
    mcp_binding_service = McpJobBindingService(database)
    mcp_resource_service = McpResourceService(database, audit_service=audit_service)
    business_application_resolver = BusinessApplicationResolver(
        business_application_repository,
        business_application_runtime_evaluator,
        mcp_tool_publication_service,
    )
    business_application_service = BusinessApplicationService(
        business_application_repository,
        authorization_evaluator,
        audit_service,
        mcp_tool_publication_service,
        business_application_runtime_evaluator,
    )
    cutover_service = LegacyPlatformCutoverService(
        database,
        destructive_enabled=settings.destructive_cutover_enabled,
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
        mcp_binding_service=mcp_binding_service,
        identity_repository=identity_repository,
        accept_new_jobs=not settings.destructive_cutover_enabled,
    )
    job_dispatcher = JobDispatchOutboxDispatcher(
        repository=agent_repository,
        publisher=publisher,
        audit_service=audit_service,
        settings=settings.queue,
        worker_id=f"{service_name}-job-dispatch-outbox",
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
        runtime_migration_gate=runtime_migration_gate,
        runtime_environment=settings.environment,
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
        identity_binder=external_credential_binding_service,
    )
    channel_credential_cipher = (
        AttachmentCredentialCipher(settings.app_config_master_key)
        if settings.app_config_master_key
        else UnavailableChannelCredentialCipher()
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
    mcp_token_issuer = (
        McpTokenIssuer.from_file(settings.mcp.token_signing_key_file)
        if service_name == "agent-worker" and settings.mcp.token_signing_key_file
        else None
    )
    python_claude_client = (
        RealClaudeCodeAgentClient(
            model=settings.claude_model,
            limits=settings.execution,
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
            secret_resolver=model_secret_provider.resolve,
            mcp_token_issuer=mcp_token_issuer,
            ones_mcp_url=settings.mcp.ones_server_url,
            data_mcp_url=settings.mcp.data_server_url,
            allowed_mcp_server_codes=settings.mcp.allowed_server_codes,
        )
        if use_real_claude
        else StubClaudeCodeAgentClient()
    )
    typescript_runtime_client = None
    if service_name == "agent-worker" and settings.agent_runtime.base_url:
        if mcp_token_issuer is None:
            raise ValueError(
                "MCP_TOKEN_SIGNING_KEY_FILE is required when Agent Runtime is configured"
            )
        typescript_runtime_client = TypeScriptAgentRuntimeClient(
            settings=RuntimeClientSettings(
                base_url=settings.agent_runtime.base_url,
                ones_mcp_url=settings.mcp.ones_server_url,
                data_mcp_url=settings.mcp.data_server_url,
                allowed_runtime_hosts=settings.agent_runtime.allowed_hosts,
                allowed_mcp_server_codes=settings.mcp.allowed_server_codes,
                allow_insecure_internal_http=(settings.agent_runtime.allow_insecure_internal_http),
            ),
            grant_issuer=RuntimeGrantIssuer.from_file(
                settings.agent_runtime.grant_private_key_file
            ),
            mcp_token_issuer=mcp_token_issuer,
            event_sink=agent_repository.record_runtime_event,
        )
    claude_client = RoutedAgentRuntimeClient(
        python_client=python_claude_client,
        typescript_client=typescript_runtime_client,
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
    delivery_dispatcher = DeliveryOutboxDispatcher(
        repository=agent_repository,
        delivery_service=result_delivery_service,
        audit_service=audit_service,
        settings=settings.delivery,
        worker_id=f"{service_name}-delivery-dispatcher",
    )
    object_storage: ObjectStorage = InMemoryObjectStorage(settings.object_storage.bucket)
    if service_name == "attachment-worker" and message_bus is None:
        s3_storage = S3ObjectStorage(settings.object_storage)
        s3_storage.ensure_bucket()
        object_storage = s3_storage
    attachment_service: AttachmentProcessingService | None = None
    if credential_cipher is not None and (
        service_name == "attachment-worker" or message_bus is not None
    ):
        attachment_service = AttachmentProcessingService(
            repository=agent_repository,
            publisher=publisher,
            audit_service=audit_service,
            credential_cipher=credential_cipher,
            downloader=DingTalkMediaDownloader(
                token_client=DingTalkAccessTokenClient(
                    client_id=settings.dingtalk.stream_client_id,
                    client_secret=settings.dingtalk.stream_client_secret,
                    timeout_seconds=settings.attachments.timeout_seconds,
                ),
                robot_code=settings.dingtalk.default_robot_code
                or settings.dingtalk.stream_client_id,
                timeout_seconds=settings.attachments.timeout_seconds,
            ),
            storage=object_storage,
            extractor=SafeAttachmentExtractor(settings.attachments),
            settings=settings.attachments,
            delivery_service=result_delivery_service,
        )
    agent_executor = AgentExecutor(
        repository=agent_repository,
        audit_service=audit_service,
        status_service=JobStatusService(agent_repository),
        context_builder=AgentContextBuilder(
            skill_loader=SkillLoader(),
            conversation_service=ConversationContextService(
                agent_repository, settings.conversation
            ),
            agent_config_service=agent_config_service,
            mcp_binding_service=mcp_binding_service,
        ),
        claude_client=claude_client,
        result_service=AgentResultService(agent_repository),
        delivery_service=result_delivery_service,
        business_authorization_service=business_authorization_service,
    )
    retry_service = JobRetryService(
        repository=agent_repository,
        queue_settings=settings.queue,
        audit_service=audit_service,
        delivery_service=result_delivery_service,
    )
    return Container(
        settings=settings,
        database=database,
        agent_repository=agent_repository,
        identity_repository=identity_repository,
        identity_service=identity_service,
        identity_admin_service=identity_admin_service,
        identity_discovery_repository=identity_discovery_repository,
        identity_discovery_service=identity_discovery_service,
        auth_service=auth_service,
        authorization_evaluator=authorization_evaluator,
        authorization_center_repository=authorization_center_repository,
        business_authorization_service=business_authorization_service,
        agent_config_service=agent_config_service,
        model_connection_service=model_connection_service,
        external_credential_binding_service=external_credential_binding_service,
        audit_service=audit_service,
        audit_repository=audit_repository,
        permission_service=permission_service,
        publisher=publisher,
        consumer=consumer,
        message_bus=message_bus,
        connector_registry=connector_registry,
        platform_config_service=platform_config_service,
        business_application_repository=business_application_repository,
        business_application_resolver=business_application_resolver,
        business_application_service=business_application_service,
        channel_ingress_service=channel_ingress_service,
        create_agent_job_service=create_job_service,
        mcp_resource_service=mcp_resource_service,
        mcp_tool_publication_service=mcp_tool_publication_service,
        cutover_service=cutover_service,
        job_dispatcher=job_dispatcher,
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
        managed_channel_service=managed_channel_service,
        webhook_ingress_service=webhook_ingress_service,
        webhook_outbox_publisher=webhook_outbox_publisher,
        webhook_dispatcher=webhook_dispatcher,
        managed_channel_repository=managed_channel_repository,
        runtime_control_service=runtime_control_service,
        channel_outbox_publisher=channel_outbox_publisher,
        channel_dispatch_service=channel_dispatch_service,
    )
