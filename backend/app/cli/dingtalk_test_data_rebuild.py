from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.modules.managed_channel.application.dingtalk_test_data_rebuild import (
    CONFIRMATION_TEXT,
    DingTalkTestDataRebuildService,
)
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or explicitly apply the non-production DingTalk test "
            "data rebuild. Preview is the default and never writes."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the exact previewed plan instead of read-only preview",
    )
    parser.add_argument("--plan-hash", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--backup-reference", default="")
    parser.add_argument("--actor-id", default="")
    parser.add_argument(
        "--writes-stopped",
        action="store_true",
        help=(
            "Attest that DingTalk Runtime, ingress dispatcher and related "
            "outbox workers have been stopped"
        ),
    )
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
        service = DingTalkTestDataRebuildService(
            database,
            environment=settings.environment,
        )
        if args.execute:
            result = service.apply(
                expected_plan_hash=args.plan_hash,
                confirmation=args.confirm,
                backup_reference=args.backup_reference,
                writes_stopped=args.writes_stopped,
                actor_id=args.actor_id,
            )
        else:
            result = service.report()
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
            else "dingtalk_rebuild_invalid"
        )
        print(
            json.dumps(
                {
                    "error_code": error_code or "dingtalk_rebuild_failed",
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
                    "error_code": "dingtalk_rebuild_failed",
                    "message": "钉钉测试数据重建失败",
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


__all__ = ["CONFIRMATION_TEXT", "build_parser", "main"]
