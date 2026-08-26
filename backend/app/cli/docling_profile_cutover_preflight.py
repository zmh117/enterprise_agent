from __future__ import annotations

import json

from app.modules.document_processing.cutover import DoclingProfileCutoverPreflight
from app.shared.config import load_settings
from app.shared.database import Database


def main() -> int:
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        report = DoclingProfileCutoverPreflight(database).run()
    except Exception:
        print("DOCLING_PROFILE_CUTOVER_PREFLIGHT_FAILED: database facts are unavailable")
        return 1
    finally:
        database.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
