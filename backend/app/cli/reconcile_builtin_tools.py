from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.bootstrap import build_api_container
from app.shared.config import load_settings
from app.shared.database import default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile code-owned Built-in Tool manifests with governed "
            "installations without verifying or publishing releases"
        )
    )
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--correlation-id", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = build_api_container(load_settings())
    try:
        SchemaHeadValidator(
            runtime.database,
            default_migrations_dir(),
        ).require_current()
        summary = runtime.platform_config_service.handlers.reconcile(
            actor_id=args.actor_id,
            correlation_id=args.correlation_id,
        )
        release_count = runtime.database.execute_one(
            "select count(*) as count from builtin_tool_release"
        )
        print(
            json.dumps(
                {
                    "status": "reconciled",
                    **summary,
                    "release_count": int(
                        (release_count or {"count": 0})["count"]
                    ),
                    "verification_performed": False,
                    "publication_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except AppError as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.error_code or "builtin_tool_reconcile_failed",
                    "message": exc.safe_message,
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
                    "error_code": "builtin_tool_reconcile_failed",
                    "message": "内置只读工具对账失败",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        runtime.database.close()


if __name__ == "__main__":
    raise SystemExit(main())
