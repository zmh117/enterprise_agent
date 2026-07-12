from __future__ import annotations

import json
import os
import unittest
import uuid
from dataclasses import replace

from app.bootstrap import build_worker_container
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.workers.agent_job_worker import AgentJobWorker
from app.shared.config import QueueSettings, Settings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError

_RUN = os.getenv("RUN_RABBITMQ4_FAILURE_INTEGRATION") == "1"


class _FailingClaudeClient:
    def __init__(self, *, retryable: bool) -> None:
        self.retryable = retryable

    def run(self, request: object) -> object:
        if self.retryable:
            raise RetryableExecutionError(
                "synthetic retryable failure",
                safe_message="Synthetic RabbitMQ 4 retry smoke failure",
            )
        raise NonRetryableExecutionError(
            "synthetic non-retryable failure",
            safe_message="Synthetic RabbitMQ 4 dead-letter smoke failure",
        )


@unittest.skipUnless(
    _RUN,
    "set RUN_RABBITMQ4_FAILURE_INTEGRATION=1 to run against live PostgreSQL/RabbitMQ 4",
)
class RabbitMQ4JobFailureIntegrationTests(unittest.TestCase):
    """Validates DB status, audit, retry and dead queues as one live boundary."""

    def setUp(self) -> None:
        import pika

        suffix = uuid.uuid4().hex
        self.rabbitmq_url = os.getenv(
            "RABBITMQ_TEST_URL", "amqp://guest:guest@127.0.0.1:5672/"
        )
        self.database_dsn = os.getenv(
            "POSTGRES_TEST_DSN",
            "postgresql://enterprise_agent:enterprise_agent@127.0.0.1:5433/enterprise_agent",
        )
        self.queue = QueueSettings(
            job_queue=f"agent.failure.job.{suffix}",
            retry_queue=f"agent.failure.retry.{suffix}",
            dead_queue=f"agent.failure.dead.{suffix}",
            retry_delay_seconds=1,
        )
        settings = Settings(
            database_dsn=self.database_dsn,
            rabbitmq_url=self.rabbitmq_url,
            feature_real_claude=False,
            feature_real_internal_tools=False,
            queue=self.queue,
        )
        self.container = build_worker_container(settings, migrate=True, seed=False)
        # DB runtime overlay can tune retry settings, but test queue names must stay isolated.
        self.container.settings = replace(self.container.settings, queue=self.queue)
        self.connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        self.channel = self.connection.channel()

    def tearDown(self) -> None:
        if hasattr(self, "channel"):
            for queue_name in (
                self.queue.job_queue,
                self.queue.retry_queue,
                self.queue.dead_queue,
            ):
                self.channel.queue_delete(queue=queue_name)
            self.connection.close()
        if hasattr(self, "container"):
            self.container.database.close()

    def _create_and_take_job_message(self, label: str) -> AgentJobMessage:
        job = self.container.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key=f"rabbitmq4-failure-smoke-{label}-{uuid.uuid4().hex}",
                requester_id="local-user",
                external_conversation_id=f"rabbitmq4-failure-{label}",
                user_message=f"Synthetic {label} failure smoke",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                project_code="default",
                correlation_id=f"corr-{label}",
            )
        )
        method, _, body = self.channel.basic_get(queue=self.queue.job_queue, auto_ack=False)
        self.assertIsNotNone(method)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(job.id, payload["job_id"])
        self.channel.basic_ack(method.delivery_tag)
        return AgentJobMessage(
            job_id=payload["job_id"],
            correlation_id=payload["correlation_id"],
        )

    def _take_routed_payload(self, queue_name: str) -> dict[str, object]:
        method, properties, body = self.channel.basic_get(queue=queue_name, auto_ack=False)
        self.assertIsNotNone(method, f"No routed message in {queue_name}")
        self.assertEqual(2, properties.delivery_mode)
        payload = json.loads(body.decode("utf-8"))
        self.channel.basic_ack(method.delivery_tag)
        return payload

    def test_retry_and_dead_routes_match_persisted_job_and_audit_state(self) -> None:
        worker = AgentJobWorker(self.container.settings, container=self.container)

        retry_message = self._create_and_take_job_message("retry")
        self.container.agent_executor.claude_client = _FailingClaudeClient(  # type: ignore[assignment]
            retryable=True
        )
        worker.handle(retry_message)
        retry_job = self.container.agent_repository.get_job(retry_message.job_id)
        retry_payload = self._take_routed_payload(self.queue.retry_queue)
        retry_audit = self.container.database.execute(
            "select event_type, status from audit_event where job_id = ? order by created_at",
            (retry_message.job_id,),
        )

        self.assertEqual(JobStatus.PENDING, retry_job.status)
        self.assertEqual(1, retry_job.retry_count)
        self.assertEqual(retry_message.job_id, retry_payload["job_id"])
        self.assertIn("job.failure.retry", [row["event_type"] for row in retry_audit])

        dead_message = self._create_and_take_job_message("dead")
        self.container.agent_executor.claude_client = _FailingClaudeClient(  # type: ignore[assignment]
            retryable=False
        )
        worker.handle(dead_message)
        dead_job = self.container.agent_repository.get_job(dead_message.job_id)
        dead_payload = self._take_routed_payload(self.queue.dead_queue)
        dead_audit = self.container.database.execute(
            "select event_type, status from audit_event where job_id = ? order by created_at",
            (dead_message.job_id,),
        )

        self.assertEqual(JobStatus.FAILED, dead_job.status)
        self.assertEqual(dead_message.job_id, dead_payload["job_id"])
        self.assertIn("job.failure.dead", [row["event_type"] for row in dead_audit])


if __name__ == "__main__":
    unittest.main()
