from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.modules.platform_config.application.resource_reset import (
    ResourceResetService,
)
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled DB/Redis/Loki resource reset. "
            "Apply requires a freshly prepared exact digest."
        )
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )
    report = commands.add_parser(
        "report",
        help="Read the exact reset inventory without changing state",
    )
    report.add_argument("--output", default="")

    prepare = commands.add_parser(
        "prepare",
        help=("Enter maintenance, drain resource Jobs and persist an exact reset manifest"),
    )
    prepare.add_argument("--actor-id", required=True)
    prepare.add_argument("--backup-reference", required=True)
    prepare.add_argument(
        "--drain-timeout-seconds",
        type=float,
        default=30.0,
    )
    prepare.add_argument("--output", default="")
    prepare.add_argument("--correlation-id", default="")

    apply_command = commands.add_parser(
        "apply",
        help=("Apply one PREPARED operation after external user confirmation of the exact digest"),
    )
    apply_command.add_argument("--operation-id", required=True)
    apply_command.add_argument("--expected-digest", required=True)
    apply_command.add_argument("--confirmed-by", required=True)

    verify = commands.add_parser(
        "verify",
        help="Verify an applied reset and all protected categories",
    )
    verify.add_argument("--operation-id", required=True)
    verify.add_argument("--actor-id", required=True)
    verify.add_argument("--output", default="")
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
        service = ResourceResetService(database)
        if args.command == "report":
            result = service.report()
        elif args.command == "prepare":
            result = service.prepare(
                actor_id=args.actor_id,
                backup_reference=args.backup_reference,
                correlation_id=args.correlation_id,
                drain_timeout_seconds=args.drain_timeout_seconds,
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
        output = getattr(args, "output", "")
        if output:
            _write_output(Path(output), result)
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
        message = exc.safe_message if isinstance(exc, AppError) else str(exc)
        error_code = exc.error_code if isinstance(exc, AppError) else "resource_reset_invalid"
        print(
            json.dumps(
                {
                    "error_code": (error_code or "resource_reset_failed"),
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
                    "error_code": "resource_reset_failed",
                    "message": "工具资源重置失败",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        database.close()


def _write_output(path: Path, result: dict[str, Any]) -> None:
    if not path.is_absolute():
        raise ValueError("--output 必须使用绝对路径")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
