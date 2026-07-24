from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.modules.attachments.storage import S3ObjectStorage
from app.modules.job.application.legacy_runtime_purge_service import (
    LegacyRuntimePurgeService,
)
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir


CONFIRMATION = "delete-legacy-agent-runtime"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report or delete all pre-execution-policy Agent runtime test data "
            "while preserving control-plane configuration"
        )
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if args.apply and args.confirm != CONFIRMATION:
        raise SystemExit(
            f"--apply requires --confirm {CONFIRMATION}"
        )

    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        migration = default_migrations_dir() / "013_agent_job_execution_policy.sql"
        database.execute_script(Path(migration).read_text())
        storage = S3ObjectStorage(settings.object_storage)
        service = LegacyRuntimePurgeService(
            database=database,
            storage=storage,
            storage_bucket=settings.object_storage.bucket,
        )
        report = service.purge() if args.apply else service.report()
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
