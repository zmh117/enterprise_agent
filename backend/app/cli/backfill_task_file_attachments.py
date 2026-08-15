from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from app.modules.file_workspace.attachment_backfill import AttachmentFileBackfill
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run-first attachment file binding and retention fact backfill"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--cursor", default="")
    parser.add_argument("--batch-size", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.reconcile:
        raise SystemExit("--apply and --reconcile are mutually exclusive")
    database = Database(load_settings().database_dsn)
    try:
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        report = AttachmentFileBackfill(database).run(
            apply=bool(args.apply),
            reconcile=bool(args.reconcile),
            cursor=str(args.cursor),
            batch_size=int(args.batch_size),
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if report["status"] == "ready" else 2
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
