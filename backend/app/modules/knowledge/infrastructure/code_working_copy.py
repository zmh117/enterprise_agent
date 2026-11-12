"""Inspect/update one already-owned SVN working copy. The caller holds its DB claim."""

from pathlib import Path
from collections.abc import Callable
import shutil
from typing import Any
from urllib.parse import unquote

from app.modules.knowledge.domain.code_answers import code_path, path_in_scope, svn_revision
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_identity import CheckoutIdentity
from app.modules.knowledge.infrastructure.code_svn import (
    SvnCodeSource,
    xml_document,
)
from app.modules.knowledge.infrastructure.code_svn_stream import MAX_METADATA_ENTRIES


def require_checkout_space(root: Path, required: int = 512 * 1024**2) -> None:
    if shutil.disk_usage(root).free < required:
        raise CodeKnowledgeError("CODE_CHECKOUT_DISK_LIMIT")


def preflight_checkout_space(
    source: SvnCodeSource, root: Path, paths: list[str], revision: int
) -> None:
    total, entries = 0, 0

    def consume(item: dict[str, Any]) -> None:
        nonlocal total, entries
        entries += 1
        if item["kind"] == "file":
            total += item["size_bytes"]
        if total > 20 * 1024**3 or entries > MAX_METADATA_ENTRIES:
            raise CodeKnowledgeError("CODE_CHECKOUT_DISK_LIMIT")

    for path in paths:
        source.walk_inventory(path, revision, consume)
    # Working files, pristine storage and transient update data all consume space.
    require_checkout_space(root, 3 * total + 512 * 1024**2)


class SvnWorkingCopy:
    def __init__(
        self,
        source: SvnCodeSource,
        directory: Path,
        selected_paths: list[str],
        *,
        physical_key: str,
        stage: Callable[[str], None] = lambda value: None,
    ):
        if (
            not directory.is_absolute()
            or directory.resolve(strict=True) != directory
            or not directory.is_dir()
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
        self.source, self.directory = source, directory
        self.stage = stage
        self.paths = [code_path(p, root=True) for p in selected_paths]
        if not self.paths:
            raise CodeKnowledgeError("CODE_SCOPE_INVALID")
        self.physical_key = physical_key
        self.identity = CheckoutIdentity(directory, physical_key)
        self._identity()

    def _identity(self) -> None:
        self.identity.check()

    def _check_cancelled(self) -> None:
        if self.source.cancelled():
            raise CodeKnowledgeError("code_collection_interrupted")

    def inspect(self, revision: int | None = None) -> dict[str, Any]:
        self._check_cancelled()
        self._identity()
        self.stage("verify_status")
        self._status()
        self.stage("verify_info")
        operative, rows, file_count, total_bytes = self._info(revision)
        self.stage("verify_inventory")
        self._complete(operative, rows)
        self._identity()
        self._check_cancelled()
        return dict(
            repository_uuid=self.source.expected_uuid,
            branch_path=self.source.branch_path,
            operative_revision=operative,
            mixed=False,
            modified=False,
            switched=False,
            selected_paths=self.paths,
            file_count=file_count,
            bytes=total_bytes,
        )

    def _status(self) -> None:
        target = str(self.directory) + "@"

        def consume(entry: Any) -> None:
            self._check_cancelled()
            node = entry.find("wc-status")
            if (
                node is None
                or node.get("item") != "normal"
                or node.get("props") not in {"none", "normal"}
                or node.get("wc-locked") == "true"
                or node.get("switched") == "true"
                or node.get("tree-conflicted") == "true"
                or node.get("file-external") == "true"
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_DIRTY")

        self.source.records(
            "status",
            ["--xml", "--verbose", "--no-ignore", "--ignore-externals", target],
            ("status", "target", "entry"),
            consume,
        )

    def _info(self, revision: int | None) -> tuple[int, dict[str, str], int, int]:
        rows: dict[str, str] = {}
        revisions: set[int] = set()
        file_count, total_bytes = 0, 0

        def consume(node: Any) -> None:
            nonlocal file_count, total_bytes
            self._check_cancelled()
            relative = self._entry(node)
            kind = node.get("kind")
            if relative in rows or kind not in {"file", "dir"}:
                raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID")
            rows[relative] = kind
            in_scope = path_in_scope(relative, self.paths)
            if not in_scope and not any(
                p.startswith(relative + "/") or not relative for p in self.paths
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_SCOPE_CHANGED")
            if kind == "dir" and in_scope and node.findtext("wc-info/depth") != "infinity":
                raise CodeKnowledgeError("CODE_CHECKOUT_INCOMPLETE")
            try:
                n = svn_revision(int(node.attrib["revision"]))
            except (ValueError, KeyError):
                raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID") from None
            revisions.add(n)
            if len(revisions) > 1:
                raise CodeKnowledgeError("CODE_CHECKOUT_MIXED")
            if kind == "file":
                if not in_scope:
                    raise CodeKnowledgeError("CODE_CHECKOUT_SCOPE_CHANGED")
                path = self.directory / relative
                if not path.is_file():
                    raise CodeKnowledgeError("CODE_CHECKOUT_INCOMPLETE")
                file_count += 1
                total_bytes += path.stat().st_size
                if total_bytes > 20 * 1024**3:
                    raise CodeKnowledgeError("CODE_CHECKOUT_DISK_LIMIT")

        self.source.records(
            "info",
            ["--xml", "--depth", "infinity", str(self.directory) + "@"],
            ("info", "entry"),
            consume,
        )
        if not rows or not revisions:
            raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID")
        operative = revisions.pop()
        if not set(self.paths).issubset(rows) or (
            revision is not None and operative != svn_revision(revision)
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_VERSION_MISMATCH")
        return operative, rows, file_count, total_bytes

    def _complete(self, revision: int, rows: dict[str, str]) -> None:
        self.source.preflight(revision)
        remaining = {p for p in rows if path_in_scope(p, self.paths)}
        for path in self.paths:
            self._check_cancelled()
            node = xml_document(
                self.source._run(
                    "info", ["--xml", "-r", str(revision), self.source._target(revision, path)]
                )
            ).find("entry")
            if node is None or node.get("kind") != rows[path]:
                raise CodeKnowledgeError("CODE_CHECKOUT_INCOMPLETE")
            remaining.remove(path)
            if rows[path] == "file":
                continue
            if self.source.external_declarations(revision, path=path)["declarations"]:
                raise CodeKnowledgeError("CODE_CHECKOUT_EXTERNALS_UNSUPPORTED")

            def consume(item: dict[str, Any]) -> None:
                relative = path + "/" + item["path"] if path else item["path"]
                if relative not in remaining or rows[relative] != item["kind"]:
                    raise CodeKnowledgeError("CODE_CHECKOUT_INCOMPLETE")
                remaining.remove(relative)

            self.source.walk_inventory(path, revision, consume)
        if remaining:
            raise CodeKnowledgeError("CODE_CHECKOUT_INCOMPLETE")

    def _entry(self, node: Any) -> str:
        path = Path(node.get("path", ""))
        if not path.is_absolute():
            raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID")
        try:
            relative = path.relative_to(self.directory).as_posix()
        except ValueError:
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID") from None
        relative = "" if relative == "." else code_path(relative)
        try:
            if path.resolve(strict=True) != path or path.is_symlink():
                raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
        except FileNotFoundError:
            raise CodeKnowledgeError("CODE_CHECKOUT_INCOMPLETE") from None
        expected = "^" + (
            self.source.branch_path + "/" + relative if relative else self.source.branch_path or "/"
        )
        if (
            node.findtext("repository/uuid") != self.source.expected_uuid
            or unquote(node.findtext("relative-url") or "") != expected
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_SOURCE_MISMATCH")
        return relative

    def update(self, revision: int, *, timeout: float) -> dict[str, Any]:
        """No implicit HEAD, revert, depth change, externals or model-supplied flags."""
        revision = svn_revision(revision)
        if not 0 < timeout <= 1800:
            raise CodeKnowledgeError("CODE_OPERATION_DEADLINE_INVALID")
        before = self.inspect()
        self.source.preflight(revision)
        if before["operative_revision"] == revision:
            return before
        for path in self.paths:
            # A selected file can be replaced by a directory at the target revision.
            # Inspect the target kind, not the current local working-copy kind.
            node = xml_document(
                self.source._run(
                    "info", ["--xml", "-r", str(revision), self.source._target(revision, path)]
                )
            ).find("entry")
            if (
                node is None
                or node.get("kind") not in {"dir", "file"}
                or node.findtext("repository/uuid") != self.source.expected_uuid
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID")
            if (
                node.get("kind") == "dir"
                and self.source.external_declarations(revision, path=path)["declarations"]
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_EXTERNALS_UNSUPPORTED")
        preflight_checkout_space(self.source, self.directory, self.paths, revision)
        self._identity()
        self.source.execute(
            "update",
            [
                "--quiet",
                "--ignore-externals",
                "--accept",
                "postpone",
                "-r",
                str(revision),
                str(self.directory) + "@",
            ],
            timeout=timeout,
            limit=None,
            cancelled=self._cancelled_with_space_check,
        )
        return self.inspect(revision)

    def _cancelled_with_space_check(self) -> bool:
        require_checkout_space(self.directory)
        return self.source.cancelled()
