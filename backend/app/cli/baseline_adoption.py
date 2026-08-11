from __future__ import annotations

import argparse
import json
import os

from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import BaselineAdoptionInspector, MigrationDefinitionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only preflight and verification for legacy baseline adoption"
    )
    parser.add_argument("action", choices=("preflight", "verify"))
    parser.add_argument(
        "--build",
        default=os.getenv("MIGRATOR_BUILD", "local-uncommitted"),
        help="Expected non-secret release or commit identifier",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = Database(load_settings().database_dsn)
    inspector = BaselineAdoptionInspector(database, default_migrations_dir())
    operation = str(args.action).upper()
    try:
        if args.action == "preflight":
            report = inspector.preflight(migrator_build=args.build)
        else:
            report = inspector.verify(expected_migrator_build=args.build)
    except MigrationDefinitionError as exc:
        print(f"BASELINE_ADOPTION_{operation}_FAILED: {exc}")
        return 1
    except Exception:
        print(
            f"BASELINE_ADOPTION_{operation}_FAILED: "
            "database unavailable or verification failed"
        )
        return 1
    finally:
        database.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
