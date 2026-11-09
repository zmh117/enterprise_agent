"""Maintenance-only retirement. Requires a freshly reviewed metadata inventory."""

import argparse
import json

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_retirement import CodeRetirement
from app.shared.config import load_settings
from app.shared.database import Database


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-digest", required=True)
    parser.add_argument("--old-containers-stopped", action="store_true", required=True)
    args = parser.parse_args()
    database = None
    try:
        database = Database(load_settings().database_dsn)
        result = CodeRetirement(database).retire(args.inventory_digest)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.code
                    if isinstance(exc, CodeKnowledgeError)
                    else "CODE_RETIREMENT_FAILED"
                }
            )
        )
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
