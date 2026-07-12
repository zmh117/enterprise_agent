from __future__ import annotations

import json
import logging
from typing import Any

from app.modules.message_bus.application.message_publisher import (
    AttachmentTaskHandler,
    AttachmentTaskMessage,
)
from app.shared.config import QueueSettings

logger = logging.getLogger(__name__)


class RabbitMQAttachmentConsumer:
    def __init__(self, rabbitmq_url: str, queue: QueueSettings) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue = queue

    def consume_attachments(self, handler: AttachmentTaskHandler) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ consuming") from exc
        connection: Any = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self.queue.attachment_queue, durable=True)
            channel.queue_declare(
                queue=self.queue.attachment_retry_queue,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": self.queue.attachment_queue,
                },
            )
            channel.queue_declare(queue=self.queue.attachment_dead_queue, durable=True)
            channel.basic_qos(prefetch_count=1)

            def on_message(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                del properties
                payload = json.loads(body.decode())
                handler(
                    AttachmentTaskMessage(
                        attachment_id=str(payload["attachment_id"]),
                        correlation_id=str(payload.get("correlation_id") or ""),
                    )
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=self.queue.attachment_queue, on_message_callback=on_message)
            channel.start_consuming()
        finally:
            connection.close()
