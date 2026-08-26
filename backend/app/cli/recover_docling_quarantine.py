from __future__ import annotations

import argparse
import json

from app.modules.document_processing.cutover import DoclingQuarantineRecovery
from app.shared.config import load_settings
from app.shared.database import Database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover quarantined Docling slots after a controlled engine restart"
    )
    parser.add_argument("--confirm-docling-restarted", action="store_true")
    args = parser.parse_args()
    database = Database(load_settings().database_dsn)
    try:
        report = DoclingQuarantineRecovery(database).run(
            docling_restarted=bool(args.confirm_docling_restarted)
        )
    except Exception:
        print("DOCLING_QUARANTINE_RECOVERY_FAILED: database facts are unavailable")
        return 1
    finally:
        database.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "recovered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
