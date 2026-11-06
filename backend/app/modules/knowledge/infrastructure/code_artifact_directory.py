"""Atomic, invocation-bound extraction artifacts on a controlled shared volume."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, MAX_PACKAGE_BYTES
from app.modules.knowledge.domain.code_package import decode_package, parse_json, sha256
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_source import _read_beneath


class CodeArtifactDirectory:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
            raise CodeKnowledgeError("code_artifact_root_invalid")
        self.root = root

    @staticmethod
    def key(binding: dict[str, Any]) -> str:
        return digest(binding)

    def publish(
        self, sandbox: Path, binding: dict[str, Any], *, sealed_candidate: bytes | None = None
    ) -> dict[str, Any]:
        files = {
            name: _read_beneath(sandbox, "outputs/" + name, limit)
            for name, limit in (("candidate.txt", MAX_PACKAGE_BYTES), ("report.md", 512 * 1024))
        }
        if sealed_candidate is not None:
            files["candidate.txt"] = sealed_candidate
        package = decode_package(files["candidate.txt"])
        if package["manifest.json"] != binding["grant"]["candidate_manifest"]:
            raise CodeKnowledgeError("code_artifact_binding_mismatch")
        files["report.md"].decode("utf-8")
        manifest = {
            "binding": binding,
            "files": {
                name: {"sha256": sha256(data), "size": len(data)} for name, data in files.items()
            },
        }
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / self.key(binding)
        if target.exists():
            if self.read(binding)[0] != manifest:
                raise CodeKnowledgeError("code_artifact_conflict")
            return manifest
        staging = Path(tempfile.mkdtemp(prefix=".artifact-", dir=self.root))
        try:
            for name, data in {**files, "manifest.json": canonical_json(manifest).encode()}.items():
                with (staging / name).open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(staging / name, 0o444)
            os.chmod(staging, 0o555)
            try:
                staging.rename(target)
            except FileExistsError:
                if self.read(binding)[0] != manifest:
                    raise CodeKnowledgeError("code_artifact_conflict") from None
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return manifest
        finally:
            if staging.exists():
                os.chmod(staging, 0o700)
                shutil.rmtree(staging)

    def read(self, binding: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
        root = self.root / self.key(binding)
        manifest = parse_json(_read_beneath(root, "manifest.json", 256 * 1024).decode())
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"binding", "files"}
            or manifest["binding"] != binding
        ):
            raise CodeKnowledgeError("code_artifact_binding_mismatch")
        if set(manifest["files"]) != {"candidate.txt", "report.md"}:
            raise CodeKnowledgeError("code_artifact_files_invalid")
        files = {}
        for name, limit in (("candidate.txt", MAX_PACKAGE_BYTES), ("report.md", 512 * 1024)):
            data = _read_beneath(root, name, limit)
            if manifest["files"][name] != {"sha256": sha256(data), "size": len(data)}:
                raise CodeKnowledgeError("code_artifact_digest_mismatch")
            files[name] = data
        return manifest, files
