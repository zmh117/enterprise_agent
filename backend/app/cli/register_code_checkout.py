"""Register an existing working copy during maintenance; no checkout/update/copy."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_client import WorkingCopyClient, registry
from app.modules.knowledge.infrastructure.code_checkout_store import CodeCheckoutStore
from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def register_existing(
    db: Database,
    *,
    entry: dict[str, str],
    root: Path,
    auth_root: Path,
    directory: str,
    paths: list[str],
) -> dict[str, Any]:
    from app.modules.knowledge.domain.code_answers import code_path
    from app.modules.knowledge.infrastructure.code_checkout_store import checkout_scope

    paths = checkout_scope(paths)
    directory = code_path(directory)
    candidate = root / directory
    if root.resolve(strict=True) != root or candidate.resolve(strict=True) != candidate:
        raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
    client = WorkingCopyClient(entry, auth_root)
    info = client.source.preflight(client.source.head())
    store = CodeCheckoutStore(db)
    source = store.register_repository(
        entry["repository_uuid"], entry["branch_path"], info["repository_root_url"]
    )
    checkout = store.register_checkout(
        source_id=source,
        root_key="code-svn-checkout",
        root=root,
        relative_dir=directory,
        selected_paths=paths,
    )
    with db.unit_of_work():
        current = store.row("code_checkout", checkout["id"], lock=True)
        if current["writer_operation_id"] or db.execute_one(
            f"SELECT id FROM {store.t('code_analysis')} WHERE checkout_id=? AND closed_at IS NULL LIMIT 1",
            (checkout["id"],),
        ):
            raise CodeKnowledgeError("WORKSPACE_BUSY")
        verified = SvnWorkingCopy(
            client.source, candidate, paths, physical_key=checkout["physical_key"]
        ).inspect()
        stamp = timestamp(database_now(db))
        db.execute(
            f"UPDATE {store.t('code_checkout')} SET state='ready',verified_revision=?,verified_at=?,invalid_reason=NULL,updated_at=? WHERE id=?",
            (verified["operative_revision"], stamp, stamp, checkout["id"]),
        )
        return {
            "checkout_id": checkout["id"],
            "source_id": source,
            "svn_revision": verified["operative_revision"],
            "relative_dir": directory,
            "selected_paths": paths,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--select", action="append", default=[])
    args = parser.parse_args()
    database = None
    try:
        database = Database(load_settings().database_dsn)
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        entries = registry(Path(os.environ["CODE_CHECKOUT_REGISTRY_FILE"]))
        result = register_existing(
            database,
            entry=entries[args.registration],
            root=Path(os.environ["CODE_CHECKOUT_ROOT"]),
            auth_root=Path(os.environ["CODE_SVN_AUTH_ROOT"]),
            directory=args.directory,
            paths=args.select or [""],
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.code
                    if isinstance(exc, CodeKnowledgeError)
                    else "CODE_CHECKOUT_REGISTRATION_FAILED"
                }
            )
        )
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
