"""Emit a safe read-only pre-extraction retirement inventory, never mutate data."""

import json

from app.modules.knowledge.infrastructure.code_retirement_inventory import CodeRetirementInventory
from app.shared.config import load_settings
from app.shared.database import Database


def main() -> int:
    database = None
    try:
        database = Database(load_settings().database_dsn)
        result = CodeRetirementInventory(database).inspect()
        print(json.dumps(result, ensure_ascii=False, default=str, sort_keys=True))
        return 0
    except Exception:
        # Never print a driver exception: it may contain SQL or connection material.
        print('{"error_code":"code_retirement_inventory_unavailable"}')
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
