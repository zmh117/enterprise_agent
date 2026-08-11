from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.application.job_dispatch_cutover import JobDispatchCutoverService
from app.modules.job.infrastructure.repositories import AgentRepository, AuditRepository
from app.modules.message_bus.infrastructure.rabbitmq_cutover import (
    RabbitMQExactQueueScanner,
)
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Dry-run or apply the one-time exact Agent job queue to Outbox cutover")
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor-id", default="job-dispatch-cutover-cli")
    parser.add_argument("--max-messages-per-queue", type=int, default=10_000)
    parser.add_argument("--confirm-topology-digest", default="")
    parser.add_argument("--delete-empty-old-queues", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        repository = AgentRepository(database)
        service = JobDispatchCutoverService(
            repository=repository,
            audit_service=AuditService(AuditRepository(database)),
            queue_settings=settings.queue,
        )
        plan = service.topology_plan()
        expected_digest = str(plan["topology_digest"])
        if args.apply and args.confirm_topology_digest != expected_digest:
            raise SystemExit(
                f"--apply requires the exact --confirm-topology-digest {expected_digest}"
            )
        scanner = RabbitMQExactQueueScanner(settings.rabbitmq_url)
        queue_names = [
            settings.queue.job_queue,
            settings.queue.retry_queue,
            settings.queue.legacy_retry_queue,
            settings.queue.dead_queue,
        ]
        before = scanner.inspect_exact(queue_names)
        if args.apply:
            active = {
                name: state["consumers"] for name, state in before.items() if state["consumers"]
            }
            if active:
                raise SystemExit(
                    "Apply requires all exact Agent job consumers to be stopped: "
                    + json.dumps(active, ensure_ascii=False, sort_keys=True)
                )
        scans: list[dict[str, object]] = []
        for queue_name in queue_names:
            if not before[queue_name]["exists"]:
                continue

            def process_message(
                body: bytes,
                source_queue: str = queue_name,
            ) -> dict[str, object]:
                return service.process_message(
                    source_queue=source_queue,
                    body=body,
                    apply=args.apply,
                    actor_id=args.actor_id,
                ).to_dict()

            scans.append(
                scanner.scan_exact(
                    queue_name=queue_name,
                    limit=max(0, args.max_messages_per_queue),
                    apply=args.apply,
                    process=process_message,
                )
            )
        after = scanner.inspect_exact(queue_names)
        deleted: list[str] = []
        quarantine_count = repository.dispatch_cutover_quarantine_count()
        if args.delete_empty_old_queues:
            if not args.apply:
                raise SystemExit("--delete-empty-old-queues requires --apply")
            if quarantine_count:
                raise SystemExit(
                    "Old queues cannot be deleted while cutover quarantine is non-empty"
                )
            if any(bool(scan["truncated"]) for scan in scans):
                raise SystemExit("Old queues cannot be deleted after a truncated scan")
            deleted = scanner.delete_exact_empty_unused(
                [
                    settings.queue.retry_queue,
                    settings.queue.legacy_retry_queue,
                    settings.queue.dead_queue,
                ]
            )
        report = {
            "mode": "apply" if args.apply else "dry-run",
            "topology": plan,
            "before": before,
            "scans": scans,
            "after": after,
            "quarantine_count": quarantine_count,
            "deleted_exact_queues": deleted,
            "wildcard_delete_supported": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
