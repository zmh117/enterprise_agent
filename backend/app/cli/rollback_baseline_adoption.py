from __future__ import annotations

import argparse
import os

from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import BaselineAdoptionRollback, MigrationDefinitionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Remove only the legacy-042 baseline 100 marker and adoption metadata; "
            "business schema and data are never modified"
        )
    )
    parser.add_argument(
        "--build",
        default=os.getenv("MIGRATOR_BUILD", "local-uncommitted"),
        help="Non-secret build or commit identifier used for the controlled operation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = Database(load_settings().database_dsn)
    try:
        head = BaselineAdoptionRollback(
            database,
            default_migrations_dir(),
            migrator_build=args.build,
        ).run()
    except MigrationDefinitionError as exc:
        print(f"BASELINE_ADOPTION_ROLLBACK_FAILED: {exc}")
        return 1
    except Exception:
        print("BASELINE_ADOPTION_ROLLBACK_FAILED: database unavailable or lock failed")
        return 1
    finally:
        database.close()
    print(f"BASELINE_ADOPTION_ROLLBACK_SUCCEEDED: restored_ledger_head={head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
