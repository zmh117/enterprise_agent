"""部署登记的 SVN 目录浏览与完整工作副本；不执行知识准入过滤。"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import urlsplit

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_source import _read_beneath, relative_path
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource, xml_document
from app.modules.knowledge.infrastructure.code_working_copy import (
    preflight_checkout_space,
    require_checkout_space,
)

FOLDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def _same_directory(path: Path, descriptor: int) -> bool:
    try:
        return os.path.samestat(os.fstat(descriptor), path.lstat())
    except OSError:
        return False


@contextmanager
def checkout_directory(destination: Path) -> Iterator[Path]:
    # mkdir is exclusive even for empty directories and dangling symlinks, and
    # works on Desktop bind mounts that reject renameat2(RENAME_NOREPLACE).
    # The existing DB writer owns this path in preparing state until the executor
    # finishes verification; filesystem visibility does not grant Runtime access.
    try:
        destination.mkdir(mode=0o750)
    except FileExistsError:
        raise CodeKnowledgeError("code_checkout_destination_exists") from None
    except OSError:
        raise CodeKnowledgeError("code_checkout_create_failed") from None
    descriptor = None
    completed = False
    try:
        descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        # The worker keeps umask 077 for credentials. Only this owned source
        # directory is group-readable; never change the process-wide umask.
        os.fchmod(descriptor, 0o750)
        yield destination
        if not _same_directory(destination, descriptor):
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
        completed = True
    except OSError:
        raise CodeKnowledgeError("CODE_SVN_LOCAL_IO_FAILED") from None
    finally:
        if descriptor is not None:
            if not completed and _same_directory(destination, descriptor):
                try:
                    shutil.rmtree(destination)
                except OSError:
                    # Keep the original failure; an uncleared directory remains
                    # invalid and can never be reused or overwritten implicitly.
                    pass
            os.close(descriptor)


def registry(path: Path) -> dict[str, dict[str, str]]:
    try:
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError
        data = json.loads(_read_beneath(path.parent, path.name, 64 * 1024))
        if not isinstance(data, dict) or not 1 <= len(data) <= 20:
            raise ValueError
        seen = set()
        for key, entry in data.items():
            if (
                not FOLDER.fullmatch(key)
                or set(entry)
                != {"public_url", "branch_url", "repository_uuid", "branch_path", "auth_ref"}
                or not all(isinstance(v, str) and v for v in entry.values())
            ):
                raise ValueError
            if not FOLDER.fullmatch(entry["auth_ref"]):
                raise ValueError
            if entry["branch_path"] != "/":
                relative_path(entry["branch_path"].lstrip("/"))
            for field in ("public_url", "branch_url"):
                url = urlsplit(entry[field])
                if (
                    url.scheme != "https"
                    or not url.hostname
                    or url.username
                    or url.password
                    or url.query
                    or url.fragment
                    or "@" in url.path
                ):
                    raise ValueError
            if entry["public_url"] in seen:
                raise ValueError
            seen.add(entry["public_url"])
        return data
    except (OSError, ValueError, TypeError, AttributeError):
        raise CodeKnowledgeError("code_checkout_registry_invalid") from None


def registered_url(path: Path, url: str) -> tuple[str, dict[str, str]]:
    if not isinstance(url, str):
        raise CodeKnowledgeError("code_checkout_url_unregistered")
    for key, entry in registry(path).items():
        if url.rstrip("/") == entry["public_url"].rstrip("/"):
            return key, entry
    raise CodeKnowledgeError("code_checkout_url_unregistered")


def selection(paths: Any, entries: list[str]) -> list[str]:
    if (
        not isinstance(paths, list)
        or not 1 <= len(paths) <= 100
        or not all(isinstance(p, str) for p in paths)
    ):
        raise CodeKnowledgeError("code_checkout_selection_invalid")
    if paths == [""]:
        return paths
    if len(set(paths)) != len(paths) or any(p not in entries for p in paths):
        raise CodeKnowledgeError("code_checkout_selection_invalid")
    for path in paths:
        relative_path(path)
        if any(path.startswith(parent + "/") for parent in paths if parent != path):
            raise CodeKnowledgeError("code_checkout_selection_overlaps")
    return sorted(paths)


class WorkingCopyClient:
    def __init__(
        self,
        entry: dict[str, str],
        auth_root: Path,
        cancelled: Callable[[], bool] = lambda: False,
        *,
        credentials: tuple[str, str] | None = None,
        config_directory: Path | None = None,
    ):
        self.entry, self.cancelled = dict(entry), cancelled
        config = config_directory or auth_root / entry["auth_ref"]
        if not config.is_dir() or config.resolve() != config:
            raise CodeKnowledgeError("code_svn_auth_reference_invalid")
        self.source = SvnCodeSource(
            branch_url=entry["branch_url"],
            expected_uuid=entry["repository_uuid"],
            branch_path=entry["branch_path"],
            config_directory=config,
            cancelled=cancelled,
            credentials=credentials,
            discover=bool(entry.get("resource_id") or entry.get("secret_ref"))
            and not entry["repository_uuid"],
        )
        if not entry["repository_uuid"]:
            self.source.discover()
            self.entry.update(
                repository_uuid=self.source.expected_uuid,
                branch_path=self.source.branch_path or "/",
            )

    def browse(self, revision: int | None, *, path: str = "") -> dict[str, Any]:
        revision = self.source.head() if revision is None else revision
        self.source.preflight(revision)
        entries = self.source.directory_entries(path, revision)
        if path:
            entries = [{**e, "path": path + "/" + e["path"]} for e in entries]
        directories = [e["path"] for e in entries if e["kind"] == "dir"]
        if len(directories) > 5000:
            raise CodeKnowledgeError("code_checkout_directory_limit")
        from app.modules.knowledge.infrastructure.code_svn_access import connection_fingerprint

        return {
            "revision": revision,
            "repository_uuid": self.entry["repository_uuid"],
            "directories": sorted(directories),
            "files": sorted(e["path"] for e in entries if e["kind"] == "file"),
            "registration_hash": connection_fingerprint(self.entry),
        }

    def _checkout_command(self, args: list[str], *, root: Path) -> None:
        def cancelled() -> bool:
            require_checkout_space(root)
            return self.cancelled()

        self.source.execute(
            args[0], args[1:], timeout=1800, limit=8 * 1024 * 1024, cancelled=cancelled
        )

    def checkout(
        self, *, root: Path, folder: str, job_id: str, revision: int, paths: list[str]
    ) -> dict[str, Any]:
        if (
            not FOLDER.fullmatch(folder)
            or not FOLDER.fullmatch(job_id)
            or root.resolve() != root
            or not root.is_dir()
        ):
            raise CodeKnowledgeError("code_checkout_destination_invalid")
        destination = root / folder
        if os.path.lexists(destination):
            raise CodeKnowledgeError("code_checkout_destination_exists")
        self.source.preflight(revision)
        kinds = {}
        for path in paths:
            node = xml_document(
                self.source._run(
                    "info", ["--xml", "-r", str(revision), self.source._target(revision, path)]
                )
            ).find("entry")
            if (
                node is None
                or node.get("kind") not in {"dir", "file"}
                or node.findtext("repository/uuid") != self.entry["repository_uuid"]
            ):
                raise CodeKnowledgeError("code_checkout_selection_invalid")
            kinds[path] = node.get("kind")
        for path, kind in kinds.items():
            if (
                kind == "dir"
                and self.source.external_declarations(revision, path=path)["declarations"]
            ):
                raise CodeKnowledgeError("code_checkout_externals_unsupported")
        preflight_checkout_space(self.source, root, paths, revision)
        target = self.source._target(revision)
        with checkout_directory(destination):
            self._checkout_command(
                [
                    "checkout",
                    "--depth",
                    "empty",
                    "--ignore-externals",
                    "-r",
                    str(revision),
                    target,
                    str(destination),
                ],
                root=root,
            )
            prepared = set()
            for path in paths:
                relative_path(path) if path else None
                parts = path.split("/") if path else []
                for i in range(1, len(parts)):
                    ancestor = "/".join(parts[:i])
                    if ancestor not in prepared:
                        self._checkout_command(
                            [
                                "update",
                                "--set-depth",
                                "empty",
                                "--ignore-externals",
                                "-r",
                                str(revision),
                                str(destination / ancestor) + "@",
                            ],
                            root=root,
                        )
                        prepared.add(ancestor)
                self._checkout_command(
                    [
                        "update",
                        *(["--set-depth", "infinity"] if kinds[path] == "dir" else []),
                        "--ignore-externals",
                        "-r",
                        str(revision),
                        str(destination / path) + "@",
                    ],
                    root=root,
                )
            if self.cancelled():
                raise CodeKnowledgeError("code_checkout_interrupted")
            for path in paths:
                node = xml_document(
                    self.source._run("info", ["--xml", str(destination / path) + "@"]).strip()
                ).find("entry")
                if (
                    node is None
                    or node.get("kind") != kinds[path]
                    or node.get("revision") != str(revision)
                    or node.findtext("repository/uuid") != self.entry["repository_uuid"]
                ):
                    raise CodeKnowledgeError("code_checkout_verification_failed")
            return {
                "revision": revision,
                "repository_uuid": self.entry["repository_uuid"],
                "paths": paths,
                "folder": folder,
                "container_directory": str(destination),
            }
