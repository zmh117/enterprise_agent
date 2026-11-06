"""Deployment CLI: verify a registered SVN source, never accept credentials as arguments."""

import argparse
import json
from pathlib import Path

from app.modules.knowledge.infrastructure.code_svn_registration import CodeSvnRegistration
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_source_registry import CodeSourceRegistry
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核验 SVN 版本与当前本地基线；默认仅预检")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--auth-root", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--registration-key", required=True)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--local-snapshot-id")
    parser.add_argument("--establish-origin", action="store_true")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    db = None
    try:
        db = Database(load_settings().database_dsn)
        if db.engine != "postgres":
            raise CodeKnowledgeError("code_postgres_required")
        SchemaHeadValidator(db, default_migrations_dir()).require_current()
        result = CodeSvnRegistration(
            db, CodeSourceRegistry(args.registry, args.auth_root), args.snapshot_root
        ).verify(
            args.source_id,
            args.registration_key,
            args.revision,
            local_snapshot_id=args.local_snapshot_id,
            establish_origin=args.establish_origin,
            commit=args.commit,
        )
        print(json.dumps({"event": "code_svn_registration", **result}, ensure_ascii=False))
        return 0
    except CodeKnowledgeError as exc:
        print(json.dumps({"event": "code_svn_registration_failed", "error_code": exc.code}))
        return 1
    except Exception:
        print('{"event":"code_svn_registration_failed","error_code":"code_svn_unavailable"}')
        return 1
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
