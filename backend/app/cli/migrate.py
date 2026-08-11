from __future__ import annotations

import argparse
import os

from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import (
    MigrationDefinitionError,
    MigrationExecutionError,
    Migrator,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply platform schema migrations exactly once")
    parser.add_argument(
        "--build",
        default=os.getenv("MIGRATOR_BUILD", "local-uncommitted"),
        help="Non-secret build or commit identifier stored in the ledger",
    )
    parser.add_argument(
        "--include-schema-contract",
        action="store_true",
        help=(
            "Explicitly include staged contract/drop migrations; existing databases "
            "must also contain separately authorized contract evidence"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build=args.build,
            include_schema_contract=bool(args.include_schema_contract),
        ).run()
    except (MigrationDefinitionError, MigrationExecutionError) as exc:
        print(f"MIGRATION_FAILED: {exc}")
        return 1
    except Exception:
        print("MIGRATION_FAILED: database unavailable or migration lock failed")
        return 1
    finally:
        database.close()
    print(
        "MIGRATION_SUCCEEDED: "
        f"head={result.head} baselined={result.baselined} "
        f"applied={','.join(result.applied) or '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
