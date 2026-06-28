from __future__ import annotations

import json

from app.shared.config import QueueSettings


class RabbitMQPublisher:
    def __init__(self, rabbitmq_url: str, queue: QueueSettings) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue = queue

    def publish_agent_job(self, job_id: str, correlation_id: str) -> None:
        self._publish(self.queue.job_queue, {"job_id": job_id, "correlation_id": correlation_id})

    def publish_retry(self, job_id: str, correlation_id: str, delay_seconds: int) -> None:
        self._publish(
            self.queue.retry_queue,
            {"job_id": job_id, "correlation_id": correlation_id, "delay_seconds": delay_seconds},
        )

    def publish_dead_letter(self, job_id: str, correlation_id: str, reason: str) -> None:
        self._publish(
            self.queue.dead_queue,
            {"job_id": job_id, "correlation_id": correlation_id, "reason": reason},
        )

    def _publish(self, queue_name: str, payload: dict[str, object]) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ publishing") from exc
        connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        try:
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(payload).encode("utf-8"),
                properties=pika.BasicProperties(delivery_mode=2),
            )
        finally:
            connection.close()
