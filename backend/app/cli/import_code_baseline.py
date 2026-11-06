"""Explicit deployment admission; never updates the original repository or assumes SVN revision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.modules.knowledge.infrastructure.code_baseline import (
    CodeBaselineAdmission,
    admission_statistics,
)
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="预检或冻结当前 MES 代码基线；不执行模型、SVN、DDL 或自动发布"
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--snapshot-root", type=Path)
    parser.add_argument("--local-root-key", default="mes-current")
    parser.add_argument("--source-code", default="mes-code")
    parser.add_argument("--base-code", default="mes-business-rules")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    db = None
    try:
        collector = LocalCodeCollector(args.source_root)
        frozen = collector.freeze()
        if not args.commit:
            result = admission_statistics(frozen)
        else:
            if args.snapshot_root is None:
                raise CodeKnowledgeError("code_snapshot_root_required")
            db = Database(load_settings().database_dsn)
            if db.engine != "postgres":
                raise CodeKnowledgeError("code_postgres_required")
            SchemaHeadValidator(db, default_migrations_dir()).require_current()
            result = CodeBaselineAdmission(db, args.snapshot_root).admit(
                collector,
                frozen,
                source_code=args.source_code,
                base_code=args.base_code,
                local_root_key=args.local_root_key,
            )
        print(
            json.dumps(
                {
                    "event": "code_baseline_admitted" if args.commit else "code_preflight_passed",
                    **result,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except CodeKnowledgeError as exc:
        print(json.dumps({"event": "code_admission_failed", "error_code": exc.code}))
        return 1
    except Exception:
        print('{"event":"code_admission_failed","error_code":"code_admission_unavailable"}')
        return 1
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
