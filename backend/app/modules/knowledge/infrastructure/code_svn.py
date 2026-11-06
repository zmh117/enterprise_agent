"""Pinned, read-only SVN collector. No model-provided commands, URLs or credentials."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import selectors
import time
from typing import Any
from collections.abc import Callable
from urllib.parse import urlsplit, quote, unquote, urljoin
import shlex
import xml.etree.ElementTree as ET

from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    COMPONENTS,
    MAX_PACKAGE_BYTES,
)
from app.modules.knowledge.domain.code_package import sha256
from app.modules.knowledge.infrastructure.code_source import relative_path

MAX_XML_BYTES = 8 * 1024 * 1024


def xml_document(data: bytes) -> ET.Element:
    if len(data) > MAX_XML_BYTES or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise CodeKnowledgeError("code_svn_response_invalid")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise CodeKnowledgeError("code_svn_response_invalid") from None


def parse_log(data: bytes, *, lower: int, upper: int, branch_path: str) -> list[dict[str, Any]]:
    root = xml_document(data)
    if root.tag != "log":
        raise CodeKnowledgeError("code_svn_log_invalid")
    result = []
    for entry in root.findall("logentry"):
        try:
            revision = int(entry.attrib["revision"])
            if not lower < revision <= upper:
                raise ValueError
            paths = []
            for item in entry.findall("./paths/path"):
                path = item.text or ""
                if not (path == branch_path or path.startswith(branch_path.rstrip("/") + "/")):
                    continue
                action = item.attrib.get("action")
                if action not in {"A", "M", "D", "R"}:
                    raise ValueError
                paths.append(
                    dict(
                        path=path,
                        action=action,
                        kind=item.attrib.get("kind", "unknown"),
                        text_modified=item.attrib.get("text-mods", "unknown"),
                        properties_modified=item.attrib.get("prop-mods", "unknown"),
                        copy_from_path=item.attrib.get("copyfrom-path"),
                        copy_from_revision=int(item.attrib["copyfrom-rev"])
                        if "copyfrom-rev" in item.attrib
                        else None,
                    )
                )
            if paths:
                result.append({"revision": revision, "paths": paths})
        except (KeyError, ValueError):
            raise CodeKnowledgeError("code_svn_log_invalid") from None
    if len({item["revision"] for item in result}) != len(result):
        raise CodeKnowledgeError("code_svn_log_duplicate")
    return sorted(result, key=lambda item: item["revision"])


class SvnCodeSource:
    def __init__(
        self,
        *,
        branch_url: str,
        expected_uuid: str,
        branch_path: str,
        config_directory: Path,
        executable: str = "svn",
        allow_local_test: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        parsed = urlsplit(branch_url)
        schemes = {"https"} | ({"file"} if allow_local_test else set())
        if (
            parsed.scheme not in schemes
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "@" in parsed.path
            or not expected_uuid
            or not branch_path.startswith("/")
        ):
            raise CodeKnowledgeError("code_svn_binding_invalid")
        relative_path(branch_path.lstrip("/"))
        if not config_directory.is_absolute() or config_directory.is_symlink():
            raise CodeKnowledgeError("code_svn_auth_reference_invalid")
        self.branch_url, self.expected_uuid, self.branch_path = (
            branch_url.rstrip("/"),
            expected_uuid,
            branch_path.rstrip("/"),
        )
        self.config_directory, self.executable = config_directory, executable
        self.cancelled = cancelled or (lambda: False)

    def _run(self, operation: str, args: list[str]) -> bytes:
        if self.cancelled():
            raise CodeKnowledgeError("code_collection_interrupted")
        if operation not in {"info", "log", "cat", "diff", "propget", "list"}:
            raise CodeKnowledgeError("code_svn_operation_denied")
        command = [
            self.executable,
            operation,
            "--non-interactive",
            "--no-auth-cache",
            "--config-dir",
            str(self.config_directory),
            *args,
        ]
        try:
            with subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ) as process:
                try:
                    return _bounded_output(
                        process,
                        timeout=60,
                        limit=MAX_PACKAGE_BYTES if operation == "cat" else MAX_XML_BYTES,
                        cancelled=self.cancelled,
                    )
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
        except (OSError, subprocess.TimeoutExpired):
            raise CodeKnowledgeError("code_svn_unavailable") from None

    def preflight(self, revision: int) -> dict[str, Any]:
        target = self._target(revision)
        root = xml_document(self._run("info", ["--xml", "-r", str(revision), target]))
        entry = root.find("entry")
        if entry is None or entry.findtext("repository/uuid") != self.expected_uuid:
            raise CodeKnowledgeError("code_svn_repository_mismatch")
        if unquote(entry.findtext("relative-url") or "") != "^" + self.branch_path:
            raise CodeKnowledgeError("code_svn_branch_mismatch")
        if entry.get("revision") != str(revision):
            raise CodeKnowledgeError("code_svn_revision_mismatch")
        return {
            "repository_uuid": self.expected_uuid,
            "branch_path": self.branch_path,
            "revision": revision,
        }

    def head(self) -> int:
        root = xml_document(self._run("info", ["--xml", self.branch_url + "@HEAD"]))
        entry = root.find("entry")
        if (
            entry is None
            or entry.findtext("repository/uuid") != self.expected_uuid
            or unquote(entry.findtext("relative-url") or "") != "^" + self.branch_path
        ):
            raise CodeKnowledgeError("code_svn_repository_mismatch")
        try:
            revision = int(entry.attrib["revision"])
        except (KeyError, ValueError):
            raise CodeKnowledgeError("code_svn_revision_mismatch") from None
        self.preflight(revision)
        return revision

    def preflight_components(self, revision: int, mapping: dict[str, str]) -> None:
        if set(mapping) != set(COMPONENTS) or len(set(mapping.values())) != 3:
            raise CodeKnowledgeError("code_svn_components_invalid")
        self.preflight(revision)
        for path in mapping.values():
            relative_path(path)
            root = xml_document(
                self._run("info", ["--xml", "-r", str(revision), self._target(revision, path)])
            )
            entry = root.find("entry")
            if (
                entry is None
                or entry.get("kind") != "dir"
                or entry.findtext("repository/uuid") != self.expected_uuid
                or unquote(entry.findtext("relative-url") or "")
                != "^" + self.branch_path + "/" + path
                or entry.get("revision") != str(revision)
            ):
                raise CodeKnowledgeError("code_svn_components_invalid")

    def _target(self, revision: int, path: str = "") -> str:
        if type(revision) is not int or revision < 0:
            raise CodeKnowledgeError("code_svn_revision_invalid")
        suffix = "/" + quote(relative_path(path), safe="/") if path else ""
        return f"{self.branch_url}{suffix}@{revision}"

    def commits(
        self, *, after: int, target: int, through: int | None = None
    ) -> list[dict[str, Any]]:
        through = target if through is None else through
        if after < 0 or not after <= through <= target:
            raise CodeKnowledgeError("code_svn_range_invalid")
        self.preflight(target)
        commits = []
        # Bound every request; retain each relevant revision, even if endpoint files are equal.
        for lower in range(after, through, 100):
            upper = min(lower + 100, through)
            data = self._run(
                "log",
                [
                    "--xml",
                    "--verbose",
                    "--with-no-revprops",
                    "-r",
                    f"{lower + 1}:{upper}",
                    self._target(target),
                ],
            )
            commits.extend(parse_log(data, lower=lower, upper=upper, branch_path=self.branch_path))
        return commits

    def content(self, path: str, revision: int) -> bytes:
        return self._run("cat", ["-r", str(revision), self._target(revision, path)])

    def inventory(self, path: str, revision: int) -> list[dict[str, Any]]:
        """List a pinned subtree; directory entries and special files remain explicit."""
        root = xml_document(
            self._run(
                "list", ["--xml", "--recursive", "-r", str(revision), self._target(revision, path)]
            )
        )
        result: list[dict[str, Any]] = []
        for entry in root.findall("./list/entry"):
            name = relative_path(entry.findtext("name") or "")
            kind = entry.get("kind")
            if kind not in {"file", "dir"} or len(result) >= 30_000:
                raise CodeKnowledgeError("code_source_inventory_limit")
            try:
                size = int(entry.findtext("size") or "0")
            except ValueError:
                raise CodeKnowledgeError("code_svn_response_invalid") from None
            if size < 0:
                raise CodeKnowledgeError("code_svn_response_invalid")
            result.append({"path": name, "kind": kind, "size_bytes": size})
        if len({item["path"] for item in result}) != len(result):
            raise CodeKnowledgeError("code_svn_inventory_duplicate")
        return sorted(result, key=lambda item: item["path"])

    def special_paths(self, revision: int) -> set[str]:
        root = xml_document(
            self._run(
                "propget",
                [
                    "--xml",
                    "--recursive",
                    "-r",
                    str(revision),
                    "svn:special",
                    self._target(revision),
                ],
            )
        )
        paths = set()
        for target in root.findall("target"):
            url = target.get("path", "")
            if not url.startswith(self.branch_url + "/"):
                raise CodeKnowledgeError("code_svn_response_invalid")
            paths.add(relative_path(unquote(url[len(self.branch_url) + 1 :])))
        return paths

    def changed_paths(self, revision: int) -> list[dict[str, str]]:
        data = self._run(
            "diff", ["--summarize", "--xml", "-c", str(revision), self._target(revision)]
        )
        return [
            {
                "path": item.text or "",
                "action": item.get("item", "unknown"),
                "properties": item.get("props", "unknown"),
                "kind": item.get("kind", "unknown"),
            }
            for item in xml_document(data).findall("./paths/path")
        ]

    def external_declarations(
        self,
        revision: int,
        *,
        approved: dict[str, "SvnCodeSource"] | None = None,
        capture_floating: bool = False,
    ) -> dict[str, Any]:
        data = self._run(
            "propget",
            ["--xml", "--recursive", "-r", str(revision), "svn:externals", self._target(revision)],
        )
        document = xml_document(data)
        if document.tag != "properties":
            raise CodeKnowledgeError("code_svn_response_invalid")
        declarations: list[dict[str, Any]] = []
        for target in document.findall("target"):
            for prop in target.findall("property"):
                if prop.get("name") == "svn:externals" and (prop.text or "").strip():
                    for line in (prop.text or "").splitlines():
                        if not line.strip() or line.lstrip().startswith("#"):
                            continue
                        if len(declarations) >= 100:
                            raise CodeKnowledgeError("code_svn_externals_limit")
                        declarations.append(
                            self._external(
                                line,
                                target.get("path", ""),
                                approved or {},
                                capture_floating=capture_floating,
                            )
                        )
        return {
            "declarations": declarations,
            "complete": all(item["state"] == "PINNED" for item in declarations),
        }

    def _external(
        self,
        line: str,
        target: str,
        approved: dict[str, "SvnCodeSource"],
        *,
        capture_floating: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "property_hash": sha256(line.encode()),
            "state": "UNRESOLVED",
            "critical": True,
        }
        try:
            local, url, revision = parse_external(line)
            if target != self.branch_url and not target.startswith(self.branch_url + "/"):
                return result
            directory = unquote(target[len(self.branch_url) :]).strip("/")
            path = relative_path(directory + "/" + local if directory else local)
            result["path"] = path
            dependency = approved.get(path)
            if dependency is None:
                return result
            if url.startswith("^/"):
                if not self.branch_url.endswith(self.branch_path):
                    return result
                url = self.branch_url[: -len(self.branch_path)] + url[1:]
            else:
                url = urljoin(target.rstrip("/") + "/", url)
            # A repository property is not network authorization. Only this exact
            # deployment-approved target may be contacted, with its own UUID/auth.
            if url.rstrip("/") != dependency.branch_url:
                return result
            if revision is None and not capture_floating:
                return {**result, "reason": "historical_floating_revision_unknown"}
            pinned = dependency.head() if revision is None else revision
            dependency.preflight(pinned)
            return {
                **result,
                "state": "PINNED",
                "critical": False,
                "path": path,
                "repository_uuid": dependency.expected_uuid,
                "branch_path": dependency.branch_path,
                "revision": pinned,
                "floating": revision is None,
            }
        except (CodeKnowledgeError, ValueError):
            return result


def parse_external(line: str) -> tuple[str, str, int | None]:
    """Common modern/legacy declarations; ambiguous peg/date forms stay unknown."""
    parts = shlex.split(line, comments=True)
    revision = None
    tokens = []
    position = 0
    while position < len(parts):
        token = parts[position]
        if token == "-r" or token.startswith("-r"):
            if revision is not None:
                raise CodeKnowledgeError("code_svn_external_invalid")
            if token == "-r":
                position += 1
                if position >= len(parts):
                    raise CodeKnowledgeError("code_svn_external_invalid")
                token = parts[position]
            else:
                token = token[2:]
            revision = int(token)
            if revision < 0:
                raise CodeKnowledgeError("code_svn_external_invalid")
        else:
            tokens.append(token)
        position += 1
    if len(tokens) != 2:
        raise CodeKnowledgeError("code_svn_external_invalid")

    def is_url(value: str) -> bool:
        return value.startswith(("https://", "file://", "^/", "../", "//", "/"))

    url, local = tokens if is_url(tokens[0]) else (tokens[1], tokens[0])
    if not is_url(url) or is_url(local):
        raise CodeKnowledgeError("code_svn_external_invalid")
    if "@" in url:
        url, peg = url.rsplit("@", 1)
        peg_revision = int(peg)
        if revision is not None and revision != peg_revision:
            raise CodeKnowledgeError("code_svn_external_peg_unresolved")
        revision = peg_revision
    relative_path(local)
    return local, url, revision


def _bounded_output(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
    limit: int,
    cancelled: Callable[[], bool] = lambda: False,
) -> bytes:
    """Bound memory while the child is running; never retain or log SVN stderr."""
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            if cancelled():
                raise CodeKnowledgeError("code_collection_interrupted")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodeKnowledgeError("code_svn_unavailable")
            if not selector.select(min(1, remaining)):
                continue
            block = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(output)))
            if not block:
                break
            output.extend(block)
            if len(output) > limit:
                raise CodeKnowledgeError("code_svn_response_too_large")
    if process.wait(timeout=max(0.001, deadline - time.monotonic())):
        raise CodeKnowledgeError("code_svn_request_failed")
    return bytes(output)
