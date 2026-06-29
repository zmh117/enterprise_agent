from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.modules.message_bus.application.message_publisher import AgentJobHandler, AgentJobMessage
from app.shared.config import QueueSettings

logger = logging.getLogger(__name__)


class RabbitMQConsumer:
    def __init__(
        self,
        rabbitmq_url: str,
        queue: QueueSettings,
        *,
        heartbeat_seconds: int | None = None,
        reconnect_seconds: int | None = None,
    ) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue = queue
        self.heartbeat_seconds = heartbeat_seconds or queue.consumer_heartbeat_seconds
        self.reconnect_seconds = reconnect_seconds or queue.consumer_reconnect_seconds

    def consume_agent_jobs(self, handler: AgentJobHandler) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ consuming") from exc

        while True:
            connection: Any | None = None
            try:
                parameters = pika.URLParameters(self.rabbitmq_url)
                parameters.heartbeat = self.heartbeat_seconds
                parameters.blocked_connection_timeout = self.heartbeat_seconds + 60
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                channel.queue_declare(queue=self.queue.job_queue, durable=True)
                channel.basic_qos(prefetch_count=1)

                def on_message(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                    payload = json.loads(body.decode("utf-8"))
                    try:
                        handler(
                            AgentJobMessage(
                                job_id=payload["job_id"],
                                correlation_id=payload.get("correlation_id", ""),
                            )
                        )
                    except Exception:
                        logger.exception("Agent job handler failed before ack")
                        if ch.is_open:
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        return
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_consume(queue=self.queue.job_queue, on_message_callback=on_message)
                logger.info(
                    "RabbitMQ consumer started queue=%s heartbeat=%s",
                    self.queue.job_queue,
                    self.heartbeat_seconds,
                )
                channel.start_consuming()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception(
                    "RabbitMQ consumer connection lost; reconnecting in %s seconds",
                    self.reconnect_seconds,
                )
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        logger.debug("RabbitMQ connection close after error failed", exc_info=True)
                time.sleep(self.reconnect_seconds)
