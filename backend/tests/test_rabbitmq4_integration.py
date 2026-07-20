from __future__ import annotations

import json
import os
import time
import unittest
import uuid

from app.modules.message_bus.infrastructure.rabbitmq_publisher import RabbitMQPublisher
from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    declare_agent_job_topology,
)
from app.shared.config import QueueSettings

_RUN = os.getenv("RUN_RABBITMQ4_INTEGRATION") == "1"


@unittest.skipUnless(_RUN, "set RUN_RABBITMQ4_INTEGRATION=1 to run against RabbitMQ 4")
class RabbitMQ4IntegrationTests(unittest.TestCase):
    """Opt-in broker compatibility test using isolated temporary queues."""

    def setUp(self) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency is required in CI
            self.skipTest(str(exc))

        suffix = uuid.uuid4().hex
        self.rabbitmq_url = os.getenv(
            "RABBITMQ_TEST_URL", "amqp://guest:guest@127.0.0.1:5672/"
        )
        self.queues = QueueSettings(
            job_queue=f"agent.compat.job.{suffix}",
            retry_queue=f"agent.compat.retry.{suffix}",
            dead_queue=f"agent.compat.dead.{suffix}",
        )
        self.connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        self.channel = self.connection.channel()

    def tearDown(self) -> None:
        if not hasattr(self, "channel"):
            return
        for queue_name in (
            self.queues.job_queue,
            self.queues.retry_queue,
            self.queues.dead_queue,
        ):
            self.channel.queue_delete(queue=queue_name)
        self.connection.close()

    def test_publisher_is_compatible_with_rabbitmq4_job_retry_and_dead_queues(self) -> None:
        version = self.connection._impl.server_properties["version"]
        if isinstance(version, bytes):
            version = version.decode("ascii")
        self.assertTrue(str(version).startswith("4."), f"RabbitMQ 4 required, got {version}")

        publisher = RabbitMQPublisher(self.rabbitmq_url, self.queues)
        publisher.publish_agent_job("job-smoke", "corr-job")
        publisher.publish_retry("job-retry", "corr-retry", 30)
        publisher.publish_dead_letter("job-dead", "corr-dead", "non-retryable")

        expected = {
            self.queues.job_queue: {
                "job_id": "job-smoke",
                "correlation_id": "corr-job",
            },
            self.queues.retry_queue: {
                "job_id": "job-retry",
                "correlation_id": "corr-retry",
            },
            self.queues.dead_queue: {
                "job_id": "job-dead",
                "correlation_id": "corr-dead",
                "reason": "non-retryable",
            },
        }

        for queue_name, expected_payload in expected.items():
            # Repeating the durable declaration must remain idempotent on RabbitMQ 4.
            declare_agent_job_topology(self.channel, self.queues)
            method, properties, body = self.channel.basic_get(queue=queue_name, auto_ack=False)
            self.assertIsNotNone(method, f"No message in {queue_name}")
            self.assertEqual(2, properties.delivery_mode)
            self.assertEqual(expected_payload, json.loads(body.decode("utf-8")))
            self.channel.basic_ack(method.delivery_tag)

            state = self.channel.queue_declare(queue=queue_name, durable=True, passive=True)
            self.assertEqual(0, state.method.message_count)

    def test_retry_expiration_dead_letters_back_to_main_queue(self) -> None:
        publisher = RabbitMQPublisher(self.rabbitmq_url, self.queues)
        publisher.publish_retry("job-delayed", "corr-delayed", 1)

        deadline = time.monotonic() + 8
        payload: dict[str, object] | None = None
        while time.monotonic() < deadline:
            method, _, body = self.channel.basic_get(
                queue=self.queues.job_queue, auto_ack=False
            )
            if method is not None:
                payload = json.loads(body.decode("utf-8"))
                self.channel.basic_ack(method.delivery_tag)
                break
            time.sleep(0.1)

        self.assertEqual(
            {"job_id": "job-delayed", "correlation_id": "corr-delayed"}, payload
        )
        retry_state = self.channel.queue_declare(
            queue=self.queues.retry_queue, passive=True
        )
        self.assertEqual(0, retry_state.method.message_count)


if __name__ == "__main__":
    unittest.main()
