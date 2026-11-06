"""Immutable source directories for read-only Runtime mounts; no File Service or MinIO."""

from __future__ import annotations

import os
import fcntl
from pathlib import Path
import shutil
import tempfile
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, MAX_PACKAGE_BYTES
from app.modules.knowledge.domain.code_package import parse_json, sha256
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_source import (
    FrozenSource,
    LocalCodeCollector,
    _read_beneath,
)


def directory_id(value: str) -> str:
    if (
        not value
        or len(value) > 128
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in value
        )
    ):
        raise CodeKnowledgeError("code_directory_id_invalid")
    return value


class CodeSnapshotDirectory:
    def __init__(
        self, root: Path, *, max_bytes: int = 8 * 1024**3, max_snapshots: int = 100
    ) -> None:
        if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
            raise CodeKnowledgeError("code_snapshot_root_invalid")
        self.root = root
        if max_bytes < 1 or max_snapshots < 1:
            raise CodeKnowledgeError("code_snapshot_capacity_invalid")
        self.max_bytes, self.max_snapshots = max_bytes, max_snapshots

    def publish(
        self, snapshot_id: str, source: FrozenSource, collector: LocalCodeCollector
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.root / ".admission.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CodeKnowledgeError("code_snapshot_admission_busy") from None
            return self._publish(snapshot_id, source, collector)
        finally:
            os.close(descriptor)

    def _publish(
        self, snapshot_id: str, source: FrozenSource, collector: LocalCodeCollector
    ) -> Path:
        destination = self.root / directory_id(snapshot_id)
        self.root.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            self.verify(snapshot_id, source.source_ref["manifest_hash"])
            return destination
        self._capacity(source)
        staging = Path(tempfile.mkdtemp(prefix=".source-", dir=self.root))
        try:
            self._write_files(staging, source, collector)
            collector.verify_stable(source.manifest)
            _durable_file(staging / "manifest.json", canonical_json(source.manifest).encode())
            for path in staging.rglob("*"):
                if path.is_dir():
                    _sync_directory(path)
                os.chmod(path, 0o555 if path.is_dir() else 0o444)
            _sync_directory(staging)
            os.chmod(staging, 0o555)
            # A competing complete publication is immutable and must have the same digest.
            try:
                staging.rename(destination)
                _sync_directory(self.root)
            except FileExistsError:
                self.verify(snapshot_id, source.source_ref["manifest_hash"])
            self.verify(snapshot_id, source.source_ref["manifest_hash"])
            return destination
        finally:
            if staging.exists():
                for path in [staging, *staging.rglob("*")]:
                    os.chmod(path, 0o750 if path.is_dir() else 0o640)
                shutil.rmtree(staging)

    def _capacity(self, source: FrozenSource) -> None:
        existing = sum(
            1 for path in self.root.iterdir() if path.is_dir() and not path.name.startswith(".")
        )
        used = 0
        for count, path in enumerate(self.root.rglob("*")):
            if count > 250_000 or path.is_symlink():
                raise CodeKnowledgeError("code_snapshot_volume_invalid")
            if path.is_file():
                used += path.stat().st_size
        required = len(canonical_json(source.manifest).encode()) + sum(
            entry["size_bytes"]
            + len(source.files[entry["file_id"]].text.encode())
            + len(canonical_json(entry).encode())
            + 1
            for entry in source.manifest["files"]
        )
        if (
            existing >= self.max_snapshots
            or used + required > self.max_bytes
            or shutil.disk_usage(self.root).free < required + 64 * 1024 * 1024
        ):
            raise CodeKnowledgeError("code_snapshot_capacity_exceeded")

    @staticmethod
    def _write_files(staging: Path, source: FrozenSource, collector: LocalCodeCollector) -> None:
        for entry in source.manifest["files"]:
            raw = _read_beneath(collector.root, entry["path"], MAX_PACKAGE_BYTES)
            text = source.files[entry["file_id"]].text.encode("utf-8")
            if sha256(raw) != entry["raw_hash"] or sha256(text) != entry["representation_hash"]:
                raise CodeKnowledgeError("code_source_changed")
            for partition, data in (("raw", raw), ("text", text)):
                target = staging / partition / entry["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            metadata = staging / "text" / (entry["path"] + ".evidence.txt")
            _durable_file(metadata, (canonical_json(entry) + "\n").encode())

    def verify(self, snapshot_id: str, manifest_hash: str) -> dict[str, Any]:
        root = self.root / directory_id(snapshot_id)
        raw = _read_beneath(root, "manifest.json", MAX_PACKAGE_BYTES)
        manifest = parse_json(raw.decode("utf-8"))
        if not isinstance(manifest, dict) or digest(manifest) != manifest_hash:
            raise CodeKnowledgeError("code_manifest_digest_mismatch")
        for entry in manifest["files"]:
            for partition, field in (("raw", "raw_hash"), ("text", "representation_hash")):
                if (
                    sha256(_read_beneath(root, partition + "/" + entry["path"], MAX_PACKAGE_BYTES))
                    != entry[field]
                ):
                    raise CodeKnowledgeError("code_source_changed")
            metadata = _read_beneath(
                root, "text/" + entry["path"] + ".evidence.txt", MAX_PACKAGE_BYTES
            )
            if metadata != (canonical_json(entry) + "\n").encode():
                raise CodeKnowledgeError("code_source_changed")
        return manifest


def _durable_file(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
