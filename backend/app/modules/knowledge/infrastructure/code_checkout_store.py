"""Stable checkout registration and transaction primitives; no SVN or model execution."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
import uuid

from app.modules.knowledge.domain.code_answers import code_path
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.database import Database


def json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def checkout_scope(values: Any) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise CodeKnowledgeError("CODE_SCOPE_INVALID")
    paths = sorted({code_path(p, root=True) for p in values})
    if len(paths) != len(values) or any(
        parent == "" or path.startswith(parent + "/")
        for i, path in enumerate(paths)
        for parent in paths[:i]
    ):
        raise CodeKnowledgeError("CODE_SCOPE_INVALID")
    return paths


class CodeCheckoutStore:
    def __init__(self, database: Database) -> None:
        self.db = database

    def t(self, name: str) -> str:
        return table(self.db, name)

    def row(self, name: str, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        if name not in {"code_checkout", "code_analysis", "code_svn_operation", "code_index_task"}:
            raise ValueError("Invalid coordination table")
        if lock and self.db.current_unit_of_work is None:
            raise RuntimeError("Row lock requires a transaction")
        suffix = " FOR UPDATE" if lock and self.db.engine == "postgres" else ""
        row = self.db.execute_one(f"SELECT * FROM {self.t(name)} WHERE id=?{suffix}", (identifier,))
        if row is None:
            raise CodeKnowledgeError("CODE_OBJECT_NOT_FOUND")
        return row

    def register_repository(self, repository_uuid: str, branch: str, root_url: str) -> str:
        branch = code_path(branch.strip("/"), root=True)
        try:
            identity = str(uuid.UUID(repository_uuid))
            url = urlsplit(root_url)
            if (
                url.scheme not in {"http", "https", "svn"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise CodeKnowledgeError("CODE_REPOSITORY_INVALID") from None
        source_id = stable_id("svn-source", identity, branch)
        stamp = now()
        with self.db.unit_of_work():
            insert(
                self.db,
                "source",
                dict(
                    id=source_id,
                    code="svn-" + source_id,
                    display_name="SVN /" + branch,
                    source_system="svn",
                    origin_state="verified",
                    identity_metadata={"repository_uuid": identity, "branch_path": branch},
                    created_at=stamp,
                ),
                conflict="ON CONFLICT(id) DO NOTHING",
            )
            insert(
                self.db,
                "code_repository",
                dict(
                    source_id=source_id,
                    repository_uuid=identity,
                    branch_path=branch,
                    repository_root_url=root_url.rstrip("/"),
                    verified_at=stamp,
                    created_at=stamp,
                ),
                conflict="ON CONFLICT(source_id) DO NOTHING",
            )
        return source_id

    def register_checkout(
        self,
        *,
        source_id: str,
        root_key: str,
        root: Path,
        relative_dir: str,
        selected_paths: list[str],
    ) -> dict[str, Any]:
        relative_dir = code_path(relative_dir)
        if root_key != "code-svn-checkout":
            raise CodeKnowledgeError("CODE_CHECKOUT_ROOT_UNREGISTERED")
        paths = checkout_scope(selected_paths)
        resolved_root = root.resolve(strict=True)
        candidate = resolved_root / relative_dir
        # Aliases and symlinked parents must not create another lock identity.
        if candidate.resolve(strict=True) != candidate or not candidate.is_dir():
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
        candidate.relative_to(resolved_root)
        stat = candidate.stat()
        physical = digest([stat.st_dev, stat.st_ino])
        identity = stable_id("checkout", root_key, relative_dir)
        with source_lock(self.db, "code-checkout-registration"), self.db.unit_of_work():
            existing = self.db.execute(
                f"SELECT id,source_id,root_key,relative_dir,physical_key,selected_paths_json FROM {self.t('code_checkout')}"
            )
            for item in existing:
                if item["id"] == identity:
                    if (
                        item["source_id"] != source_id
                        or item["physical_key"] != physical
                        or json_value(item["selected_paths_json"]) != paths
                    ):
                        raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
                    return self.row("code_checkout", identity)
                overlap = item["root_key"] == root_key and (
                    relative_dir.startswith(item["relative_dir"] + "/")
                    or item["relative_dir"].startswith(relative_dir + "/")
                )
                if overlap or item["physical_key"] == physical:
                    raise CodeKnowledgeError("CODE_CHECKOUT_OVERLAP")
            stamp = now()
            insert(
                self.db,
                "code_checkout",
                dict(
                    id=identity,
                    source_id=source_id,
                    root_key=root_key,
                    relative_dir=relative_dir,
                    physical_key=physical,
                    selected_paths_json=paths,
                    state="preparing",
                    created_at=stamp,
                    updated_at=stamp,
                ),
            )
            return self.row("code_checkout", identity)

    def reserve_checkout(
        self, *, source_id: str, relative_dir: str, selected_paths: list[str]
    ) -> dict[str, Any]:
        """Reserve a not-yet-created directory; no invented inode or verified revision."""
        relative_dir = code_path(relative_dir)
        paths = checkout_scope(selected_paths)
        root_key = "code-svn-checkout"
        identity = stable_id("checkout", root_key, relative_dir)
        with source_lock(self.db, "code-checkout-registration"), self.db.unit_of_work():
            rows = self.db.execute(
                f"SELECT relative_dir FROM {self.t('code_checkout')} WHERE root_key=?", (root_key,)
            )
            if any(
                relative_dir == row["relative_dir"]
                or relative_dir.startswith(row["relative_dir"] + "/")
                or row["relative_dir"].startswith(relative_dir + "/")
                for row in rows
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_OVERLAP")
            stamp = now()
            insert(
                self.db,
                "code_checkout",
                dict(
                    id=identity,
                    source_id=source_id,
                    root_key=root_key,
                    relative_dir=relative_dir,
                    selected_paths_json=paths,
                    state="preparing",
                    created_at=stamp,
                    updated_at=stamp,
                ),
            )
            return self.row("code_checkout", identity)

    def identify_reserved_checkout(self, identifier: str, *, root: Path, operation_id: str) -> str:
        """Called after exclusive publication, inside the completion transaction."""
        row = self.row("code_checkout", identifier, lock=True)
        if row["state"] != "preparing" or row["writer_operation_id"] != operation_id:
            raise CodeKnowledgeError("CODE_CHECKOUT_CHANGED")
        if root.resolve(strict=True) != root:
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
        path = root / code_path(row["relative_dir"])
        if path.resolve(strict=True) != path or not path.is_dir():
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
        physical = persistent_identity(path)
        other = self.db.execute_one(
            f"SELECT id FROM {self.t('code_checkout')} WHERE physical_key=? AND id<>?",
            (physical, identifier),
        )
        if other:
            raise CodeKnowledgeError("CODE_CHECKOUT_OVERLAP")
        self.db.execute(
            f"UPDATE {self.t('code_checkout')} SET physical_key=? WHERE id=?",
            (physical, identifier),
        )
        return physical
