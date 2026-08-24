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
from app.modules.channel.domain.channel_event import ChannelAttachment, ReplyRoute
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.infrastructure.rabbitmq_attachment_consumer import (
    RabbitMQAttachmentConsumer,
)
from app.modules.message_bus.infrastructure.rabbitmq_publisher import RabbitMQPublisher
from app.shared.config import AttachmentSettings, QueueSettings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from backend.tests.support.file_workspace import (
    FakeDownloader,
    file_workspace_command_kwargs,
    multimodal_container,
)


class RetryingDownloader:
    def download(
        self,
        *,
        download_code: str,
        max_bytes: int,
        connector_id: str = "",
        robot_code: str = "",
    ) -> bytes:
        del download_code, max_bytes, connector_id, robot_code
        raise RetryableExecutionError(
            "temporary",
            safe_message="temporary download failure",
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


class _RejectingImporter:
    def __init__(
        self,
        *,
        safe_message: str = "附件导入被拒绝",
        error_code: str = "document_source_media_type_mismatch",
    ) -> None:
        self.safe_message = safe_message
        self.error_code = error_code

    def import_content(self, **_kwargs: object) -> object:
        raise NonRetryableExecutionError(
            "File Service rejected attachment import",
            safe_message=self.safe_message,
            error_code=self.error_code,
        )


class _CaptureDeliveryAdapter(DeliveryAdapter):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(
        self,
        *,
        connector: object,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        del connector, route
        self.sent.append((title, text))


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
            **file_workspace_command_kwargs(runtime),
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
            **file_workspace_command_kwargs(runtime),
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


def test_attachment_rejection_persists_machine_error_code() -> None:
    runtime = multimodal_container()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="attachment-machine-error-code",
            requester_id="user_local_admin",
            external_conversation_id="attachment-machine-error-code",
            external_event_id="attachment-machine-error-code-event",
            external_message_id="attachment-machine-error-code-message",
            user_message="",
            source_channel="dingding_stream",
            source_connector_id="connector-dingtalk-stream-default",
            conversation_type="direct",
            bot_identity="robot-redacted",
            **file_workspace_command_kwargs(runtime),
            attachments=(
                ChannelAttachment(
                    media_type="document",
                    file_name="safe.md",
                    source_credential="download-safe",
                ),
            ),
        )
    )
    task = runtime.message_bus.attachments.popleft()
    runtime.attachment_service.downloader = FakeDownloader(  # type: ignore[union-attr]
        {"download-safe": b"safe text"}
    )
    runtime.attachment_service.importer = _RejectingImporter()  # type: ignore[union-attr]

    runtime.attachment_service.process(task.attachment_id, "correlation-safe")  # type: ignore[union-attr]

    row = runtime.database.execute_one(
        "select status, failure_code from message_attachment where id = ?",
        (task.attachment_id,),
    )
    assert row == {
        "status": "REJECTED",
        "failure_code": "document_source_media_type_mismatch",
    }
    assert runtime.agent_repository.get_job(job.id).status == JobStatus.FAILED


def test_staged_noncompliant_attachment_notifies_the_originating_conversation_once() -> None:
    runtime = multimodal_container(
        task_file_features={"workspace_enabled": True, "file_mcp_enabled": True}
    )
    application = runtime.business_application_repository.get_by_code(
        "multimodal-test-application"
    )
    command_kwargs = file_workspace_command_kwargs(runtime)
    command_kwargs.update(
        {
            "business_application_id": str(application["id"]),
            "business_application_code": "multimodal-test-application",
            "conversation_mode": "channel",
            "continuous_conversation_enabled": True,
            "attachments_enabled": True,
            "task_file_features": {
                "workspace_enabled": True,
                "file_mcp_enabled": True,
            },
        }
    )
    intake = runtime.create_agent_job_service.stage_attachments(
        CreateAgentJobCommand(
            idempotency_key="staged-invalid-encoding",
            requester_id="user_local_admin",
            external_conversation_id="staged-invalid-encoding-conversation",
            external_event_id="staged-invalid-encoding-event",
            external_message_id="staged-invalid-encoding-message",
            user_message="",
            source_channel="dingding_stream",
            source_connector_id="connector-dingtalk-stream-default",
            conversation_type="direct",
            bot_identity="robot-redacted",
            attachments=(
                ChannelAttachment(
                    media_type="document",
                    file_name="M102200001(1).txt",
                    source_credential="download-invalid-encoding",
                ),
            ),
            **command_kwargs,
        )
    )
    runtime.attachment_service.downloader = FakeDownloader(  # type: ignore[union-attr]
        {"download-invalid-encoding": b"invalid-source-bytes"}
    )
    runtime.attachment_service.importer = _RejectingImporter(  # type: ignore[union-attr]
        safe_message="文件必须使用 UTF-8 编码",
        error_code="file_encoding_invalid",
    )
    adapter = _CaptureDeliveryAdapter()
    runtime.result_delivery_service.adapters["dingtalk_conversation"] = adapter

    assert runtime.attachment_service.process(  # type: ignore[union-attr]
        intake.attachment_ids[0], "correlation-invalid-encoding"
    ) == "staged"
    runtime.delivery_dispatcher.dispatch_pending(limit=10)

    assert adapter.sent == [
        (
            "文件未进入工作区",
            "文件 `M102200001(1).txt` 未进入工作区：文件必须使用 UTF-8 编码。"
            "请修正后重新发送。",
        )
    ]

    assert runtime.attachment_service.process(  # type: ignore[union-attr]
        intake.attachment_ids[0], "correlation-invalid-encoding-retry"
    ) == "staged"
    runtime.delivery_dispatcher.dispatch_pending(limit=10)
    assert len(adapter.sent) == 1
