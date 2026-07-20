from __future__ import annotations

from typing import Any

from app.shared.config import QueueSettings


def retry_queue_arguments(queue: QueueSettings) -> dict[str, object]:
    return {
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": queue.job_queue,
    }


def declare_agent_job_topology(channel: Any, queue: QueueSettings) -> None:
    """Declare only the current topology; never redeclare the incompatible legacy queue."""
    channel.queue_declare(queue=queue.dead_queue, durable=True)
    channel.queue_declare(queue=queue.job_queue, durable=True)
    channel.queue_declare(
        queue=queue.retry_queue,
        durable=True,
        arguments=retry_queue_arguments(queue),
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
                **_queue_summary(channel, queue.retry_queue),
                "arguments": retry_queue_arguments(queue),
            },
            "dead_queue": _queue_summary(channel, queue.dead_queue),
            "legacy_retry_queue": {
                "name": queue.legacy_retry_queue,
                **_passive_queue_summary(channel, queue.legacy_retry_queue),
            },
        }
        return result
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
