from __future__ import annotations

import logging
import time
from pathlib import Path

from app.bootstrap import build_worker_container
from app.modules.channel.browser.answers import purge_answers
from app.shared.config import load_settings
from app.shared.logging import configure_logging
from app.modules.agent.infrastructure.runtime_pool_recovery import reconcile_runtime_nodes


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
    next_cleanup = 0.0
    while True:
        try:
            HEARTBEAT_PATH.touch()
            reconcile_runtime_nodes(settings.agent_runtime, container.database)
            if time.monotonic() >= next_cleanup:
                purge_answers(container.database)
                next_cleanup = time.monotonic() + 60
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
