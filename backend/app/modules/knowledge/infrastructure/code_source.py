"""Deployment-only read-only source admission. Never follow links or read runtime configs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from app.modules.knowledge.domain.code_contracts import (
    COMPONENTS,
    CodeKnowledgeError,
    MAX_PACKAGE_BYTES,
)
from app.modules.knowledge.domain.code_package import EvidenceSource, sha256
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import digest

EXTENSIONS = frozenset({".c", ".cc", ".cpp", ".h", ".hpp", ".vue", ".js", ".ts", ".sql"})
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".svn",
        "node_modules",
        "vendor",
        "third_party",
        "thirdparty",
        "3rdtools",
        "dist",
        "build",
        "bin",
        "obj",
        "logs",
        "log",
        "data",
        "export",
        "exports",
        "backup",
        "backups",
        "generated",
        "coverage",
        "config",
        "configs",
        "configuration",
        "settings",
        "secret",
        "secrets",
        "credentials",
    }
)
SENSITIVE_NAME = re.compile(
    r"(?:^|[._-])(?:env|secret|credentials?|password|token|cookie|config)(?:[._-]|$)", re.I
)
# Conservative admission: exclude the whole file, do not redact while retaining a false hash.
SENSITIVE_CONTENT = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b|"
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_+/=.-]{12,}|"
    r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|cookie)\s*['\"]?\s*[:=]\s*['\"][^'\"\r\n]{3,}['\"]|"
    r"[a-z]+://[^\s/:]+:[^\s/@]+@",
    re.I,
)


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or "\0" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise CodeKnowledgeError("code_source_path_invalid")
    return path.as_posix()


def component_role(path: str) -> str | None:
    return next((role for role, root in COMPONENTS.items() if path.startswith(root + "/")), None)


def _read_beneath(root: Path, relative: str, limit: int) -> bytes:
    """Open every component relative to a held directory FD, disallowing symlink races."""
    parts = relative_path(relative).split("/")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise CodeKnowledgeError("code_source_file_size_or_type")
            with os.fdopen(os.dup(file_fd), "rb") as stream:
                data = stream.read(limit + 1)
            after = os.fstat(file_fd)
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or len(data) > limit:
                raise CodeKnowledgeError("code_source_changed")
            return data
        finally:
            os.close(file_fd)
    except OSError:
        raise CodeKnowledgeError("code_source_unreadable_or_link") from None
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class FrozenSource:
    manifest: dict[str, Any]
    files: dict[str, EvidenceSource]
    source_ref: dict[str, Any]


class LocalCodeCollector:
    def __init__(
        self, root: Path, *, max_files: int = 30_000, max_total_bytes: int = 512 * 1024 * 1024
    ) -> None:
        # Only deployment CLI supplies this root. A web API must use registered source IDs.
        if (
            not root.is_absolute()
            or root.resolve() != root
            or root.is_symlink()
            or not root.is_dir()
        ):
            raise CodeKnowledgeError("code_source_root_invalid")
        self.root = root
        self.max_files, self.max_total_bytes = max_files, max_total_bytes

    def _inventory(self) -> tuple[list[str], list[dict[str, str]]]:
        included, excluded = [], []
        for role, component in COMPONENTS.items():
            start = self.root / component
            if (
                any(
                    (self.root / Path(*Path(component).parts[:i])).is_symlink()
                    for i in range(1, len(Path(component).parts) + 1)
                )
                or not start.is_dir()
            ):
                raise CodeKnowledgeError("code_source_component_missing_or_link")

            def walk_error(_: OSError) -> None:
                raise CodeKnowledgeError("code_source_inventory_incomplete")

            for directory, dirs, files in os.walk(start, followlinks=False, onerror=walk_error):
                for name in list(dirs):
                    child = Path(directory) / name
                    if child.is_symlink() or name.lower() in EXCLUDED_DIRECTORIES:
                        dirs.remove(name)
                        excluded.append(
                            {
                                "path": child.relative_to(self.root).as_posix(),
                                "reason": "directory_policy",
                            }
                        )
                for name in files:
                    child = Path(directory) / name
                    path = child.relative_to(self.root).as_posix()
                    if (
                        child.is_symlink()
                        or child.suffix.lower() not in EXTENSIONS
                        or SENSITIVE_NAME.search(name)
                    ):
                        excluded.append({"path": path, "reason": "file_policy"})
                    else:
                        included.append(path)
                    if len(included) + len(excluded) > self.max_files:
                        raise CodeKnowledgeError("code_source_inventory_limit")
        # Other frontend versions are never traversed; explicit boundary remains in the manifest.
        return sorted(included), sorted(excluded, key=lambda row: row["path"])

    def freeze(self) -> FrozenSource:
        paths, excluded = self._inventory()
        files, entries = {}, []
        total = 0
        for path in paths:
            raw = _read_beneath(self.root, path, MAX_PACKAGE_BYTES)
            total += len(raw)
            if total > self.max_total_bytes:
                raise CodeKnowledgeError("code_source_total_limit")
            try:
                text, encoding = _decode(raw)
            except CodeKnowledgeError as exc:
                if exc.code not in {"code_source_encoding_unknown", "code_source_binary"}:
                    raise
                excluded.append({"path": path, "reason": exc.code})
                continue
            if SENSITIVE_CONTENT.search(text):
                excluded.append({"path": path, "reason": "sensitive_content"})
                continue
            representation = text.replace("\r\n", "\n").replace("\r", "\n")
            file_id = stable_id("code_source_file", path, sha256(raw))
            files[file_id] = EvidenceSource(
                path, sha256(raw), sha256(representation.encode()), representation
            )
            entries.append(
                dict(
                    file_id=file_id,
                    path=path,
                    role=component_role(path),
                    encoding=encoding,
                    raw_hash=sha256(raw),
                    representation_hash=sha256(representation.encode()),
                    size_bytes=len(raw),
                    lines=len(representation.splitlines()),
                )
            )
        manifest = dict(
            contract_version="code-source/v1",
            components=COMPONENTS,
            excluded_frontends="all_except_EBR_JTH",
            files=entries,
            excluded=sorted(excluded, key=lambda row: row["path"]),
            scan_complete=True,
            inventory_hash=digest(paths),
            eol_policy="raw_hash_exact;representation_LF;line_numbers_preserved",
        )
        self.verify_stable(manifest, original_inventory=paths)
        source_ref = dict(
            kind="local_bundle",
            bundle_id=stable_id("code_bundle", digest(manifest)),
            manifest_hash=digest(manifest),
            svn_revision=None,
        )
        return FrozenSource(manifest, files, source_ref)

    def verify_stable(
        self, manifest: dict[str, Any], *, original_inventory: list[str] | None = None
    ) -> None:
        paths, _ = self._inventory()
        if manifest.get("inventory_hash") != digest(paths):
            raise CodeKnowledgeError("code_source_changed")
        if original_inventory is not None and paths != original_inventory:
            raise CodeKnowledgeError("code_source_changed")
        for entry in manifest["files"]:
            if (
                sha256(_read_beneath(self.root, entry["path"], MAX_PACKAGE_BYTES))
                != entry["raw_hash"]
            ):
                raise CodeKnowledgeError("code_source_changed")


def _decode(raw: bytes) -> tuple[str, str]:
    if b"\0" in raw:
        raise CodeKnowledgeError("code_source_binary")
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise CodeKnowledgeError("code_source_encoding_unknown")
