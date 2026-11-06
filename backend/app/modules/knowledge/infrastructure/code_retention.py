"""Deployment retention of source bytes; historical knowledge and evidence locators survive."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import shutil
import stat
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.code_snapshot_directory import (
    CodeSnapshotDirectory,
    directory_id,
)
from app.modules.knowledge.infrastructure.storage import table, source_lock
from app.shared.database import Database


class CodeSourceRetention:
    def __init__(self, database: Database, root: Path) -> None:
        self.db, self.directory = database, CodeSnapshotDirectory(root)

    def retire(
        self, snapshot_id: str, *, keep_days: int = 30, commit: bool = False
    ) -> dict[str, Any]:
        if type(keep_days) is not int or not 1 <= keep_days <= 3650:
            raise CodeKnowledgeError("code_retention_policy_invalid")
        directory_id(snapshot_id)
        source = self.db.execute_one(
            f"select * from {table(self.db, 'code_source_snapshot')} where id=?",
            (snapshot_id,),
        )
        if not source:
            raise CodeKnowledgeError("code_source_unavailable")
        with source_lock(self.db, source["source_id"]), self.db.unit_of_work():
            self._eligible(source, keep_days)
            if commit:
                self.db.execute(
                    f"update {table(self.db, 'code_source_snapshot')} set retired_at=coalesce(retired_at,?) where id=?",
                    (now(), snapshot_id),
                )
                files = self.db.execute(
                    f"select file_id,artifact_json from {table(self.db, 'code_source_file')} where source_snapshot_id=?",
                    (snapshot_id,),
                )
                for file in files:
                    artifact = {**decoded(file["artifact_json"]), "available": False}
                    self.db.execute(
                        f"update {table(self.db, 'code_source_file')} set artifact_json=? where source_snapshot_id=? and file_id=?",
                        (canonical_json(artifact), snapshot_id, file["file_id"]),
                    )
        # Authorization is revoked durably before deleting bytes; crash recovery
        # retries this same identifier, never re-enables an old mount.
        if commit:
            self._remove(snapshot_id)
        return {
            "source_snapshot_id": snapshot_id,
            "state": "RETIRED" if commit else "ELIGIBLE",
            "keep_days": keep_days,
        }

    def _eligible(self, source: dict[str, Any], keep_days: int) -> None:
        created = source["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if source["retired_at"] is None and datetime.now(UTC) - created < timedelta(days=keep_days):
            raise CodeKnowledgeError("code_source_retention_not_due")
        pending = self.db.execute_one(
            f"select id from {table(self.db, 'code_build')} where source_snapshot_id=? "
            "and stage in ('QUEUED','SOURCE_READY','EXTRACTING','VALIDATING','INDEXING') limit 1",
            (source["id"],),
        )
        live = self.db.execute_one(
            f"select i.invocation_id from agent_runtime_invocation i join {table(self.db, 'code_unit')} u on u.job_id=i.job_id "
            f"join {table(self.db, 'code_build')} b on b.id=u.build_id where b.source_snapshot_id=? "
            "and i.state<>'PREPARED' and i.execution_quiesced_at is null limit 1",
            (source["id"],),
        )
        if pending or live:
            raise CodeKnowledgeError("code_source_retention_in_use")

    def _remove(self, snapshot_id: str) -> None:
        target = self.directory.root / snapshot_id
        retired = self.directory.root / (".retired-" + snapshot_id)
        if target.is_symlink() or retired.is_symlink():
            raise CodeKnowledgeError("code_source_retention_path_invalid")
        if target.exists():
            if retired.exists():
                raise CodeKnowledgeError("code_source_retention_path_invalid")
            target.rename(retired)
        if not retired.exists():
            return
        paths = [retired]
        for path in retired.rglob("*"):
            mode = path.lstat().st_mode
            if len(paths) >= 250_000 or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise CodeKnowledgeError("code_source_retention_path_invalid")
            paths.append(path)
        for path in paths:
            os.chmod(path, 0o700 if path.is_dir() else 0o600, follow_symlinks=False)
        shutil.rmtree(retired)
