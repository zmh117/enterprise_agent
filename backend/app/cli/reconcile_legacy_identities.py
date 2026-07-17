from __future__ import annotations

import argparse
import json

from app.modules.identity.application import LegacyIdentityMigrationService
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report or apply unambiguous legacy user-subject reconciliation"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        database.run_migrations(default_migrations_dir())
        report = LegacyIdentityMigrationService(
            IdentityRepository(database)
        ).reconcile(apply=args.apply)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        database.close()


if __name__ == "__main__":
    main()
