from __future__ import annotations

import logging
import time
from pathlib import Path

from app.bootstrap import build_worker_container
from app.shared.config import load_settings
from app.shared.logging import configure_logging


logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/job-dispatch-worker.heartbeat")


def main() -> None:
    configure_logging()
    settings = load_settings()
    container = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name="job-dispatch-worker",
    )
    settings = container.settings
    logger.info("Job dispatch outbox worker starting")
    while True:
        try:
            HEARTBEAT_PATH.touch()
            result = container.job_dispatcher.publish_pending(limit=100)
            if (
                result.published
                or result.failed
                or result.dead
                or result.recovered
                or result.expired
            ):
                logger.info(
                    "Job dispatch outbox scan "
                    "published=%s failed=%s dead=%s recovered=%s expired=%s",
                    result.published,
                    result.failed,
                    result.dead,
                    result.recovered,
                    result.expired,
                )
        except Exception:
            logger.exception("Job dispatch outbox scan failed")
        finally:
            HEARTBEAT_PATH.touch()
        time.sleep(max(settings.queue.dispatch_outbox_scan_seconds, 1))


if __name__ == "__main__":
    main()
