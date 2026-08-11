from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.modules.audit.application.audit_service import AuditService
from app.modules.delivery.application.delivery_operations import (
    DeliveryOperationsService,
)
from app.modules.job.infrastructure.repositories import AgentRepository, AuditRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or replay persisted Delivery Outbox events"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="Read one exact Delivery event")
    status.add_argument("--delivery-id", required=True)

    commands.add_parser("metrics", help="Read aggregate Delivery state metrics")

    replay = commands.add_parser(
        "replay",
        help=("Rearm one exact DEAD Delivery with its frozen binding and persisted artifact"),
    )
    replay.add_argument("--delivery-id", required=True)
    replay.add_argument("--actor-id", default="delivery-replay-cli")
    replay.add_argument("--reason", required=True)
    # Hidden trap arguments make prohibited override attempts fail safely and
    # auditable instead of being silently ignored or accepted by wrappers.
    replay.add_argument("--connector-id", default="", help=argparse.SUPPRESS)
    replay.add_argument("--target", default="", help=argparse.SUPPRESS)
    replay.add_argument("--payload", default="", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        service = DeliveryOperationsService(
            repository=AgentRepository(database),
            audit_service=AuditService(AuditRepository(database)),
        )
        if args.command == "metrics":
            result = service.metrics()
        elif args.command == "status":
            result = service.status(delivery_id=args.delivery_id)
        else:
            result = service.replay(
                delivery_id=args.delivery_id,
                actor_id=args.actor_id,
                reason=args.reason,
                connector_id=args.connector_id,
                target=args.target,
                payload=args.payload,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except AppError as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.error_code or "delivery_operation_failed",
                    "message": exc.safe_message,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
