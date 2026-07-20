from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.bootstrap import build_worker_container
from app.shared.config import load_settings
from app.shared.logging import configure_logging


logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/webhook-worker.heartbeat")


def main() -> None:
    configure_logging()
    settings = load_settings()
    container = build_worker_container(
        settings,
        migrate=settings.app_startup_migrate,
        seed=settings.seed_local_config,
        service_name="webhook-worker",
    )
    settings = container.settings
    if container.consumer is None:
        raise RuntimeError("Webhook worker container does not have a message consumer")

    def recover_outbox() -> None:
        last_cleanup = 0.0
        while True:
            try:
                HEARTBEAT_PATH.touch()
                result = container.webhook_outbox_publisher.publish_pending(limit=100)
                if result.published or result.failed:
                    logger.info(
                        "Webhook outbox scan published=%s failed=%s",
                        result.published,
                        result.failed,
                    )
                if time.monotonic() - last_cleanup >= 24 * 60 * 60:
                    now = datetime.now(UTC)
                    cleaned = container.webhook_event_repository.cleanup(
                        nonce_before=now.isoformat(),
                        event_before=(
                            now - timedelta(days=settings.webhooks.event_retention_days)
                        ).isoformat(),
                    )
                    logger.info("Webhook retention cleanup result=%s", cleaned)
                    last_cleanup = time.monotonic()
            except Exception:
                logger.exception("Webhook outbox recovery scan failed")
            finally:
                HEARTBEAT_PATH.touch()
            time.sleep(max(settings.webhooks.outbox_scan_seconds, 1))

    threading.Thread(
        target=recover_outbox,
        name="webhook-outbox-recovery",
        daemon=True,
    ).start()
    logger.info("Webhook dispatcher worker starting queue=%s", settings.queue.webhook_queue)
    container.consumer.consume_webhook_events(container.webhook_dispatcher.handle)


if __name__ == "__main__":
    main()
