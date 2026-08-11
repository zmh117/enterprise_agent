from __future__ import annotations

from dataclasses import replace
import json
import os
import uuid

import pytest

from app.bootstrap import build_worker_container
from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunResult,
)
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.delivery.application.delivery_operations import (
    DeliveryOperationsService,
)
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.application.job_dispatch_service import (
    JobDispatchOutboxDispatcher,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.config import DeliverySettings, QueueSettings, Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import RetryableExecutionError
from app.shared.migrations import Migrator
from app.workers.agent_job_worker import AgentJobWorker


POSTGRES_ADMIN_DSN = os.getenv("MIGRATION_POSTGRES_DSN", "")
RABBITMQ_URL = os.getenv("RABBITMQ_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_ADMIN_DSN or not RABBITMQ_URL,
    reason=(
        "set MIGRATION_POSTGRES_DSN and RABBITMQ_TEST_URL to run the Phase 2C real integration"
    ),
)


class _StaticContextBuilder:
    def build(self, job: object) -> AgentExecutionContext:
        del job
        return AgentExecutionContext(
            system_role="Phase 2C integration Agent",
            safety_rules=["Read only"],
            user_question="prove independent Delivery recovery",
            project_code="default",
            allowed_tools=[],
            tool_restrictions=[],
            skills={},
            retrieved_context={},
            conversation_summary="",
        )


class _CountingLongResultClient:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: object) -> AgentRunResult:
        del request
        self.calls += 1
        return AgentRunResult(final_answer="x" * 450)


class _UnavailablePublisher:
    def publish_agent_job(
        self,
        event_id: str,
        job_id: str,
        correlation_id: str,
    ) -> None:
        del event_id, job_id, correlation_id
        raise ConnectionError("synthetic RabbitMQ interruption")


class _SecondChunkOutageAdapter(DeliveryAdapter):
    def __init__(self) -> None:
        self.available = False
        self.calls: list[str] = []

    def send(
        self,
        *,
        connector: object,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        del connector, route, text
        self.calls.append(title)
        if not self.available and title.endswith("part 2/3"):
            raise RetryableExecutionError(
                "synthetic Delivery interruption",
                safe_message="投递服务暂时不可用",
                error_code="delivery_phase2c_interrupted",
            )


@pytest.fixture
def migrated_postgres_dsn() -> str:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    database_name = f"phase2c_gate_{uuid.uuid4().hex}"
    with psycopg.connect(POSTGRES_ADMIN_DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(database_name)))
    parameters = conninfo_to_dict(POSTGRES_ADMIN_DSN)
    parameters["dbname"] = database_name
    test_dsn = make_conninfo(**parameters)
    database = Database(test_dsn)
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="phase2c-real-gate",
        ).run()
    finally:
        database.close()
    try:
        yield test_dsn
    finally:
        with psycopg.connect(POSTGRES_ADMIN_DSN, autocommit=True) as admin:
            admin.execute(
                """
                select pg_terminate_backend(pid)
                  from pg_stat_activity
                 where datname = %s and pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(sql.SQL("drop database {}").format(sql.Identifier(database_name)))


def test_rabbitmq_recovery_then_dead_delivery_replay_does_not_rerun_agent(
    migrated_postgres_dsn: str,
) -> None:
    import pika

    suffix = uuid.uuid4().hex
    queue = QueueSettings(
        job_queue=f"agent.phase2c.gate.{suffix}",
        dispatch_outbox_max_attempts=2,
        dispatch_outbox_retry_base_seconds=1,
    )
    delivery = DeliverySettings(
        outbox_max_attempts=1,
        outbox_max_replays=1,
        outbox_retry_base_seconds=1,
    )
    settings = Settings(
        database_dsn=migrated_postgres_dsn,
        rabbitmq_url=RABBITMQ_URL,
        feature_real_claude=False,
        queue=queue,
        delivery=delivery,
    )
    client = _CountingLongResultClient()
    runtime = build_worker_container(
        settings,
        seed=True,
        runtime_clients={
            "python-v1": client,
            "typescript-v1": client,
        },
    )
    runtime.settings = replace(
        runtime.settings,
        queue=queue,
        delivery=delivery,
    )
    runtime.agent_executor.context_builder = _StaticContextBuilder()  # type: ignore[assignment]
    runtime.result_delivery_service.chunker.max_chars = 200
    adapter = _SecondChunkOutageAdapter()
    runtime.result_delivery_service.adapters["phase2c_delivery"] = adapter
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    try:
        version = connection._impl.server_properties["version"]
        if isinstance(version, bytes):
            version = version.decode("ascii")
        assert str(version).startswith("4."), f"RabbitMQ 4 required, got {version}"

        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key=f"phase2c-{suffix}",
                requester_id="user_local_admin",
                external_conversation_id=f"phase2c-{suffix}",
                user_message="Phase 2C real chain",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                project_code="default",
                correlation_id=f"phase2c-correlation-{suffix}",
                reply_route={"type": "phase2c_delivery", "target": {}},
            )
        )
        dispatch_event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert dispatch_event is not None

        unavailable = JobDispatchOutboxDispatcher(
            repository=runtime.agent_repository,
            publisher=_UnavailablePublisher(),
            audit_service=runtime.audit_service,
            settings=queue,
            worker_id="phase2c-rabbit-unavailable",
        )
        failed_publish = unavailable.publish_pending(limit=1)
        assert failed_publish.failed == 1
        assert failed_publish.dead == 0
        assert runtime.agent_repository.get_delivery_event_for_job(job.id) is None
        runtime.database.execute(
            """
            update job_dispatch_outbox
               set next_attempt_at = '2000-01-01T00:00:00+00:00'
             where id = ?
            """,
            (dispatch_event.id,),
        )

        recovered_publish = runtime.job_dispatcher.publish_pending(limit=1)
        assert recovered_publish.published == 1
        method, properties, body = channel.basic_get(
            queue=queue.job_queue,
            auto_ack=False,
        )
        assert method is not None
        assert properties.delivery_mode == 2
        payload = json.loads(body.decode("utf-8"))
        channel.basic_ack(method.delivery_tag)

        message = AgentJobMessage(**payload)
        worker = AgentJobWorker(runtime.settings, container=runtime)
        worker.handle(message)
        worker.handle(message)
        assert client.calls == 1
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED

        event = runtime.agent_repository.get_delivery_event_for_job(job.id)
        assert event is not None
        artifact_before = runtime.agent_repository.get_artifact(event.result_artifact_id)
        duplicate_id = runtime.result_delivery_service.enqueue_job_result(
            job_id=job.id,
            artifact_id=event.result_artifact_id,
            correlation_id=event.correlation_id,
        )
        assert duplicate_id == event.id

        failed_delivery = runtime.delivery_dispatcher.dispatch_pending(limit=1)
        assert failed_delivery.dead == 1
        assert runtime.agent_repository.get_delivery_event(event.id).status.value == "DEAD"
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
        assert adapter.calls == [
            "Agent 诊断报告 part 1/3",
            "Agent 诊断报告 part 2/3",
        ]

        operations = DeliveryOperationsService(
            repository=runtime.agent_repository,
            audit_service=runtime.audit_service,
        )
        replayed = operations.replay(
            delivery_id=event.id,
            actor_id="phase2c-integration-operator",
            reason="RabbitMQ recovered; retry persisted Delivery intent",
        )
        assert replayed["status"] == "PENDING"
        adapter.available = True
        completed_delivery = runtime.delivery_dispatcher.dispatch_pending(limit=1)

        assert completed_delivery.succeeded == 1
        assert runtime.agent_repository.get_delivery_event(event.id).status.value == "SUCCEEDED"
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
        assert client.calls == 1
        assert runtime.agent_repository.get_artifact(event.result_artifact_id) == artifact_before
        assert adapter.calls.count("Agent 诊断报告 part 1/3") == 1
        assert adapter.calls.count("Agent 诊断报告 part 2/3") == 2
        assert adapter.calls.count("Agent 诊断报告 part 3/3") == 1
    finally:
        try:
            channel.queue_delete(queue=queue.job_queue)
        finally:
            connection.close()
            runtime.database.close()
