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

    def publish_attachment(self, attachment_id: str, correlation_id: str) -> None:
        self._publish(
            self.queue.attachment_queue,
            {"attachment_id": attachment_id, "correlation_id": correlation_id},
        )

    def publish_attachment_retry(
        self, attachment_id: str, correlation_id: str, delay_seconds: int
    ) -> None:
        self._publish_attachment_retry(
            {
                "attachment_id": attachment_id,
                "correlation_id": correlation_id,
                "delay_seconds": delay_seconds,
            },
            delay_seconds,
        )

    def publish_attachment_dead_letter(
        self, attachment_id: str, correlation_id: str, reason: str
    ) -> None:
        self._publish(
            self.queue.attachment_dead_queue,
            {"attachment_id": attachment_id, "correlation_id": correlation_id, "reason": reason},
        )

    def publish_webhook_event(self, webhook_event_id: str, correlation_id: str) -> None:
        self._publish_webhook(
            {"webhook_event_id": webhook_event_id, "correlation_id": correlation_id},
        )

    def publish_webhook_dead_letter(
        self, webhook_event_id: str, correlation_id: str, reason: str
    ) -> None:
        self._publish(
            self.queue.webhook_dead_queue,
            {
                "webhook_event_id": webhook_event_id,
                "correlation_id": correlation_id,
                "reason": reason,
            },
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
            channel.confirm_delivery()
            confirmed = channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(payload).encode("utf-8"),
                properties=pika.BasicProperties(delivery_mode=2),
            )
            if confirmed is False:
                raise RuntimeError("RabbitMQ publisher confirm failed")
        finally:
            connection.close()

    def _publish_attachment_retry(
        self, payload: dict[str, object], delay_seconds: int
    ) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ publishing") from exc
        connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        try:
            channel = connection.channel()
            channel.queue_declare(
                queue=self.queue.attachment_retry_queue,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": self.queue.attachment_queue,
                },
            )
            channel.basic_publish(
                exchange="",
                routing_key=self.queue.attachment_retry_queue,
                body=json.dumps(payload).encode("utf-8"),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    expiration=str(max(delay_seconds, 1) * 1000),
                ),
            )
        finally:
            connection.close()

    def _publish_webhook(self, payload: dict[str, object]) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ publishing") from exc
        connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self.queue.webhook_dead_queue, durable=True)
            channel.queue_declare(
                queue=self.queue.webhook_queue,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": self.queue.webhook_dead_queue,
                },
            )
            channel.confirm_delivery()
            confirmed = channel.basic_publish(
                exchange="",
                routing_key=self.queue.webhook_queue,
                body=json.dumps(payload).encode("utf-8"),
                properties=pika.BasicProperties(delivery_mode=2),
            )
            if confirmed is False:
                raise RuntimeError("RabbitMQ publisher confirm failed")
        finally:
            connection.close()
