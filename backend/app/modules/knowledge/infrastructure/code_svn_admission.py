"""Pinned SVN admission: filter before persistence, then use the same immutable volume."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import tempfile
import time
from typing import Any, Iterator

from app.modules.knowledge.domain.code_contracts import (
    COMPONENTS,
    CodeKnowledgeError,
    MAX_PACKAGE_BYTES,
)
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_source import (
    EXCLUDED_DIRECTORIES,
    EXTENSIONS,
    SENSITIVE_CONTENT,
    SENSITIVE_NAME,
    FrozenSource,
    LocalCodeCollector,
    _decode,
    relative_path,
)
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource


def canonical_path(remote: str, components: dict[str, str]) -> str:
    for role, prefix in components.items():
        if remote.startswith(prefix + "/"):
            return COMPONENTS[role] + remote[len(prefix) :]
    raise CodeKnowledgeError("code_svn_path_outside_components")


class SvnSourceAdmission:
    def __init__(
        self,
        source: SvnCodeSource,
        components: dict[str, str],
        *,
        externals: dict[str, SvnCodeSource] | None = None,
    ) -> None:
        self.source, self.components, self.externals = source, components, externals or {}

    @contextmanager
    def prepare(
        self, revision: int, *, capture_floating: bool = False
    ) -> Iterator[tuple[LocalCodeCollector, FrozenSource]]:
        self.source.preflight_components(revision, self.components)
        dependencies = self.source.external_declarations(
            revision,
            approved=self.externals,
            capture_floating=capture_floating,
        )
        for dependency in dependencies["declarations"]:
            if dependency.get("path") and not any(
                dependency["path"].startswith(prefix + "/") for prefix in self.components.values()
            ):
                dependency.update(
                    state="EXCLUDED", critical=False, reason="outside_approved_components"
                )
            if dependency["state"] == "PINNED":
                path = canonical_path(dependency["path"], self.components)
                nested = self.externals[dependency["path"]].external_declarations(
                    dependency["revision"]
                )
                if (
                    any(part.lower() in EXCLUDED_DIRECTORIES for part in PurePosixPath(path).parts)
                    or nested["declarations"]
                ):
                    dependency.update(
                        state="UNRESOLVED", critical=True, reason="nested_or_excluded_external"
                    )
        dependencies["complete"] = all(
            d["state"] in {"PINNED", "EXCLUDED"} for d in dependencies["declarations"]
        )
        with tempfile.TemporaryDirectory(prefix="code-svn-admission-") as temporary:
            root = Path(temporary).resolve()
            for component in COMPONENTS.values():
                (root / component).mkdir(parents=True)
            budget = {"entries": 0, "bytes": 0, "deadline": time.monotonic() + 1800}
            excluded: list[dict[str, str]] = []
            for role, remote in self.components.items():
                self._copy(self.source, revision, remote, COMPONENTS[role], root, budget, excluded)
            for dependency in dependencies["declarations"]:
                if dependency["state"] != "PINNED":
                    continue
                path = dependency["path"]
                destination = canonical_path(path, self.components)
                self._copy(
                    self.externals[path],
                    dependency["revision"],
                    "",
                    destination,
                    root,
                    budget,
                    excluded,
                )
            collector = LocalCodeCollector(root)
            local = collector.freeze()
            manifest = {
                **local.manifest,
                "excluded": sorted(
                    excluded + local.manifest["excluded"], key=lambda item: item["path"]
                ),
                "svn_components": self.components,
                "externals": dependencies,
                "scan_complete": dependencies["complete"],
            }
            frozen = FrozenSource(
                manifest,
                local.files,
                {
                    "kind": "svn",
                    "repository_uuid": self.source.expected_uuid,
                    "branch_path": self.source.branch_path,
                    "revision": revision,
                    "manifest_hash": digest(manifest),
                    "component_paths": self.components,
                    "external_revisions": [
                        {
                            "path": canonical_path(item["path"], self.components),
                            "repository_uuid": item["repository_uuid"],
                            "branch_path": item["branch_path"],
                            "revision": item["revision"],
                        }
                        for item in dependencies["declarations"]
                        if item["state"] == "PINNED"
                    ],
                },
            )
            yield collector, frozen

    @staticmethod
    def _copy(
        source: SvnCodeSource,
        revision: int,
        remote: str,
        destination: str,
        root: Path,
        budget: dict[str, float],
        excluded: list[dict[str, str]],
    ) -> None:
        special = source.special_paths(revision)
        for entry in source.inventory(remote, revision):
            if time.monotonic() > budget["deadline"]:
                raise CodeKnowledgeError("code_source_admission_timeout")
            budget["entries"] += 1
            if budget["entries"] > 30_000:
                raise CodeKnowledgeError("code_source_inventory_limit")
            suffix = entry["path"]
            canonical = relative_path(destination + "/" + suffix)
            remote_file = relative_path(remote + "/" + suffix if remote else suffix)
            parts = PurePosixPath(suffix)
            # Skip forbidden directory contents without fetching them; preserve the directory boundary.
            excluded_parent = next(
                (i for i, p in enumerate(parts.parts) if p.lower() in EXCLUDED_DIRECTORIES), None
            )
            if excluded_parent is not None:
                if excluded_parent == len(parts.parts) - 1 and entry["kind"] == "dir":
                    excluded.append({"path": canonical, "reason": "directory_policy"})
                continue
            if entry["kind"] == "dir":
                continue
            if (
                remote_file in special
                or parts.suffix.lower() not in EXTENSIONS
                or SENSITIVE_NAME.search(parts.name)
            ):
                excluded.append({"path": canonical, "reason": "file_policy"})
                continue
            if entry["size_bytes"] > MAX_PACKAGE_BYTES:
                raise CodeKnowledgeError("code_source_file_size_or_type")
            raw = source.content(remote_file, revision)
            budget["bytes"] += len(raw)
            if budget["bytes"] > 512 * 1024**2:
                raise CodeKnowledgeError("code_source_total_limit")
            try:
                text, _ = _decode(raw)
            except CodeKnowledgeError as exc:
                if exc.code not in {"code_source_encoding_unknown", "code_source_binary"}:
                    raise
                excluded.append({"path": canonical, "reason": exc.code})
                continue
            if SENSITIVE_CONTENT.search(text):
                excluded.append({"path": canonical, "reason": "sensitive_content"})
                continue
            target = root / canonical
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("xb") as stream:
                    stream.write(raw)
            except FileExistsError:
                raise CodeKnowledgeError("code_svn_external_path_collision") from None


def compare_baseline(local: dict[str, Any], svn: dict[str, Any]) -> dict[str, Any]:
    """Proof covers the declared admission scope only; never rewrites local identity."""

    def admitted(manifest: dict[str, Any]) -> dict[str, tuple[str, str]]:
        return {
            item["path"]: (item["raw_hash"], item["representation_hash"])
            for item in manifest["files"]
        }

    left, right = admitted(local), admitted(svn)
    differences = sorted(
        path for path in left.keys() | right.keys() if left.get(path) != right.get(path)
    )
    exclusions_match = sorted(local["excluded"], key=lambda item: item["path"]) == sorted(
        svn["excluded"], key=lambda item: item["path"]
    )
    complete = bool(local["scan_complete"] and svn["scan_complete"])
    verified = complete and not differences and exclusions_match
    return {
        "state": "VERIFIED" if verified else "UNMAPPED",
        "scope": "admitted_source_manifest",
        "local_manifest_hash": digest(local),
        "svn_manifest_hash": digest(svn),
        "different_paths": differences[:100],
        "difference_count": len(differences),
        "exclusions_match": exclusions_match,
        "complete": complete,
    }
