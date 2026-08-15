"""Executable baseline for the attachment worker contract before its file-worker cutover.

Confirmed-current contract:

* the durable queue names remain ``agent.attachment.{queue,retry.queue,dead.queue}``;
* work messages contain only ``attachment_id`` and ``correlation_id``;
* the retry queue dead-letters to the work queue and carries the same identifiers;
* a message is acknowledged only after the handler returns successfully;
* ``message_id + ordinal`` is the source idempotency boundary; and
* a WAITING_INPUT Job is released only after every attachment reaches a terminal state.

These assertions intentionally survive the service rename from attachment-worker to
file-worker. They protect in-flight RabbitMQ messages during that cutover.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.agent.application.agent_context_builder import (
    ATTACHMENT_ONLY_USER_QUESTION,
)
from app.modules.channel.domain.channel_event import ChannelAttachment
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.infrastructure.rabbitmq_attachment_consumer import (
    RabbitMQAttachmentConsumer,
)
from app.modules.message_bus.infrastructure.rabbitmq_publisher import RabbitMQPublisher
from app.shared.config import AttachmentSettings, QueueSettings
from backend.tests.test_continuous_multimodal_conversations import (
    FakeDownloader,
    RetryingDownloader,
    multimodal_container,
)


class _Method:
    delivery_tag = 17


class _Channel:
    def __init__(self, *, body: bytes | None = None) -> None:
        self.body = body
        self.declarations: list[dict[str, Any]] = []
        self.prefetch_count: int | None = None
        self.consumer_queue = ""
        self.callback: Any = None
        self.acks: list[int] = []
        self.published: list[dict[str, Any]] = []

    def queue_declare(self, **kwargs: Any) -> None:
        self.declarations.append(kwargs)

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

    def confirm_delivery(self) -> None:
        return None

    def basic_publish(self, **kwargs: Any) -> bool:
        self.published.append(kwargs)
        return True


class _Connection:
    def __init__(self, channel: _Channel) -> None:
        self._channel = channel
        self.closed = False

    def channel(self) -> _Channel:
        return self._channel

    def close(self) -> None:
        self.closed = True


def _install_fake_pika(monkeypatch: pytest.MonkeyPatch, channel: _Channel) -> _Connection:
    connection = _Connection(channel)
    fake_pika = SimpleNamespace(
        URLParameters=lambda value: value,
        BlockingConnection=lambda _parameters: connection,
        BasicProperties=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setitem(sys.modules, "pika", fake_pika)
    return connection


def test_attachment_consumer_preserves_durable_topology_and_message_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = QueueSettings()
    channel = _Channel(
        body=json.dumps(
            {"attachment_id": "attachment-1", "correlation_id": "correlation-1"}
        ).encode("utf-8")
    )
    connection = _install_fake_pika(monkeypatch, channel)
    received: list[object] = []

    RabbitMQAttachmentConsumer("amqp://test", queue).consume_attachments(received.append)

    assert channel.declarations == [
        {"queue": queue.attachment_queue, "durable": True},
        {
            "queue": queue.attachment_retry_queue,
            "durable": True,
            "arguments": {
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": queue.attachment_queue,
            },
        },
        {"queue": queue.attachment_dead_queue, "durable": True},
    ]
    assert channel.prefetch_count == 1
    assert channel.consumer_queue == queue.attachment_queue
    assert vars(received[0]) == {
        "attachment_id": "attachment-1",
        "correlation_id": "correlation-1",
    }
    assert channel.acks == [17]
    assert connection.closed is True


def test_attachment_consumer_does_not_ack_when_handler_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _Channel(body=b'{"attachment_id":"attachment-1","correlation_id":"c"}')
    connection = _install_fake_pika(monkeypatch, channel)

    def fail(_message: object) -> None:
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        RabbitMQAttachmentConsumer("amqp://test", QueueSettings()).consume_attachments(fail)

    assert channel.acks == []
    assert connection.closed is True


def test_attachment_publisher_preserves_work_and_retry_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = QueueSettings()
    channel = _Channel()
    _install_fake_pika(monkeypatch, channel)
    publisher = RabbitMQPublisher("amqp://test", queue)

    publisher.publish_attachment("attachment-1", "correlation-1")
    publisher.publish_attachment_retry("attachment-1", "correlation-1", 30)

    work, retry = channel.published
    assert work["routing_key"] == queue.attachment_queue
    assert json.loads(work["body"].decode("utf-8")) == {
        "attachment_id": "attachment-1",
        "correlation_id": "correlation-1",
    }
    assert retry["routing_key"] == queue.attachment_retry_queue
    assert json.loads(retry["body"].decode("utf-8")) == {
        "attachment_id": "attachment-1",
        "correlation_id": "correlation-1",
        "delay_seconds": 30,
    }
    assert retry["properties"].delivery_mode == 2
    assert retry["properties"].expiration == "30000"


def test_attachment_source_idempotency_and_all_terminal_release_boundary() -> None:
    runtime = multimodal_container()
    runtime.attachment_service.settings = replace(  # type: ignore[union-attr]
        runtime.attachment_service.settings,  # type: ignore[union-attr]
        max_file_bytes=1024,
    )
    attachments = (
        ChannelAttachment(
            media_type="document",
            file_name="first.md",
            source_credential="download-first",
        ),
        ChannelAttachment(
            media_type="document",
            file_name="second.md",
            source_credential="download-second",
        ),
    )
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="attachment-worker-contract",
            requester_id="user_local_admin",
            external_conversation_id="attachment-worker-contract",
            external_event_id="attachment-worker-contract-event",
            external_message_id="attachment-worker-contract-message",
            user_message="",
            source_channel="dingding_stream",
            source_connector_id="connector-dingtalk-stream-default",
            conversation_type="direct",
            bot_identity="robot-redacted",
            attachments=attachments,
        )
    )
    tasks = list(runtime.message_bus.attachments)
    assert len(tasks) == 2

    original_attachment = runtime.agent_repository.get_attachment(tasks[0].attachment_id)
    duplicate = runtime.agent_repository.add_attachment(
        message_id=original_attachment.message_id,
        job_id=job.id,
        ordinal=original_attachment.ordinal,
        media_type="document",
        file_name="ignored-duplicate-name.md",
    )
    assert duplicate.id == tasks[0].attachment_id
    assert runtime.agent_repository.count_rows("message_attachment") == 2

    runtime.attachment_service.downloader = FakeDownloader(  # type: ignore[union-attr]
        {
            "download-first": b"first",
            "download-second": b"second",
        }
    )
    assert runtime.attachment_service.process(tasks[0].attachment_id, "c-1") == "waiting"  # type: ignore[union-attr]
    assert runtime.agent_repository.get_job(job.id).status == JobStatus.WAITING_INPUT
    assert runtime.attachment_service.process(tasks[1].attachment_id, "c-2") == "released"  # type: ignore[union-attr]
    released_job = runtime.agent_repository.get_job(job.id)
    assert released_job.status == JobStatus.PENDING
    assert (
        runtime.agent_executor.context_builder.build(released_job).user_question
        == ATTACHMENT_ONLY_USER_QUESTION
    )


def test_attachment_retry_reuses_source_identity_and_keeps_job_waiting() -> None:
    runtime = multimodal_container()
    runtime.attachment_service.settings = AttachmentSettings(  # type: ignore[union-attr]
        enabled=True,
        max_file_bytes=1024,
    )
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="attachment-retry-contract",
            requester_id="user_local_admin",
            external_conversation_id="attachment-retry-contract",
            external_event_id="attachment-retry-contract-event",
            user_message="",
            source_channel="dingding_stream",
            source_connector_id="connector-dingtalk-stream-default",
            conversation_type="direct",
            bot_identity="robot-redacted",
            attachments=(
                ChannelAttachment(
                    media_type="document",
                    file_name="retry.md",
                    source_credential="download-retry",
                ),
            ),
        )
    )
    task = runtime.message_bus.attachments.popleft()
    runtime.attachment_service.downloader = RetryingDownloader()  # type: ignore[union-attr]

    assert runtime.attachment_service.process(task.attachment_id, "correlation-retry") == "retry"  # type: ignore[union-attr]

    retry_task, delay = runtime.message_bus.attachment_retries.popleft()
    assert retry_task.attachment_id == task.attachment_id
    assert retry_task.correlation_id == "correlation-retry"
    assert delay == 30
    retry_row = runtime.database.execute_one(
        "select retry_count from message_attachment where id = ?",
        (task.attachment_id,),
    )
    assert retry_row is not None
    assert retry_row["retry_count"] == 1
    assert runtime.agent_repository.get_job(job.id).status == JobStatus.WAITING_INPUT
