from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from app.bootstrap import build_worker_container
from app.shared.config import load_settings
from app.shared.logging import configure_logging

logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/channel-dispatch-worker.heartbeat")


def main() -> None:
    configure_logging()
    settings = load_settings()
    container = build_worker_container(
        settings,
        migrate=settings.app_startup_migrate,
        seed=settings.seed_local_config,
        service_name="channel-dispatch-worker",
    )
    if container.consumer is None:
        raise RuntimeError("Channel dispatch worker does not have a message consumer")

    def publish_outbox() -> None:
        while True:
            try:
                HEARTBEAT_PATH.touch()
                result = container.channel_outbox_publisher.publish_pending(limit=100)
                if result["published"] or result["failed"]:
                    logger.info("Channel outbox scan result=%s", result)
            except Exception:
                logger.exception("Channel outbox recovery scan failed")
            finally:
                HEARTBEAT_PATH.touch()
            time.sleep(1)

    threading.Thread(
        target=publish_outbox,
        name="channel-outbox-recovery",
        daemon=True,
    ).start()
    logger.info(
        "Channel dispatcher worker starting queue=%s",
        container.settings.queue.channel_queue,
    )
    container.consumer.consume_channel_events(container.channel_dispatch_service.handle)


if __name__ == "__main__":
    main()
