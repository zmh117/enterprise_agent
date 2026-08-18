from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.message_bus.application.message_publisher import (
    FileProcessingDisposition,
    FileProcessingTaskMessage,
    FileProcessingTaskResult,
)
from app.modules.message_bus.infrastructure.rabbitmq_file_processing import (
    RabbitMQFileProcessingConsumer,
    RabbitMQFileProcessingPublisher,
)
from app.shared.config import QueueSettings


class _Method:
    delivery_tag = 23
    redelivered = True


class _Channel:
    def __init__(self, body: bytes | None = None) -> None:
        self.body = body
        self.declarations: list[dict[str, Any]] = []
        self.published: list[dict[str, Any]] = []
        self.acks: list[int] = []
        self.callback: Any = None
        self.consumer_queue = ""
        self.prefetch_count = 0

    def queue_declare(self, **values: Any) -> None:
        self.declarations.append(values)

    def confirm_delivery(self) -> None:
        return None

    def basic_publish(self, **values: Any) -> bool:
        self.published.append(values)
        return True

    def basic_qos(self, *, prefetch_count: int) -> None:
        self.prefetch_count = prefetch_count

    def basic_consume(self, *, queue: str, on_message_callback: Any) -> None:
        self.consumer_queue = queue
        self.callback = on_message_callback

    def start_consuming(self) -> None:
        if self.body is not None:
            self.callback(self, _Method(), object(), self.body)

    def basic_ack(self, *, delivery_tag: int) -> None:
        self.acks.append(delivery_tag)


class _Connection:
    def __init__(self, channel: _Channel) -> None:
        self._channel = channel

    def channel(self) -> _Channel:
        return self._channel

    def close(self) -> None:
        return None


def _pika(monkeypatch: pytest.MonkeyPatch, channel: _Channel) -> None:
    connection = _Connection(channel)
    monkeypatch.setitem(
        sys.modules,
        "pika",
        SimpleNamespace(
            URLParameters=lambda value: value,
            BlockingConnection=lambda _: connection,
            BasicProperties=lambda **values: SimpleNamespace(**values),
        ),
    )


def _message() -> FileProcessingTaskMessage:
    return FileProcessingTaskMessage(
        contract_version="file-processing/v1",
        run_id="run-1",
        source_version_id="version-1",
        profile_hash="a" * 64,
        attempt=0,
        correlation_id="correlation-1",
    )


def test_processing_publisher_uses_durable_work_retry_dead_topology_and_safe_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = QueueSettings()
    channel = _Channel()
    _pika(monkeypatch, channel)
    publisher = RabbitMQFileProcessingPublisher("amqp://test", queue)

    publisher.publish_message(_message())
    publisher.publish_retry(_message(), delay_seconds=30)
    publisher.publish_dead(_message(), error_code="docling_format_rejected")

    assert channel.declarations[:3] == [
        {"queue": queue.file_processing_dead_queue, "durable": True},
        {
            "queue": queue.file_processing_queue,
            "durable": True,
            "arguments": {
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": queue.file_processing_dead_queue,
            },
        },
        {
            "queue": queue.file_processing_retry_queue,
            "durable": True,
            "arguments": {
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": queue.file_processing_queue,
            },
        },
    ]
    work, retry, dead = channel.published
    assert work["routing_key"] == queue.file_processing_queue
    assert set(json.loads(work["body"])) == {
        "contract_version",
        "run_id",
        "source_version_id",
        "profile_hash",
        "attempt",
        "correlation_id",
    }
    assert retry["routing_key"] == queue.file_processing_retry_queue
    assert retry["properties"].expiration == "30000"
    assert json.loads(retry["body"])["attempt"] == 1
    assert dead["routing_key"] == queue.file_processing_dead_queue
    assert json.loads(dead["body"])["dead_letter_error_code"] == "docling_format_rejected"


def test_processing_consumer_validates_message_and_acks_only_after_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = QueueSettings()
    channel = _Channel(json.dumps(_message().safe_payload()).encode())
    _pika(monkeypatch, channel)
    received: list[FileProcessingTaskMessage] = []

    def handle(message: FileProcessingTaskMessage) -> FileProcessingTaskResult:
        received.append(message)
        return FileProcessingTaskResult(FileProcessingDisposition.ACK)

    RabbitMQFileProcessingConsumer("amqp://test", queue).consume(handle)

    assert received[0].redelivered is True
    assert channel.prefetch_count == 1
    assert channel.consumer_queue == queue.file_processing_queue
    assert channel.acks == [23]


def test_processing_consumer_quarantines_malformed_input_without_republishing_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_body = b'{"token":"must-not-enter-dead-letter"}'
    channel = _Channel(secret_body)
    _pika(monkeypatch, channel)

    RabbitMQFileProcessingConsumer("amqp://test", QueueSettings()).consume(
        lambda _: FileProcessingTaskResult(FileProcessingDisposition.ACK)
    )

    assert channel.acks == [23]
    assert len(channel.published) == 1
    dead_body = channel.published[0]["body"]
    assert b"must-not-enter-dead-letter" not in dead_body
    assert json.loads(dead_body) == {
        "contract_version": "file-processing-dead/v1",
        "dead_letter_error_code": "processing_message_invalid",
    }
