from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.application.job_dispatch_operations import (
    JobDispatchOperationsService,
)
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.modules.job.infrastructure.repositories import AgentRepository, AuditRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or replay persisted Agent job dispatch events"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="Read one exact persisted event")
    _add_exact_identifier(status)

    commands.add_parser("metrics", help="Read aggregate dispatch state metrics")

    replay = commands.add_parser(
        "replay",
        help="Rearm one exact DEAD event within its persisted replay limit",
    )
    _add_exact_identifier(replay)
    replay.add_argument("--actor-id", default="job-dispatch-replay-cli")
    replay.add_argument("--reason", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        service = JobDispatchOperationsService(
            repository=AgentRepository(database),
            audit_service=AuditService(AuditRepository(database)),
            mcp_tool_snapshot_service=(JobMcpToolSnapshotService(database)),
        )
        if args.command == "metrics":
            result = service.metrics()
        elif args.command == "status":
            result = service.status(
                event_id=args.event_id or "",
                job_id=args.job_id or "",
            )
        else:
            result = service.replay(
                event_id=args.event_id or "",
                job_id=args.job_id or "",
                actor_id=args.actor_id,
                reason=args.reason,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except AppError as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.error_code or "job_dispatch_operation_failed",
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


def _add_exact_identifier(parser: argparse.ArgumentParser) -> None:
    identifiers = parser.add_mutually_exclusive_group(required=True)
    identifiers.add_argument("--event-id", default="")
    identifiers.add_argument("--job-id", default="")


if __name__ == "__main__":
    raise SystemExit(main())
