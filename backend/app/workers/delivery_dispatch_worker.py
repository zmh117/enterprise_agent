from __future__ import annotations

import logging
from pathlib import Path
import time

from app.bootstrap import build_worker_container
from app.shared.config import load_settings
from app.shared.logging import configure_logging


logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/delivery-dispatch-worker.heartbeat")


def main() -> None:
    configure_logging()
    settings = load_settings()
    container = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name="delivery-dispatch-worker",
    )
    logger.info("Delivery outbox worker starting")
    while True:
        result = container.delivery_dispatcher.dispatch_pending(limit=100)
        HEARTBEAT_PATH.touch()
        if any(
            (
                result.succeeded,
                result.skipped,
                result.retrying,
                result.failed,
                result.dead,
                result.recovered,
            )
        ):
            logger.info(
                "Delivery outbox scan succeeded=%s skipped=%s retrying=%s "
                "failed=%s dead=%s recovered=%s",
                result.succeeded,
                result.skipped,
                result.retrying,
                result.failed,
                result.dead,
                result.recovered,
            )
        time.sleep(max(1, settings.delivery.outbox_scan_seconds))


if __name__ == "__main__":
    main()
