from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.conversation_context import ConversationContextService
from app.modules.agent.application.agent_executor import AgentExecutor
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.infrastructure.claude_code_agent_client import (
    RealClaudeCodeAgentClient,
    StubClaudeCodeAgentClient,
)
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.agent_config.application import AgentConfigService
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.attachments.credentials import AttachmentCredentialCipher
from app.modules.attachments.dingtalk_downloader import DingTalkMediaDownloader
from app.modules.attachments.domain import ObjectStorage
from app.modules.attachments.extraction import SafeAttachmentExtractor
from app.modules.attachments.service import AttachmentProcessingService
from app.modules.attachments.storage import InMemoryObjectStorage, S3ObjectStorage
from app.modules.channel.application.channel_ingress_service import ChannelIngressService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.delivery.application.report_chunker import ReportChunker
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.delivery.infrastructure.adapters import (
    DingTalkConversationDeliveryAdapter,
    DingTalkEnterpriseAppDeliveryAdapter,
    DingTalkStreamSessionWebhookDeliveryAdapter,
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
from app.modules.internal_tools.application.tools import ReadOnlyToolService
from app.modules.internal_tools.infrastructure.internal_api_client import (
    FakeInternalApiClient,
    HttpInternalApiClient,
    InternalApiClient,
)
from app.modules.identity.application import (
    AuthService,
    AuthorizationEvaluator,
    IdentityAdminService,
    IdentityService,
)
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.application.create_agent_job_service import CreateAgentJobService
from app.modules.job.application.job_retry_service import JobRetryService
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.infrastructure.repositories import (
    AgentRepository,
    AuditRepository,
    ConfigurationRepository,
)
from app.modules.message_bus.application.message_publisher import MessageConsumer, MessagePublisher
from app.modules.message_bus.infrastructure.in_memory_bus import InMemoryMessageBus
from app.modules.message_bus.infrastructure.rabbitmq_consumer import RabbitMQConsumer
from app.modules.message_bus.infrastructure.rabbitmq_publisher import RabbitMQPublisher
from app.modules.permission.application.permission_service import PermissionService
from app.modules.platform_config.application import PlatformConfigService
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
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
    identity_admin_service: IdentityAdminService
    auth_service: AuthService
    authorization_evaluator: AuthorizationEvaluator
    agent_config_service: AgentConfigService
    audit_service: AuditService
    audit_repository: AuditRepository
    permission_service: PermissionService
    publisher: MessagePublisher
    consumer: MessageConsumer | None
    message_bus: InMemoryMessageBus | None
    internal_api_client: InternalApiClient
    tool_service: ReadOnlyToolService
    connector_registry: ConnectorRegistry
    platform_config_service: PlatformConfigService
    workflow_service: WorkflowService
    channel_ingress_service: ChannelIngressService
    create_agent_job_service: CreateAgentJobService
    dingtalk_message_service: DingTalkMessageService
    dingtalk_stream_message_service: DingTalkStreamMessageService
    result_delivery_service: ResultDeliveryService
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


ContainerFactory = Callable[[Settings], Container]


def build_api_container(
    settings: Settings, *, migrate: bool = True, seed: bool = False
) -> Container:
    settings = load_settings_with_db_overlay(settings, service_name="api-server", migrate=migrate)
    publisher = RabbitMQPublisher(settings.rabbitmq_url, settings.queue)
    return _build_container(
        settings=settings,
        publisher=publisher,
        consumer=None,
        message_bus=None,
        migrate=migrate,
        seed=seed,
        use_real_claude=settings.feature_real_claude,
    )


def build_worker_container(
    settings: Settings,
    *,
    migrate: bool = True,
    seed: bool = False,
    service_name: str = "agent-worker",
) -> Container:
    settings = load_settings_with_db_overlay(settings, service_name=service_name, migrate=migrate)
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
        publisher=publisher,
        consumer=consumer,
        message_bus=None,
        migrate=migrate,
        seed=seed,
        use_real_claude=settings.feature_real_claude,
    )


def build_test_container(
    settings: Settings, *, migrate: bool = True, seed: bool = False
) -> Container:
    settings = load_settings_with_db_overlay(settings, service_name="api-server", migrate=migrate)
    message_bus = InMemoryMessageBus()
    return _build_container(
        settings=settings,
        publisher=message_bus,
        consumer=message_bus,
        message_bus=message_bus,
        migrate=migrate,
        seed=seed,
        use_real_claude=False,
    )


def build_container(settings: Settings, *, migrate: bool = True, seed: bool = False) -> Container:
    return build_test_container(settings, migrate=migrate, seed=seed)


def _build_container(
    *,
    settings: Settings,
    publisher: MessagePublisher,
    consumer: MessageConsumer | None,
    message_bus: InMemoryMessageBus | None,
    migrate: bool,
    seed: bool,
    use_real_claude: bool,
) -> Container:
    database = Database(settings.database_dsn)
    if migrate:
        database.run_migrations(default_migrations_dir())
    if seed:
        seed_path = default_migrations_dir().parent / "seeds" / "local_seed.sql"
        database.execute_script(seed_path.read_text())

    agent_repository = AgentRepository(database)
    audit_repository = AuditRepository(database)
    config_repository = ConfigurationRepository(database)
    identity_repository = IdentityRepository(database)
    platform_config_repository = PlatformConfigRepository(database)
    agent_config_repository = AgentConfigRepository(database)
    workflow_repository = WorkflowRepository(database)
    webhook_trigger_repository = WebhookTriggerRepository(database)
    webhook_event_repository = WebhookEventRepository(database)
    audit_service = AuditService(
        audit_repository,
        max_chars=settings.execution.max_tool_response_chars,
    )
    connector_registry = ConnectorRegistry(config_repository)
    identity_service = IdentityService(
        identity_repository,
        audit_service,
        connector_registry,
    )
    authorization_evaluator = AuthorizationEvaluator(identity_repository, audit_service)
    permission_service = PermissionService(
        config_repository,
        authorization_evaluator=authorization_evaluator,
        unified_enabled=settings.identity.enabled,
        shadow_mode=settings.identity.permission_shadow_mode,
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
    agent_config_service = AgentConfigService(
        agent_config_repository,
        authorization_evaluator,
        audit_service,
        SkillLoader(),
        allowed_models={settings.claude_model},
    )
    platform_config_service = PlatformConfigService(
        platform_config_repository,
        permission_service,
    )
    workflow_service = WorkflowService(
        workflow_repository,
        permission_service,
    )
    credential_cipher = (
        AttachmentCredentialCipher(settings.app_config_master_key)
        if settings.attachments.enabled
        else None
    )
    create_job_service = CreateAgentJobService(
        repository=agent_repository,
        permission_service=permission_service,
        audit_service=audit_service,
        publisher=publisher,
        queue_settings=settings.queue,
        connector_registry=connector_registry,
        credential_cipher=credential_cipher,
        continuous_enabled=settings.conversation.enabled,
        attachment_settings=settings.attachments,
        agent_config_service=agent_config_service,
        published_agent_runtime_enabled=settings.identity.published_agent_runtime_enabled,
        default_agent_code=settings.identity.default_agent_code,
    )
    channel_ingress_service = ChannelIngressService(
        create_job_service=create_job_service,
        audit_service=audit_service,
        identity_service=identity_service if settings.identity.enabled else None,
        unified_identity_enabled=settings.identity.enabled,
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
        authorization=authorization_evaluator,
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
            event_repository=webhook_event_repository,
        ),
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
        attachments_enabled=settings.attachments.enabled,
        attachment_credential_ttl_seconds=settings.attachments.credential_ttl_seconds,
        connector_registry=connector_registry,
        default_tenant_code=settings.identity.dingtalk_tenant_code,
    )
    internal_api_client: InternalApiClient = FakeInternalApiClient()
    if settings.feature_real_internal_tools and message_bus is None:
        internal_api_client = HttpInternalApiClient(
            settings.internal_api_base_url,
            auth_token=settings.internal_api_auth_token,
            timeout_seconds=settings.internal_api_timeout_seconds,
            max_response_chars=settings.internal_api_max_response_chars,
        )
    tool_service = ReadOnlyToolService(
        internal_api_client=internal_api_client,
        permission_service=permission_service,
        audit_service=audit_service,
        repository=agent_repository,
        limits=settings.execution,
    )
    tool_registry = ToolRegistry(tool_service)
    claude_client = (
        RealClaudeCodeAgentClient(
            model=settings.claude_model,
            tool_registry=tool_registry,
            limits=settings.execution,
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
        )
        if use_real_claude
        else StubClaudeCodeAgentClient()
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
    dingtalk_stream_session_webhook_adapter = DingTalkStreamSessionWebhookDeliveryAdapter(
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
    )
    object_storage: ObjectStorage = InMemoryObjectStorage(settings.object_storage.bucket)
    if settings.attachments.enabled and message_bus is None:
        s3_storage = S3ObjectStorage(settings.object_storage)
        s3_storage.ensure_bucket()
        object_storage = s3_storage
    attachment_service: AttachmentProcessingService | None = None
    if settings.attachments.enabled and credential_cipher is not None:
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
            tool_registry=tool_registry,
            skill_loader=SkillLoader(),
            conversation_service=(
                ConversationContextService(agent_repository, settings.conversation)
                if settings.conversation.enabled
                else None
            ),
            agent_config_service=agent_config_service,
        ),
        claude_client=claude_client,
        tool_registry=tool_registry,
        result_service=AgentResultService(agent_repository),
        delivery_service=result_delivery_service,
    )
    retry_service = JobRetryService(
        repository=agent_repository,
        publisher=publisher,
        queue_settings=settings.queue,
    )
    return Container(
        settings=settings,
        database=database,
        agent_repository=agent_repository,
        identity_repository=identity_repository,
        identity_service=identity_service,
        identity_admin_service=identity_admin_service,
        auth_service=auth_service,
        authorization_evaluator=authorization_evaluator,
        agent_config_service=agent_config_service,
        audit_service=audit_service,
        audit_repository=audit_repository,
        permission_service=permission_service,
        publisher=publisher,
        consumer=consumer,
        message_bus=message_bus,
        internal_api_client=internal_api_client,
        tool_service=tool_service,
        connector_registry=connector_registry,
        platform_config_service=platform_config_service,
        workflow_service=workflow_service,
        channel_ingress_service=channel_ingress_service,
        create_agent_job_service=create_job_service,
        dingtalk_message_service=dingtalk_service,
        dingtalk_stream_message_service=dingtalk_stream_service,
        result_delivery_service=result_delivery_service,
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
    )
