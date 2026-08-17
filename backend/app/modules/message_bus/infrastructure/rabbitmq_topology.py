from __future__ import annotations

from typing import Any

from app.shared.config import QueueSettings


def declare_agent_job_topology(channel: Any, queue: QueueSettings) -> None:
    """Declare the Outbox target and explicit poison-message quarantine queue."""
    channel.queue_declare(queue=queue.dead_queue, durable=True)
    channel.queue_declare(queue=queue.job_queue, durable=True)


def declare_channel_event_topology(channel: Any, queue: QueueSettings) -> None:
    channel.queue_declare(queue=queue.channel_dead_queue, durable=True)
    channel.queue_declare(
        queue=queue.channel_queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": queue.channel_dead_queue,
        },
    )


def inspect_agent_job_topology(rabbitmq_url: str, queue: QueueSettings) -> dict[str, object]:
    try:
        import pika
    except ModuleNotFoundError as exc:
        raise RuntimeError("pika is required for RabbitMQ topology checks") from exc

    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    try:
        channel = connection.channel()
        declare_agent_job_topology(channel, queue)
        result: dict[str, object] = {
            "job_queue": _queue_summary(channel, queue.job_queue),
            "retry_queue": {
                "name": queue.retry_queue,
                **_passive_queue_summary(connection.channel(), queue.retry_queue),
            },
            "dead_queue": {
                "name": queue.dead_queue,
                **_passive_queue_summary(connection.channel(), queue.dead_queue),
            },
            "legacy_retry_queue": {
                "name": queue.legacy_retry_queue,
                **_passive_queue_summary(
                    connection.channel(),
                    queue.legacy_retry_queue,
                ),
            },
        }
        return result
    finally:
        connection.close()


def inspect_agent_job_topology_read_only(
    rabbitmq_url: str,
    queue: QueueSettings,
) -> dict[str, object]:
    """Inspect queue counts without declaring, binding, consuming, or publishing."""
    try:
        import pika
    except ModuleNotFoundError as exc:
        raise RuntimeError("pika is required for RabbitMQ topology checks") from exc

    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    try:
        return {
            label: {
                "name": name,
                **_passive_queue_summary(connection.channel(), name),
            }
            for label, name in (
                ("job_queue", queue.job_queue),
                ("retry_queue", queue.retry_queue),
                ("dead_queue", queue.dead_queue),
                ("legacy_retry_queue", queue.legacy_retry_queue),
            )
        }
    finally:
        connection.close()


def _queue_summary(channel: Any, name: str) -> dict[str, object]:
    method = channel.queue_declare(queue=name, durable=True, passive=True).method
    return {
        "name": name,
        "exists": True,
        "messages": int(method.message_count),
        "consumers": int(method.consumer_count),
    }


def _passive_queue_summary(channel: Any, name: str) -> dict[str, object]:
    try:
        method = channel.queue_declare(queue=name, passive=True).method
        return {
            "exists": True,
            "messages": int(method.message_count),
            "consumers": int(method.consumer_count),
        }
    except Exception:
        # RabbitMQ closes a channel after a passive declare of a missing queue.
        return {"exists": False, "messages": 0, "consumers": 0}
    finally:
        if channel.is_open:
            channel.close()
