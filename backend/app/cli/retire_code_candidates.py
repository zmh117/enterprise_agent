"""Dry-run first, then retire exactly the reviewed unindexed v1 candidates."""

import argparse
import json

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_candidate_retirement import CodeCandidateRetirement
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="清理指定来源的旧 v1 候选，保留源码和执行审计；默认预检"
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--expected-digest")
    args = parser.parse_args(argv)
    db = Database(load_settings().database_dsn)
    try:
        SchemaHeadValidator(db, default_migrations_dir()).require_current()
        result = CodeCandidateRetirement(db).retire(
            args.source_id, expected_digest=args.expected_digest
        )
        print(json.dumps(result))
        return 0
    except CodeKnowledgeError as exc:
        print(json.dumps(dict(error_code=exc.code)))
        return 1
    except Exception:
        print(json.dumps(dict(error_code="code_candidate_retirement_unavailable")))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
