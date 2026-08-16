from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from app.modules.message_bus.application.message_publisher import (
    AgentJobHandler,
    AgentJobMessage,
    ChannelEventHandler,
    ChannelEventMessage,
    WebhookEventHandler,
    WebhookEventMessage,
)
from app.shared.config import QueueSettings
from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    declare_agent_job_topology,
    declare_channel_event_topology,
)

logger = logging.getLogger(__name__)

_MAX_MESSAGE_IDENTIFIER_CHARS = 240
_MAX_CORRELATION_ID_CHARS = 240
_MAX_CLASSIFICATION_CHARS = 80
_MAX_AGENT_JOB_ENVELOPE_BYTES = 64 * 1024


class AgentJobEnvelopeError(ValueError):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification[:_MAX_CLASSIFICATION_CHARS]


def decode_agent_job_message(body: bytes, *, redelivered: bool) -> AgentJobMessage:
    if len(body) > _MAX_AGENT_JOB_ENVELOPE_BYTES:
        raise AgentJobEnvelopeError("envelope_too_large")
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentJobEnvelopeError("invalid_utf8") from exc
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise AgentJobEnvelopeError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise AgentJobEnvelopeError("invalid_object")

    event_id = _required_message_identifier(payload, "event_id")
    job_id = _required_message_identifier(payload, "job_id")
    correlation_value = payload.get("correlation_id", "")
    if not isinstance(correlation_value, str):
        raise AgentJobEnvelopeError("invalid_correlation_id")
    correlation_id = correlation_value.strip()
    if len(correlation_id) > _MAX_CORRELATION_ID_CHARS:
        raise AgentJobEnvelopeError("invalid_correlation_id")
    return AgentJobMessage(
        event_id=event_id,
        job_id=job_id,
        correlation_id=correlation_id,
        redelivered=redelivered,
    )


def process_agent_job_delivery(
    channel: Any,
    method: Any,
    properties: Any,
    body: bytes,
    handler: AgentJobHandler,
    *,
    dead_queue: str,
    properties_factory: Callable[[Any, str], Any] | None = None,
) -> str:
    """Apply the bounded broker delivery policy without changing Job state."""
    try:
        message = decode_agent_job_message(
            body,
            redelivered=bool(method.redelivered),
        )
    except AgentJobEnvelopeError as exc:
        classification = f"envelope_{exc.classification}"
        logger.warning(
            "Agent job message quarantined classification=%s body_bytes=%s",
            classification,
            len(body),
        )
        _quarantine_agent_job_delivery(
            channel,
            method,
            properties,
            body,
            dead_queue=dead_queue,
            classification=classification,
            properties_factory=properties_factory,
        )
        return "quarantined"

    try:
        handler(message)
    except Exception:
        if not bool(method.redelivered):
            logger.warning(
                "Agent job handler failed classification=handler_failed_first_delivery "
                "event_id=%s job_id=%s",
                message.event_id,
                message.job_id,
            )
            if not channel.is_open:
                raise RuntimeError("RabbitMQ channel closed before agent job requeue")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return "requeued"
        classification = "handler_failed_after_redelivery"
        logger.warning(
            "Agent job message quarantined classification=%s event_id=%s job_id=%s",
            classification,
            message.event_id,
            message.job_id,
        )
        _quarantine_agent_job_delivery(
            channel,
            method,
            properties,
            body,
            dead_queue=dead_queue,
            classification=classification,
            properties_factory=properties_factory,
        )
        return "quarantined"

    channel.basic_ack(delivery_tag=method.delivery_tag)
    return "acked"


def _required_message_identifier(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise AgentJobEnvelopeError(f"invalid_{field}")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_MESSAGE_IDENTIFIER_CHARS:
        raise AgentJobEnvelopeError(f"invalid_{field}")
    return normalized


def _quarantine_agent_job_delivery(
    channel: Any,
    method: Any,
    properties: Any,
    body: bytes,
    *,
    dead_queue: str,
    classification: str,
    properties_factory: Callable[[Any, str], Any] | None,
) -> None:
    if not channel.is_open:
        raise RuntimeError("RabbitMQ channel closed before agent job quarantine")
    factory = properties_factory or _quarantine_properties
    confirmed = channel.basic_publish(
        exchange="",
        routing_key=dead_queue,
        body=body,
        properties=factory(properties, classification[:_MAX_CLASSIFICATION_CHARS]),
        mandatory=True,
    )
    if confirmed is False:
        raise RuntimeError("RabbitMQ quarantine publish confirm failed")
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _quarantine_properties(original: Any, classification: str) -> Any:
    try:
        import pika
    except ModuleNotFoundError as exc:
        raise RuntimeError("pika is required for RabbitMQ consuming") from exc

    def bounded_property(name: str) -> str | None:
        value = getattr(original, name, None)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized[:_MAX_MESSAGE_IDENTIFIER_CHARS] or None

    return pika.BasicProperties(
        delivery_mode=2,
        content_type="application/json",
        correlation_id=bounded_property("correlation_id"),
        message_id=bounded_property("message_id"),
        headers={"x-agent-quarantine-classification": classification},
    )


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
        self._consume_agent_jobs(handler)

    def consume_webhook_events(self, handler: WebhookEventHandler) -> None:
        self._consume_webhook_events(handler)

    def consume_channel_events(self, handler: ChannelEventHandler) -> None:
        self._consume_channel_events(handler)

    def _consume_agent_jobs(self, handler: AgentJobHandler) -> None:
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
                declare_agent_job_topology(channel, self.queue)
                channel.confirm_delivery()
                channel.basic_qos(prefetch_count=1)

                def on_message(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                    process_agent_job_delivery(
                        ch,
                        method,
                        properties,
                        body,
                        handler,
                        dead_queue=self.queue.dead_queue,
                    )

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

    def _consume_webhook_events(self, handler: WebhookEventHandler) -> None:
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
                channel.queue_declare(queue=self.queue.webhook_dead_queue, durable=True)
                channel.queue_declare(
                    queue=self.queue.webhook_queue,
                    durable=True,
                    arguments={
                        "x-dead-letter-exchange": "",
                        "x-dead-letter-routing-key": self.queue.webhook_dead_queue,
                    },
                )
                channel.basic_qos(prefetch_count=1)

                def on_message(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                    del properties
                    payload = json.loads(body.decode("utf-8"))
                    try:
                        handler(
                            WebhookEventMessage(
                                webhook_event_id=payload["webhook_event_id"],
                                correlation_id=payload.get("correlation_id", ""),
                            )
                        )
                    except Exception:
                        logger.exception("Webhook event handler failed before ack")
                        if ch.is_open:
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        return
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_consume(
                    queue=self.queue.webhook_queue, on_message_callback=on_message
                )
                logger.info(
                    "RabbitMQ Webhook consumer started queue=%s heartbeat=%s",
                    self.queue.webhook_queue,
                    self.heartbeat_seconds,
                )
                channel.start_consuming()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception(
                    "RabbitMQ Webhook consumer connection lost; reconnecting in %s seconds",
                    self.reconnect_seconds,
                )
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        logger.debug("RabbitMQ connection close after error failed", exc_info=True)
                time.sleep(self.reconnect_seconds)

    def _consume_channel_events(self, handler: ChannelEventHandler) -> None:
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
                declare_channel_event_topology(channel, self.queue)
                channel.basic_qos(prefetch_count=1)

                def on_message(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                    del properties
                    payload = json.loads(body.decode("utf-8"))
                    try:
                        handler(
                            ChannelEventMessage(
                                channel_event_id=payload["channel_event_id"],
                                correlation_id=payload.get("correlation_id", ""),
                            )
                        )
                    except Exception:
                        logger.exception("Channel event handler failed before ack")
                        if ch.is_open:
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        return
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_consume(
                    queue=self.queue.channel_queue, on_message_callback=on_message
                )
                logger.info("RabbitMQ Channel consumer started queue=%s", self.queue.channel_queue)
                channel.start_consuming()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception(
                    "RabbitMQ Channel consumer connection lost; reconnecting in %s seconds",
                    self.reconnect_seconds,
                )
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        logger.debug("RabbitMQ connection close after error failed", exc_info=True)
                time.sleep(self.reconnect_seconds)
