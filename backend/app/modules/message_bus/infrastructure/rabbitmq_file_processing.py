from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.document_processing.repository import DocumentProcessingRepository
from app.modules.message_bus.application.message_publisher import (
    AssemblyTaskMessage,
    DocumentProcessingStageMessage,
    FileProcessingDisposition,
    FileProcessingTaskHandler,
    FileProcessingTaskMessage,
    PictureProcessingTaskMessage,
)
from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    declare_file_processing_topology,
)
from app.shared.config import QueueSettings
from app.shared.database import assert_external_io_allowed


logger = logging.getLogger(__name__)
MAX_PROCESSING_MESSAGE_BYTES = 8 * 1024


def _safe_message(
    value: dict[str, Any], *, redelivered: bool = False
) -> DocumentProcessingStageMessage:
    contract = str(value.get("contract_version") or "")
    if contract == "file-processing/v1":
        payload = DocumentProcessingRepository.validate_safe_message_payload(value)
        return FileProcessingTaskMessage(
            contract_version=contract,
            run_id=str(payload["run_id"]),
            source_version_id=str(payload["source_version_id"]),
            profile_hash=str(payload["profile_hash"]),
            attempt=int(payload["attempt"]),
            correlation_id=str(payload["correlation_id"]),
            redelivered=redelivered,
        )
    payload = DocumentProcessingRepository.validate_safe_stage_message_payload(value)
    if contract == "file-picture-processing/v1":
        return PictureProcessingTaskMessage(
            contract_version=contract,
            run_id=str(payload["run_id"]),
            picture_item_id=str(payload["picture_item_id"]),
            profile_hash=str(payload["profile_hash"]),
            attempt=int(payload["attempt"]),
            correlation_id=str(payload["correlation_id"]),
            redelivered=redelivered,
        )
    return AssemblyTaskMessage(
        contract_version=contract,
        run_id=str(payload["run_id"]),
        profile_hash=str(payload["profile_hash"]),
        attempt=int(payload["attempt"]),
        correlation_id=str(payload["correlation_id"]),
        redelivered=redelivered,
    )


class RabbitMQFileProcessingPublisher:
    def __init__(self, rabbitmq_url: str, queue: QueueSettings) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue = queue

    def publish(self, event: dict[str, Any]) -> None:
        if str(event.get("event_type") or "") != "file.processing.requested":
            return
        self.publish_message(_safe_message(dict(event["payload"])))

    def publish_message(self, message: DocumentProcessingStageMessage) -> None:
        self._publish(self.queue.file_processing_queue, message.safe_payload())

    def publish_retry(
        self, message: DocumentProcessingStageMessage, *, delay_seconds: int
    ) -> None:
        if not 1 <= delay_seconds <= 600:
            raise ValueError("File processing retry delay is invalid")
        payload = message.safe_payload()
        payload["attempt"] = message.attempt + 1
        self._publish(
            self.queue.file_processing_retry_queue,
            payload,
            expiration_ms=delay_seconds * 1000,
        )

    def publish_dead(self, message: DocumentProcessingStageMessage, *, error_code: str) -> None:
        safe_error = _safe_error_code(error_code)
        self._publish(
            self.queue.file_processing_dead_queue,
            {**message.safe_payload(), "dead_letter_error_code": safe_error},
        )

    def publish_invalid_dead(self, *, error_code: str) -> None:
        self._publish(
            self.queue.file_processing_dead_queue,
            {
                "contract_version": "file-processing-dead/v1",
                "dead_letter_error_code": _safe_error_code(error_code),
            },
        )

    def _publish(
        self,
        queue_name: str,
        payload: dict[str, object],
        *,
        expiration_ms: int | None = None,
    ) -> None:
        assert_external_io_allowed("rabbitmq.publish_file_processing")
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ publishing") from exc
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_PROCESSING_MESSAGE_BYTES:
            raise ValueError("File processing message exceeds its safe bound")
        connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        try:
            channel = connection.channel()
            declare_file_processing_topology(channel, self.queue)
            channel.confirm_delivery()
            confirmed = channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=encoded,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    expiration=(str(expiration_ms) if expiration_ms is not None else None),
                    content_type="application/json",
                ),
                mandatory=True,
            )
            if confirmed is False:
                raise RuntimeError("RabbitMQ file processing publish confirm failed")
        finally:
            connection.close()


class DocumentProcessingStageOutboxPublisher:
    def __init__(
        self,
        repository: DocumentProcessingRepository,
        publisher: RabbitMQFileProcessingPublisher,
    ) -> None:
        self.repository = repository
        self.publisher = publisher

    def publish_pending(self, *, limit: int = 100) -> dict[str, int]:
        claim_token = f"stage-outbox-{uuid.uuid4().hex}"
        rows = self.repository.claim_stage_outbox(claim_token=claim_token, limit=limit)
        published = failed = 0
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
                if not isinstance(payload, dict):
                    raise ValueError("stage payload is not an object")
                self.publisher.publish_message(_safe_message(payload))
                self.repository.mark_stage_outbox_published(
                    outbox_id=str(row["id"]), claim_token=claim_token
                )
                published += 1
            except Exception as exc:
                self.repository.mark_stage_outbox_failed(
                    outbox_id=str(row["id"]),
                    claim_token=claim_token,
                    error_code=f"stage_publish_{type(exc).__name__.lower()}"[:128],
                    retry_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                )
                failed += 1
        return {"published": published, "failed": failed}


class RabbitMQFileProcessingConsumer:
    def __init__(self, rabbitmq_url: str, queue: QueueSettings) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue = queue
        self.publisher = RabbitMQFileProcessingPublisher(rabbitmq_url, queue)

    def consume(
        self,
        handler: FileProcessingTaskHandler,
        *,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("pika is required for RabbitMQ consuming") from exc
        connection: Any = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
        try:
            channel = connection.channel()
            declare_file_processing_topology(channel, self.queue)
            channel.basic_qos(prefetch_count=1)
            if on_ready is not None:
                on_ready()

            def on_message(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                del properties
                try:
                    if len(body) > MAX_PROCESSING_MESSAGE_BYTES:
                        raise ValueError("message_too_large")
                    value = json.loads(body.decode("utf-8", errors="strict"))
                    if not isinstance(value, dict):
                        raise ValueError("message_not_object")
                    message = _safe_message(
                        value, redelivered=bool(getattr(method, "redelivered", False))
                    )
                except Exception:
                    logger.warning("Rejected unsafe file processing message")
                    self.publisher.publish_invalid_dead(error_code="processing_message_invalid")
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

                try:
                    result = handler(message)
                    if result.disposition is FileProcessingDisposition.RETRY:
                        self.publisher.publish_retry(message, delay_seconds=result.delay_seconds)
                    elif result.disposition is FileProcessingDisposition.DEAD:
                        self.publisher.publish_dead(message, error_code=result.error_code)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    logger.exception(
                        "File processing handler failed safely run_id=%s",
                        message.run_id,
                    )
                    self.publisher.publish_dead(message, error_code="processing_handler_unexpected")
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(
                queue=self.queue.file_processing_queue,
                on_message_callback=on_message,
            )
            channel.start_consuming()
        finally:
            connection.close()


def _safe_error_code(value: str) -> str:
    normalized = str(value or "processing_failed")[:128]
    if not normalized.replace("_", "").isalnum():
        return "processing_failed"
    return normalized
