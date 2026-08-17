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
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.application.job_dispatch_service import (
    JobDispatchOutboxDispatcher,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.config import QueueSettings, Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.workers.agent_job_worker import AgentJobWorker


POSTGRES_ADMIN_DSN = os.getenv("MIGRATION_POSTGRES_DSN", "")
RABBITMQ_URL = os.getenv("RABBITMQ_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_ADMIN_DSN or not RABBITMQ_URL,
    reason=(
        "set MIGRATION_POSTGRES_DSN and RABBITMQ_TEST_URL to run the Phase 2B real integration"
    ),
)


class _StaticContextBuilder:
    def build(self, job: object) -> AgentExecutionContext:
        return AgentExecutionContext(
            system_role="Phase 2B integration Agent",
            safety_rules=["Read only"],
            user_question="prove durable dispatch",
            project_code="default",
            allowed_tools=[],
            tool_restrictions=[],
            skills={},
            retrieved_context={},
            conversation_summary="",
        )


class _CountingAgentClient:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: object) -> AgentRunResult:
        self.calls += 1
        return AgentRunResult(final_answer="one durable business result")


class _UnavailablePublisher:
    def publish_agent_job(
        self,
        event_id: str,
        job_id: str,
        correlation_id: str,
    ) -> None:
        raise ConnectionError("synthetic broker interruption")


@pytest.fixture
def migrated_postgres_dsn() -> str:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    database_name = f"phase2b_gate_{uuid.uuid4().hex}"
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
            migrator_build="phase2b-real-gate",
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


def _create_job(container: object, label: str) -> object:
    return container.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=f"phase2b-{label}-{uuid.uuid4().hex}",
            requester_id="user_local_admin",
            external_conversation_id=f"phase2b-{label}",
            user_message=f"Phase 2B {label}",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            project_code="default",
            correlation_id=f"phase2b-correlation-{label}",
        )
    )


def test_committed_job_survives_dispatch_and_duplicate_event_executes_once(
    migrated_postgres_dsn: str,
) -> None:
    import pika

    suffix = uuid.uuid4().hex
    queue = QueueSettings(
        job_queue=f"agent.phase2b.gate.{suffix}",
        dispatch_outbox_max_attempts=2,
        dispatch_outbox_retry_base_seconds=1,
    )
    settings = Settings(
        database_dsn=migrated_postgres_dsn,
        rabbitmq_url=RABBITMQ_URL,
        feature_real_claude=False,
        queue=queue,
    )
    counting_client = _CountingAgentClient()
    container = build_worker_container(
        settings,
        seed=True,
        runtime_client=counting_client,
    )
    container.settings = replace(container.settings, queue=queue)
    container.agent_executor.context_builder = _StaticContextBuilder()  # type: ignore[assignment]
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    try:
        version = connection._impl.server_properties["version"]
        if isinstance(version, bytes):
            version = version.decode("ascii")
        assert str(version).startswith("4."), f"RabbitMQ 4 required, got {version}"

        committed_job = _create_job(container, "success")
        committed_event = container.agent_repository.get_dispatch_event_for_job(committed_job.id)
        assert committed_job.status == JobStatus.PENDING
        assert committed_event is not None
        assert committed_event.status.value == "PENDING"

        publish_result = container.job_dispatcher.publish_pending(limit=1)
        assert publish_result.published == 1
        method, properties, body = channel.basic_get(
            queue=queue.job_queue,
            auto_ack=False,
        )
        assert method is not None
        assert properties.delivery_mode == 2
        payload = json.loads(body.decode("utf-8"))
        assert payload == {
            "event_id": committed_event.id,
            "job_id": committed_job.id,
            "correlation_id": committed_event.correlation_id,
        }
        channel.basic_ack(method.delivery_tag)

        message = AgentJobMessage(**payload)
        worker = AgentJobWorker(container.settings, container=container)
        worker.handle(message)
        worker.handle(message)

        persisted_job = container.agent_repository.get_job(committed_job.id)
        assert persisted_job.status == JobStatus.SUCCEEDED
        assert persisted_job.result == "one durable business result"
        assert counting_client.calls == 1
        assert container.database.execute_one(
            """
            select count(*) as count
              from audit_event
             where job_id = ? and event_type = 'worker.claimed'
            """,
            (committed_job.id,),
        ) == {"count": 1}

        failed_job = _create_job(container, "broker-dead")
        failed_event = container.agent_repository.get_dispatch_event_for_job(failed_job.id)
        assert failed_event is not None
        unavailable_dispatcher = JobDispatchOutboxDispatcher(
            repository=container.agent_repository,
            publisher=_UnavailablePublisher(),
            audit_service=container.audit_service,
            settings=queue,
            worker_id="phase2b-unavailable-broker",
        )
        first_failure = unavailable_dispatcher.publish_pending(limit=1)
        assert first_failure.failed == 1
        assert first_failure.dead == 0
        container.database.execute(
            """
            update job_dispatch_outbox
               set next_attempt_at = '2000-01-01T00:00:00+00:00'
             where id = ?
            """,
            (failed_event.id,),
        )
        second_failure = unavailable_dispatcher.publish_pending(limit=1)
        terminal_event = container.agent_repository.get_dispatch_event(failed_event.id)
        assert second_failure.failed == 1
        assert second_failure.dead == 1
        assert terminal_event.status.value == "DEAD"
        assert terminal_event.attempt_count == 2
        assert container.agent_repository.get_job(failed_job.id).status == JobStatus.PENDING
    finally:
        try:
            channel.queue_delete(queue=queue.job_queue)
        finally:
            connection.close()
            container.database.close()
