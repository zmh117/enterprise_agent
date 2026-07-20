from __future__ import annotations

import argparse
import json

from app.bootstrap import build_worker_container
from app.modules.job.application.retry_recovery_service import RetryRecoveryService
from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    inspect_agent_job_topology,
)
from app.shared.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or explicitly recover stranded Agent job retries"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--job-id", action="append", default=[])
    parser.add_argument("--actor-id", default="retry-recovery-cli")
    args = parser.parse_args()

    settings = load_settings()
    container = build_worker_container(settings, migrate=True, seed=False)
    try:
        report = RetryRecoveryService(
            repository=container.agent_repository,
            publisher=container.publisher,
            audit_service=container.audit_service,
            queue_settings=container.settings.queue,
        ).reconcile(
            apply=args.apply,
            job_ids=args.job_id or None,
            actor_id=args.actor_id,
        )
        report["rabbitmq"] = inspect_agent_job_topology(
            settings.rabbitmq_url, container.settings.queue
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        container.database.close()


if __name__ == "__main__":
    main()
