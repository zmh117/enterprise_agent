from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from app.bootstrap import build_worker_container
from app.modules.document_processing.repository import DocumentProcessingRepository
from app.modules.message_bus.infrastructure.rabbitmq_attachment_consumer import (
    RabbitMQAttachmentConsumer,
)
from app.modules.message_bus.infrastructure.rabbitmq_file_processing import (
    DocumentProcessingStageOutboxPublisher,
    RabbitMQFileProcessingPublisher,
)
from app.shared.config import load_settings
from app.shared.logging import configure_logging, with_correlation


logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/file-worker.heartbeat")
STATUS = Path("/tmp/file-worker.status.json")


def main() -> None:
    configure_logging()
    settings = load_settings()
    container = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name="file-worker",
    )
    if container.attachment_service is None:
        raise RuntimeError("File attachment processing is not enabled")
    attachment_service = container.attachment_service
    consumer = RabbitMQAttachmentConsumer(settings.rabbitmq_url, settings.queue)
    importer = attachment_service.importer
    if importer is None or not hasattr(importer, "run_maintenance"):
        raise RuntimeError("File lifecycle client is not enabled")
    stage_outbox = DocumentProcessingStageOutboxPublisher(
        DocumentProcessingRepository(container.database),
        RabbitMQFileProcessingPublisher(settings.rabbitmq_url, settings.queue),
    )
    status_lock = threading.Lock()
    status: dict[str, int | str] = {
        "status": "STARTING",
        "rabbitmq": "unavailable",
        "file_service": "unavailable",
    }

    def publish_status(**updates: int | str) -> None:
        with status_lock:
            status.update(updates)
            temporary = STATUS.with_suffix(".tmp")
            temporary.write_text(json.dumps(status, sort_keys=True))
            temporary.replace(STATUS)
            HEARTBEAT.touch()

    def maintain() -> None:
        while True:
            try:
                result = importer.run_maintenance()
                release_job_ids = result.pop("document_processing_release_job_ids", [])
                released = 0
                if isinstance(release_job_ids, list):
                    for job_id in release_job_ids:
                        outcome = attachment_service.release_if_ready(
                            job_id,
                            f"document-processing-reconcile:{job_id}"[:128],
                        )
                        released += int(outcome == "released")
                notice = attachment_service.reconcile_file_readiness_notices()
                stage_result = stage_outbox.publish_pending(limit=100)
                publish_status(
                    **{
                        **result,
                        "document_processing_jobs_released": released,
                        "file_readiness_notices_expired": int(notice.get("expired") or 0),
                        "file_readiness_notices_notified": int(notice.get("notified") or 0),
                        "document_stage_outbox_published": int(
                            stage_result.get("published") or 0
                        ),
                        "document_stage_outbox_failed": int(stage_result.get("failed") or 0),
                        "status": "RUNNING",
                        "file_service": "ready",
                        "last_error_class": "",
                        "last_maintenance_at": str(int(time.time())),
                    }
                )
            except Exception as exc:
                publish_status(
                    file_service="unavailable",
                    last_error_class=type(exc).__name__[:128],
                )
                logger.warning(
                    "File maintenance attempt failed error_class=%s",
                    type(exc).__name__,
                )
            time.sleep(60)

    def handle(message: object) -> None:
        attachment_id = str(getattr(message, "attachment_id"))
        correlation_id = str(getattr(message, "correlation_id"))
        HEARTBEAT.touch()
        with_correlation(
            correlation_id,
            lambda: attachment_service.process(attachment_id, correlation_id),
        )
        HEARTBEAT.touch()

    publish_status()
    threading.Thread(target=maintain, name="file-maintenance", daemon=True).start()
    logger.info(
        "File worker starting compatible_attachment_queue=%s",
        settings.queue.attachment_queue,
    )
    consumer.consume_attachments(
        handle,
        on_ready=lambda: publish_status(rabbitmq="ready"),
    )


if __name__ == "__main__":
    main()
