"""Per-Job authorization over a deployment-owned read-only source volume.

The model cannot pick the snapshot, volume root, grant or output destination.
Ordinary Job sandboxes have no CodeSourceMount and cannot reach this volume.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_package import sha256
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.code_source import _read_beneath, relative_path
from app.modules.knowledge.infrastructure.code_snapshot_directory import (
    CodeSnapshotDirectory,
    directory_id,
)


class CodeSourceMount:
    def __init__(
        self,
        *,
        root: Path,
        snapshot_id: str,
        manifest_hash: str,
        allowed_prefixes: tuple[str, ...],
        recheck: Callable[[], None],
    ) -> None:
        self.snapshot_id = directory_id(snapshot_id)
        self.root = root / self.snapshot_id / "text"
        self.recheck = recheck
        recheck()
        manifest = CodeSnapshotDirectory(root).verify(snapshot_id, manifest_hash)
        self.allowed_prefixes = tuple(
            relative_path(prefix).rstrip("/") for prefix in allowed_prefixes
        )
        if not self.allowed_prefixes:
            raise CodeKnowledgeError("code_mount_scope_empty")
        self.files = {
            entry["path"]: entry for entry in manifest["files"] if self._allowed(entry["path"])
        }

    def _allowed(self, path: str) -> bool:
        return any(
            path == prefix or path.startswith(prefix + "/") for prefix in self.allowed_prefixes
        )

    def _path(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        if value.startswith("source/"):
            return relative_path(value[len("source/") :])
        prefix = str(self.root) + "/"
        if value.startswith(prefix):
            return relative_path(value[len(prefix) :])
        return None

    def authorize(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        self.recheck()
        path_field = "path" if tool in {"Grep", "Glob"} else "file_path"
        path = self._path(arguments.get(path_field))
        if path is None:
            return None  # Existing sandbox policy handles or rejects other paths.
        if tool not in {"Read", "Glob", "Grep"} or not self._allowed(path):
            raise CodeKnowledgeError("code_mount_access_denied")
        if tool == "Read":
            return self._read(path, arguments)
        return self._search(tool, path, arguments)

    def _read(self, path: str, arguments: dict[str, Any]) -> dict[str, Any]:
        original_path = path.removesuffix(".evidence.txt")
        if set(arguments) - {"file_path", "offset", "limit"} or original_path not in self.files:
            raise CodeKnowledgeError("code_mount_read_invalid")
        start, count = arguments.get("offset", 1), arguments.get("limit", 400)
        if type(start) is not int or type(count) is not int or start < 1 or not 1 <= count <= 400:
            raise CodeKnowledgeError("code_mount_read_limit")
        entry = self.files[original_path]
        data = _read_beneath(self.root, path, 15 * 1024 * 1024)
        expected_hash = (
            sha256((canonical_json(entry) + "\n").encode())
            if original_path != path
            else entry["representation_hash"]
        )
        if sha256(data) != expected_hash:
            raise CodeKnowledgeError("code_source_changed")
        lines = data.splitlines(keepends=True)
        if sum(len(line) for line in lines[start - 1 : start - 1 + count]) > 64 * 1024:
            raise CodeKnowledgeError("code_mount_read_limit")
        return {"file_path": str(self.root / path), "offset": start, "limit": count}

    def _search(self, tool: str, path: str, arguments: dict[str, Any]) -> dict[str, Any]:
        fields = {"path", "pattern", "output_mode"} if tool == "Grep" else {"path", "pattern"}
        if set(arguments) - fields:
            raise CodeKnowledgeError("code_mount_search_invalid")
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= 1024:
            raise CodeKnowledgeError("code_mount_search_invalid")
        candidates = [name for name in self.files if name == path or name.startswith(path + "/")]
        if not candidates:
            raise CodeKnowledgeError("code_mount_search_empty_scope")
        mode = arguments.get("output_mode", "files_with_matches")
        if tool == "Grep" and mode == "content":
            # Content search is limited to one verified file. Bound the worst
            # possible output before handing the search to the native tool.
            if path not in self.files:
                raise CodeKnowledgeError("code_mount_search_requires_file")
            data = _read_beneath(self.root, path, 15 * 1024 * 1024)
            if sha256(data) != self.files[path]["representation_hash"]:
                raise CodeKnowledgeError("code_source_changed")
            row_bytes = max((len(line) for line in data.splitlines()), default=0)
            row_bytes += len(str(self.root / path).encode()) + 32
            if row_bytes * 40 > 64 * 1024:
                raise CodeKnowledgeError("code_mount_search_limit")
            return {
                "path": str(self.root / path),
                "pattern": pattern,
                "output_mode": "content",
                "-n": True,
                "head_limit": 40,
            }
        if tool == "Grep" and mode != "files_with_matches":
            raise CodeKnowledgeError("code_mount_search_invalid")
        if tool == "Glob":
            if pattern.startswith("/") or ".." in pattern.split("/") or "\\" in pattern:
                raise CodeKnowledgeError("code_mount_search_invalid")
            # Conservative across native glob implementations; narrow the directory on overflow.
            possible = set(candidates + [name + ".evidence.txt" for name in candidates])
            for name in candidates:
                possible.update(str(parent) for parent in Path(name).parents if str(parent) != ".")
            if len(possible) > 100:
                raise CodeKnowledgeError("code_mount_search_limit")
            return {"path": str(self.root / path), "pattern": pattern}
        # Return only bounded locations; long source lines cannot leak through a grep result.
        return {
            "path": str(self.root / path),
            "pattern": pattern,
            "output_mode": "files_with_matches",
            "head_limit": 100,
        }
