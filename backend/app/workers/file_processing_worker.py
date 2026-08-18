from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

from app.modules.document_processing.file_service_client import (
    DocumentProcessingFileServiceClient,
)
from app.modules.document_processing.provider import (
    DoclingServeProvider,
    read_docling_api_key,
)
from app.modules.document_processing.worker_service import FileProcessingWorkerService
from app.modules.identity.application.service_principal import ServicePrincipalTokenClient
from app.modules.message_bus.infrastructure.rabbitmq_file_processing import (
    RabbitMQFileProcessingConsumer,
)
from app.shared.config import load_settings
from app.shared.logging import configure_logging, with_correlation


logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/file-processing-worker.heartbeat")
STATUS = Path("/tmp/file-processing-worker.status.json")


def main() -> None:
    configure_logging()
    settings = load_settings()
    if not settings.service_principal.enabled:
        raise RuntimeError("File Processing Worker Service Principal is disabled")
    worker_settings = settings.document_processing_worker
    if worker_settings.concurrency != 1:
        raise RuntimeError("Phase 1 File Processing Worker concurrency must be 1")
    token_provider = ServicePrincipalTokenClient(
        base_url=settings.service_principal.identity_base_url,
        allowed_hosts=settings.service_principal.identity_allowed_hosts,
        bootstrap_credential_file=(
            settings.service_principal.file_processing_worker_bootstrap_token_file
        ),
        timeout_seconds=settings.service_principal.timeout_seconds,
        refresh_skew_seconds=settings.service_principal.refresh_skew_seconds,
    )
    file_service = DocumentProcessingFileServiceClient(
        base_url=settings.file_service.internal_base_url,
        allowed_hosts=settings.file_service.internal_allowed_hosts,
        token_provider=token_provider,
        timeout_seconds=settings.file_service.internal_timeout_seconds,
    )
    processor = DoclingServeProvider(
        base_url=worker_settings.docling_base_url,
        allowed_hosts=worker_settings.docling_allowed_hosts,
        api_key=read_docling_api_key(worker_settings.docling_api_key_file),
        connect_timeout_seconds=worker_settings.connect_timeout_seconds,
        max_response_bytes=worker_settings.max_response_bytes,
    )
    service = FileProcessingWorkerService(
        file_service=file_service,
        processor=processor,
        poll_interval_seconds=worker_settings.poll_interval_seconds,
        total_timeout_seconds=worker_settings.total_timeout_seconds,
        max_attempts=settings.queue.file_processing_max_attempts,
        retry_base_seconds=settings.queue.file_processing_retry_base_seconds,
    )
    consumer = RabbitMQFileProcessingConsumer(settings.rabbitmq_url, settings.queue)
    status_lock = threading.Lock()

    def publish_status(**updates: str) -> None:
        with status_lock:
            current: dict[str, str] = {}
            if STATUS.exists():
                try:
                    value = json.loads(STATUS.read_text())
                    if isinstance(value, dict):
                        current = {str(key): str(item) for key, item in value.items()}
                except (OSError, json.JSONDecodeError):
                    current = {}
            current.update(updates)
            temporary = STATUS.with_suffix(".tmp")
            temporary.write_text(json.dumps(current, sort_keys=True))
            temporary.replace(STATUS)
            HEARTBEAT.touch()

    def dependency_monitor() -> None:
        endpoints = {
            "file_service": settings.file_service.internal_base_url.rstrip("/") + "/ready",
            "docling": worker_settings.docling_base_url.rstrip("/") + "/ready",
        }
        while True:
            status: dict[str, str] = {}
            for name, url in endpoints.items():
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        status[name] = "ready" if response.status == 200 else "unavailable"
                except (OSError, TimeoutError):
                    status[name] = "unavailable"
            publish_status(**status)
            time.sleep(30)

    def handle(message: object):
        run_id = str(getattr(message, "run_id"))
        correlation_id = str(getattr(message, "correlation_id"))
        HEARTBEAT.touch()
        result = with_correlation(correlation_id, lambda: service(message))
        publish_status(
            status="RUNNING",
            last_run_id=run_id,
            last_disposition=str(result.disposition),
            last_error_code=result.error_code,
        )
        return result

    publish_status(
        status="STARTING",
        rabbitmq="unavailable",
        file_service="unavailable",
        docling="unavailable",
    )
    threading.Thread(
        target=dependency_monitor,
        name="file-processing-dependencies",
        daemon=True,
    ).start()
    logger.info(
        "File processing worker starting queue=%s concurrency=1",
        settings.queue.file_processing_queue,
    )
    consumer.consume(
        handle,
        on_ready=lambda: publish_status(status="RUNNING", rabbitmq="ready"),
    )


if __name__ == "__main__":
    main()
