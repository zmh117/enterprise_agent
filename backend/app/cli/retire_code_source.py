"""Explicit source-byte retirement; dry-run by default, never deletes knowledge."""

import argparse
import json
from pathlib import Path

from app.modules.knowledge.infrastructure.code_retention import CodeSourceRetention
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按保留期限退役一个明确源码快照；默认仅预检")
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--source-snapshot-id", required=True)
    parser.add_argument("--keep-days", type=int, default=30)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    db = None
    try:
        db = Database(load_settings().database_dsn)
        if db.engine != "postgres":
            raise CodeKnowledgeError("code_postgres_required")
        SchemaHeadValidator(db, default_migrations_dir()).require_current()
        result = CodeSourceRetention(db, args.snapshot_root).retire(
            args.source_snapshot_id,
            keep_days=args.keep_days,
            commit=args.commit,
        )
        print(json.dumps(result))
        return 0
    except CodeKnowledgeError as exc:
        print(json.dumps({"error_code": exc.code}))
        return 1
    except Exception:
        print('{"error_code":"code_source_retention_unavailable"}')
        return 1
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
