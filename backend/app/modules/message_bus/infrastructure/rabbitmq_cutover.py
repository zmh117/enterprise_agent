from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RabbitMQExactQueueScanner:
    def __init__(self, rabbitmq_url: str) -> None:
        self.rabbitmq_url = rabbitmq_url

    def inspect_exact(self, queue_names: list[str]) -> dict[str, dict[str, object]]:
        connection = self._connection()
        try:
            return {
                name: self._passive_queue_summary(connection, name)
                for name in queue_names
            }
        finally:
            connection.close()

    def scan_exact(
        self,
        *,
        queue_name: str,
        limit: int,
        apply: bool,
        process: Callable[[bytes], dict[str, object]],
    ) -> dict[str, object]:
        connection = self._connection()
        channel: Any | None = None
        deliveries: list[tuple[int, dict[str, object]]] = []
        try:
            channel = connection.channel()
            state = channel.queue_declare(queue=queue_name, passive=True).method
            initial_messages = int(state.message_count)
            consumers = int(state.consumer_count)
            if apply and consumers:
                raise RuntimeError(
                    f"Exact queue {queue_name} still has {consumers} consumers"
                )
            scan_count = min(initial_messages, max(0, int(limit)))
            for _ in range(scan_count):
                method, _, body = channel.basic_get(queue=queue_name, auto_ack=False)
                if method is None:
                    break
                try:
                    result = process(body)
                except Exception:
                    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    raise
                deliveries.append((method.delivery_tag, result))
            for delivery_tag, result in deliveries:
                if apply and result.get("disposition") == "ack":
                    channel.basic_ack(delivery_tag=delivery_tag)
                else:
                    channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
            return {
                "name": queue_name,
                "exists": True,
                "initial_messages": initial_messages,
                "consumers": consumers,
                "scanned": len(deliveries),
                "scan_limit": max(0, int(limit)),
                "truncated": initial_messages > len(deliveries),
                "results": [result for _, result in deliveries],
            }
        except Exception:
            if channel is not None and channel.is_open:
                for delivery_tag, _ in deliveries:
                    try:
                        channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                    except Exception:
                        break
            raise
        finally:
            connection.close()

    def delete_exact_empty_unused(self, queue_names: list[str]) -> list[str]:
        connection = self._connection()
        deleted: list[str] = []
        try:
            for name in queue_names:
                summary = self._passive_queue_summary(connection, name)
                if not summary["exists"]:
                    continue
                if summary["messages"] or summary["consumers"]:
                    raise RuntimeError(
                        f"Exact queue {name} is not empty and unused: {summary}"
                    )
                channel = connection.channel()
                channel.queue_delete(
                    queue=name,
                    if_empty=True,
                    if_unused=True,
                )
                channel.close()
                deleted.append(name)
            return deleted
        finally:
            connection.close()

    def _connection(self) -> Any:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ cutover") from exc
        return pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))

    @staticmethod
    def _passive_queue_summary(connection: Any, name: str) -> dict[str, object]:
        channel = connection.channel()
        try:
            method = channel.queue_declare(queue=name, passive=True).method
            return {
                "exists": True,
                "messages": int(method.message_count),
                "consumers": int(method.consumer_count),
            }
        except Exception:
            return {"exists": False, "messages": 0, "consumers": 0}
        finally:
            if channel.is_open:
                channel.close()
