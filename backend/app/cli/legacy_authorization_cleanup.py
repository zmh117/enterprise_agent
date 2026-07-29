from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.modules.identity.application.legacy_authorization_cleanup import (
    LegacyAuthorizationCleanupService,
)
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled legacy authorization cleanup. Apply requires "
            "a freshly prepared exact digest."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "report",
        help="Read the exact legacy authorization inventory",
    )
    prepare = commands.add_parser(
        "prepare",
        help="Persist an exact cleanup manifest after backups",
    )
    prepare.add_argument("--actor-id", required=True)
    prepare.add_argument("--backup-reference", required=True)
    prepare.add_argument("--correlation-id", default="")
    apply_command = commands.add_parser(
        "apply",
        help="Delete the exact prepared inventory after user confirmation",
    )
    apply_command.add_argument("--operation-id", required=True)
    apply_command.add_argument("--expected-digest", required=True)
    apply_command.add_argument("--confirmed-by", required=True)
    verify = commands.add_parser(
        "verify",
        help="Verify legacy rows are empty and two admins remain",
    )
    verify.add_argument("--operation-id", required=True)
    verify.add_argument("--actor-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(
            database,
            default_migrations_dir(),
        ).require_current()
        service = LegacyAuthorizationCleanupService(database)
        if args.command == "report":
            result = service.report()
        elif args.command == "prepare":
            result = service.prepare(
                actor_id=args.actor_id,
                backup_reference=args.backup_reference,
                correlation_id=args.correlation_id,
            )
        elif args.command == "apply":
            result = service.apply(
                operation_id=args.operation_id,
                expected_digest=args.expected_digest,
                confirmed_by=args.confirmed_by,
            )
        else:
            result = service.verify(
                operation_id=args.operation_id,
                actor_id=args.actor_id,
            )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (AppError, ValueError) as exc:
        message = (
            exc.safe_message if isinstance(exc, AppError) else str(exc)
        )
        error_code = (
            exc.error_code
            if isinstance(exc, AppError)
            else "legacy_authorization_cleanup_invalid"
        )
        print(
            json.dumps(
                {
                    "error_code": (
                        error_code
                        or "legacy_authorization_cleanup_failed"
                    ),
                    "message": message,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "error_code": "legacy_authorization_cleanup_failed",
                    "message": "旧授权清理失败",
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
