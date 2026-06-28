from __future__ import annotations

import json
from typing import Any

from app.modules.message_bus.application.message_publisher import AgentJobHandler, AgentJobMessage
from app.shared.config import QueueSettings


class RabbitMQConsumer:
    def __init__(self, rabbitmq_url: str, queue: QueueSettings) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue = queue

    def consume_agent_jobs(self, handler: AgentJobHandler) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ consuming") from exc

        connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        channel = connection.channel()
        channel.queue_declare(queue=self.queue.job_queue, durable=True)

        def on_message(ch: Any, method: Any, properties: Any, body: bytes) -> None:
            payload = json.loads(body.decode("utf-8"))
            handler(
                AgentJobMessage(
                    job_id=payload["job_id"],
                    correlation_id=payload.get("correlation_id", ""),
                )
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=self.queue.job_queue, on_message_callback=on_message)
        channel.start_consuming()
