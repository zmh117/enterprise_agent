"""Inspect/update one already-owned SVN working copy. The caller holds its DB claim."""

from pathlib import Path
import shutil
from typing import Any
from urllib.parse import unquote

from app.modules.knowledge.domain.code_answers import code_path, path_in_scope, svn_revision
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_identity import CheckoutIdentity
from app.modules.knowledge.infrastructure.code_svn import (
    BULK_METADATA_TIMEOUT,
    SvnCodeSource,
    xml_document,
)


def require_checkout_space(root: Path, required: int = 512 * 1024**2) -> None:
    if shutil.disk_usage(root).free < required:
        raise CodeKnowledgeError("CODE_CHECKOUT_DISK_LIMIT")


def preflight_checkout_space(
    source: SvnCodeSource, root: Path, paths: list[str], revision: int
) -> None:
    total, files = 0, 0
    for path in paths:
        for item in source.inventory(path, revision):
            if item["kind"] == "file":
                total += item["size_bytes"]
                files += 1
        if total > 20 * 1024**3 or files > 100000:
            raise CodeKnowledgeError("CODE_CHECKOUT_DISK_LIMIT")
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
    ):
        if (
            not directory.is_absolute()
            or directory.resolve(strict=True) != directory
            or not directory.is_dir()
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
        self.source, self.directory = source, directory
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
        target = str(self.directory) + "@"
        status = xml_document(
            self.source._run(
                "status",
                ["--xml", "--verbose", "--no-ignore", "--ignore-externals", target],
                timeout=BULK_METADATA_TIMEOUT,
            )
        )
        for node in status.findall("./target/entry/wc-status"):
            self._check_cancelled()
            if (
                node.get("item") != "normal"
                or node.get("props") not in {"none", "normal"}
                or node.get("switched") == "true"
                or node.get("tree-conflicted") == "true"
                or node.get("file-external") == "true"
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_DIRTY")
        info = xml_document(
            self.source._run(
                "info", ["--xml", "--depth", "infinity", target], timeout=BULK_METADATA_TIMEOUT
            )
        )
        if status.tag != "status" or info.tag != "info":
            raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID")
        rows = info.findall("entry")
        if not rows or len(rows) > 100000:
            raise CodeKnowledgeError("CODE_CHECKOUT_INVENTORY_LIMIT")
        revisions: set[int] = set()
        selected = set()
        file_count, total_bytes = 0, 0
        for node in rows:
            # On a large Desktop bind mount these filesystem checks can outlive
            # the lease even after svn info exits. Keep checking the same owner.
            self._check_cancelled()
            relative = self._entry(node)
            try:
                n = svn_revision(int(node.attrib["revision"]))
            except (ValueError, KeyError):
                raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID") from None
            revisions.add(n)
            if relative in self.paths:
                selected.add(relative)
            if node.get("kind") == "file":
                if not path_in_scope(relative, self.paths):
                    raise CodeKnowledgeError("CODE_CHECKOUT_SCOPE_CHANGED")
                file_count += 1
                total_bytes += (self.directory / relative).stat().st_size
        if len(revisions) != 1:
            raise CodeKnowledgeError("CODE_CHECKOUT_MIXED")
        operative = revisions.pop()
        if selected != set(self.paths) or (
            revision is not None and operative != svn_revision(revision)
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_VERSION_MISMATCH")
        if total_bytes > 20 * 1024**3:
            raise CodeKnowledgeError("CODE_CHECKOUT_DISK_LIMIT")
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

    def _entry(self, node: Any) -> str:
        path = Path(node.get("path", ""))
        if not path.is_absolute():
            raise CodeKnowledgeError("CODE_CHECKOUT_INFO_INVALID")
        try:
            relative = path.relative_to(self.directory).as_posix()
        except ValueError:
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID") from None
        relative = "" if relative == "." else code_path(relative)
        if path.resolve(strict=True) != path or path.is_symlink():
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
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
                "--ignore-externals",
                "--accept",
                "postpone",
                "-r",
                str(revision),
                str(self.directory) + "@",
            ],
            timeout=timeout,
            limit=8 * 1024 * 1024,
            cancelled=self._cancelled_with_space_check,
        )
        return self.inspect(revision)

    def _cancelled_with_space_check(self) -> bool:
        require_checkout_space(self.directory)
        return self.source.cancelled()
