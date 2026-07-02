from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.agent_executor import AgentExecutor
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.infrastructure.claude_code_agent_client import (
    RealClaudeCodeAgentClient,
    StubClaudeCodeAgentClient,
)
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.application.channel_ingress_service import ChannelIngressService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.delivery.application.report_chunker import ReportChunker
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.delivery.infrastructure.adapters import (
    DingTalkDeliveryAdapter,
    HttpDeliveryAdapter,
    NoneDeliveryAdapter,
)
from app.modules.dingding.application.dingding_message_service import DingTalkMessageService
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.modules.internal_tools.application.tools import ReadOnlyToolService
from app.modules.internal_tools.infrastructure.internal_api_client import (
    FakeInternalApiClient,
    HttpInternalApiClient,
    InternalApiClient,
)
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
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir


@dataclass
class Container:
    settings: Settings
    database: Database
    agent_repository: AgentRepository
    audit_service: AuditService
    permission_service: PermissionService
    publisher: MessagePublisher
    consumer: MessageConsumer | None
    message_bus: InMemoryMessageBus | None
    internal_api_client: InternalApiClient
    tool_service: ReadOnlyToolService
    connector_registry: ConnectorRegistry
    channel_ingress_service: ChannelIngressService
    create_agent_job_service: CreateAgentJobService
    dingtalk_message_service: DingTalkMessageService
    result_delivery_service: ResultDeliveryService
    agent_executor: AgentExecutor
    retry_service: JobRetryService


ContainerFactory = Callable[[Settings], Container]


def build_api_container(
    settings: Settings, *, migrate: bool = True, seed: bool = False
) -> Container:
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
    settings: Settings, *, migrate: bool = True, seed: bool = False
) -> Container:
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
    audit_service = AuditService(
        audit_repository,
        max_chars=settings.execution.max_tool_response_chars,
    )
    permission_service = PermissionService(config_repository)
    connector_registry = ConnectorRegistry(config_repository)
    create_job_service = CreateAgentJobService(
        repository=agent_repository,
        permission_service=permission_service,
        audit_service=audit_service,
        publisher=publisher,
        queue_settings=settings.queue,
        connector_registry=connector_registry,
    )
    channel_ingress_service = ChannelIngressService(
        create_job_service=create_job_service,
        audit_service=audit_service,
    )
    dingtalk_service = DingTalkMessageService(
        secret=settings.dingtalk.secret,
        channel_ingress_service=channel_ingress_service,
        callback_client=DingTalkCallbackClient(
            callback_url=settings.dingtalk.callback_url,
            host_allowlist=settings.dingtalk.callback_host_allowlist,
        ),
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
    dingtalk_adapter = DingTalkDeliveryAdapter(
        fallback_callback_url=settings.dingtalk.callback_url,
        host_allowlist=settings.dingtalk.callback_host_allowlist,
    )
    http_adapter = HttpDeliveryAdapter(timeout_seconds=settings.delivery.timeout_seconds)
    result_delivery_service = ResultDeliveryService(
        repository=agent_repository,
        audit_service=audit_service,
        connector_registry=connector_registry,
        adapters={
            "none": NoneDeliveryAdapter(),
            "dingtalk_conversation": dingtalk_adapter,
            "dingtalk_webhook_robot": dingtalk_adapter,
            "dingtalk_enterprise_robot": dingtalk_adapter,
            "email": http_adapter,
            "webhook": http_adapter,
        },
        chunker=ReportChunker(settings.delivery.chunk_max_chars),
    )
    agent_executor = AgentExecutor(
        repository=agent_repository,
        audit_service=audit_service,
        status_service=JobStatusService(agent_repository),
        context_builder=AgentContextBuilder(
            tool_registry=tool_registry,
            skill_loader=SkillLoader(),
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
        audit_service=audit_service,
        permission_service=permission_service,
        publisher=publisher,
        consumer=consumer,
        message_bus=message_bus,
        internal_api_client=internal_api_client,
        tool_service=tool_service,
        connector_registry=connector_registry,
        channel_ingress_service=channel_ingress_service,
        create_agent_job_service=create_job_service,
        dingtalk_message_service=dingtalk_service,
        result_delivery_service=result_delivery_service,
        agent_executor=agent_executor,
        retry_service=retry_service,
    )
