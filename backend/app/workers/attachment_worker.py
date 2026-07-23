from __future__ import annotations

import logging

from app.bootstrap import build_worker_container
from app.modules.message_bus.infrastructure.rabbitmq_attachment_consumer import (
    RabbitMQAttachmentConsumer,
)
from app.shared.config import load_settings
from app.shared.logging import configure_logging, with_correlation

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    settings = load_settings()
    container = build_worker_container(
        settings,
        migrate=settings.app_startup_migrate,
        seed=settings.seed_local_config,
        service_name="attachment-worker",
    )
    if container.attachment_service is None:
        raise RuntimeError("Attachment processing is not enabled")
    attachment_service = container.attachment_service
    consumer = RabbitMQAttachmentConsumer(settings.rabbitmq_url, settings.queue)

    def handle(message: object) -> None:
        attachment_id = str(getattr(message, "attachment_id"))
        correlation_id = str(getattr(message, "correlation_id"))
        with_correlation(
            correlation_id,
            lambda: attachment_service.process(attachment_id, correlation_id),
        )

    logger.info("Attachment worker starting queue=%s", settings.queue.attachment_queue)
    consumer.consume_attachments(handle)


if __name__ == "__main__":
    main()
