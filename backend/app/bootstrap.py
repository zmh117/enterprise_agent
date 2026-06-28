from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.agent_executor import AgentExecutor
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.infrastructure.claude_code_agent_client import StubClaudeCodeAgentClient
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.audit.application.audit_service import AuditService
from app.modules.dingding.application.dingding_message_service import DingTalkMessageService
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.modules.internal_tools.application.tools import ReadOnlyToolService
from app.modules.internal_tools.infrastructure.internal_api_client import FakeInternalApiClient
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
    internal_api_client: FakeInternalApiClient
    tool_service: ReadOnlyToolService
    create_agent_job_service: CreateAgentJobService
    dingtalk_message_service: DingTalkMessageService
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
    )


def build_worker_container(
    settings: Settings, *, migrate: bool = True, seed: bool = False
) -> Container:
    publisher = RabbitMQPublisher(settings.rabbitmq_url, settings.queue)
    consumer = RabbitMQConsumer(settings.rabbitmq_url, settings.queue)
    return _build_container(
        settings=settings,
        publisher=publisher,
        consumer=consumer,
        message_bus=None,
        migrate=migrate,
        seed=seed,
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
    create_job_service = CreateAgentJobService(
        repository=agent_repository,
        permission_service=permission_service,
        audit_service=audit_service,
        publisher=publisher,
        queue_settings=settings.queue,
    )
    dingtalk_service = DingTalkMessageService(
        secret=settings.dingtalk.secret,
        create_job_service=create_job_service,
        callback_client=DingTalkCallbackClient(
            callback_url=settings.dingtalk.callback_url,
            host_allowlist=settings.dingtalk.callback_host_allowlist,
        ),
    )
    internal_api_client = FakeInternalApiClient()
    tool_service = ReadOnlyToolService(
        internal_api_client=internal_api_client,
        permission_service=permission_service,
        audit_service=audit_service,
        repository=agent_repository,
        limits=settings.execution,
    )
    tool_registry = ToolRegistry(tool_service)
    agent_executor = AgentExecutor(
        repository=agent_repository,
        audit_service=audit_service,
        status_service=JobStatusService(agent_repository),
        context_builder=AgentContextBuilder(
            tool_registry=tool_registry,
            skill_loader=SkillLoader(),
        ),
        claude_client=StubClaudeCodeAgentClient(),
        tool_registry=tool_registry,
        result_service=AgentResultService(agent_repository),
        callback_client=DingTalkCallbackClient(
            callback_url=settings.dingtalk.callback_url,
            host_allowlist=settings.dingtalk.callback_host_allowlist,
        ),
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
        create_agent_job_service=create_job_service,
        dingtalk_message_service=dingtalk_service,
        agent_executor=agent_executor,
        retry_service=retry_service,
    )
