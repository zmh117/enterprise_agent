"""Bounded read-only SVN commands. No model-provided commands, URLs or credentials."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import selectors
import time
import re
import uuid
from typing import Any
from collections.abc import Callable
from urllib.parse import urlsplit, quote, unquote, urljoin
import shlex
import xml.etree.ElementTree as ET

from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    MAX_SOURCE_BYTES,
)
from app.modules.knowledge.domain.code_json import sha256
from app.modules.knowledge.infrastructure.code_source import relative_path
from app.modules.knowledge.infrastructure.code_executor_lock import inherited_execution_fds

MAX_XML_BYTES = 8 * 1024 * 1024
BULK_METADATA_TIMEOUT = 300
SVN_OPERATIONS = frozenset(
    {"info", "log", "cat", "diff", "propget", "list", "blame", "status", "checkout", "update"}
)


class SvnCommandFailure(CodeKnowledgeError):
    """A failed process with bounded, data-only diagnostics; no argv or stderr."""

    def __init__(
        self, code: str, *, operation: str, returncode: int, error_codes: set[bytes]
    ) -> None:
        super().__init__(code)
        self.diagnostic = {
            "operation": operation if operation in SVN_OPERATIONS else "unknown",
            "exit_code": returncode if -255 <= returncode <= 255 else None,
            "svn_error_codes": sorted(
                code.decode("ascii") for code in error_codes if re.fullmatch(rb"E[0-9]{6}", code)
            )[:8],
        }


def xml_document(data: bytes) -> ET.Element:
    if len(data) > MAX_XML_BYTES or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise CodeKnowledgeError("code_svn_response_invalid")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise CodeKnowledgeError("code_svn_response_invalid") from None


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
        credentials: tuple[str, str] | None = None,
        discover: bool = False,
    ) -> None:
        parsed = urlsplit(branch_url)
        schemes = {"http", "https", "svn"} | ({"file"} if allow_local_test else set())
        if (
            parsed.scheme not in schemes
            or (parsed.scheme != "file" and not parsed.hostname)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "@" in parsed.path
            or (not expected_uuid and not discover)
            or not branch_path.startswith("/")
        ):
            raise CodeKnowledgeError("code_svn_binding_invalid")
        if branch_path != "/":
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
        self._credentials = credentials

    def discover(self) -> None:
        entry = xml_document(self._run("info", ["--xml", self.branch_url + "@HEAD"])).find("entry")
        try:
            if entry is None:
                raise ValueError
            identity = str(uuid.UUID(entry.findtext("repository/uuid") or ""))
            relative = unquote(entry.findtext("relative-url") or "")
            if not relative.startswith("^/"):
                raise ValueError
            branch = relative[1:].rstrip("/")
            if branch:
                relative_path(branch.lstrip("/"))
            self.expected_uuid, self.branch_path = identity, branch
        except ValueError:
            raise CodeKnowledgeError("code_svn_repository_mismatch") from None

    def _run(self, operation: str, args: list[str], *, timeout: float = 60) -> bytes:
        if self.cancelled():
            raise CodeKnowledgeError("code_collection_interrupted")
        if operation not in {"info", "log", "cat", "diff", "propget", "list", "blame", "status"}:
            raise CodeKnowledgeError("code_svn_operation_denied")
        return self.execute(
            operation,
            args,
            timeout=timeout,
            limit=MAX_SOURCE_BYTES if operation == "cat" else MAX_XML_BYTES,
        )

    def execute(
        self,
        operation: str,
        args: list[str],
        *,
        timeout: float,
        limit: int,
        cancelled: Callable[[], bool] | None = None,
    ) -> bytes:
        if operation not in SVN_OPERATIONS:
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
        if self._credentials:
            command += ["--username", self._credentials[0], "--password-from-stdin"]
        timeout_error = f"CODE_SVN_{operation.upper()}_TIMEOUT"
        process = None
        try:
            with subprocess.Popen(
                command,
                stdin=subprocess.PIPE if self._credentials else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=inherited_execution_fds(),
                # The executor's primary group shares source with Runtime readers.
                # Never change the multithreaded worker's private credential umask.
                umask=0o027,
            ) as process:
                try:
                    if self._credentials and process.stdin is not None:
                        try:
                            process.stdin.write((self._credentials[1] + "\n").encode())
                            process.stdin.close()
                        except BrokenPipeError:
                            pass
                    return _bounded_output(
                        process,
                        timeout=timeout,
                        limit=limit,
                        cancelled=cancelled or self.cancelled,
                        timeout_error=timeout_error,
                        operation=operation,
                    )
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
        except subprocess.TimeoutExpired:
            raise CodeKnowledgeError(timeout_error) from None
        except OSError as exc:
            if process is not None:
                error = "CODE_SVN_LOCAL_IO_FAILED"
            elif isinstance(exc, FileNotFoundError):
                error = "CODE_SVN_EXECUTABLE_NOT_FOUND"
            elif isinstance(exc, PermissionError):
                error = "CODE_SVN_EXECUTION_DENIED"
            else:
                error = "CODE_SVN_START_FAILED"
            raise CodeKnowledgeError(error) from None

    def preflight(self, revision: int) -> dict[str, Any]:
        target = self._target(revision)
        root = xml_document(self._run("info", ["--xml", "-r", str(revision), target]))
        entry = root.find("entry")
        if entry is None or entry.findtext("repository/uuid") != self.expected_uuid:
            raise CodeKnowledgeError("code_svn_repository_mismatch")
        if unquote(entry.findtext("relative-url") or "") != "^" + (self.branch_path or "/"):
            raise CodeKnowledgeError("code_svn_branch_mismatch")
        if entry.get("revision") != str(revision):
            raise CodeKnowledgeError("code_svn_revision_mismatch")
        return {
            "repository_uuid": self.expected_uuid,
            "branch_path": self.branch_path,
            "revision": revision,
            "repository_root_url": entry.findtext("repository/root"),
        }

    def head(self) -> int:
        root = xml_document(self._run("info", ["--xml", self.branch_url + "@HEAD"]))
        entry = root.find("entry")
        if (
            entry is None
            or entry.findtext("repository/uuid") != self.expected_uuid
            or unquote(entry.findtext("relative-url") or "") != "^" + (self.branch_path or "/")
        ):
            raise CodeKnowledgeError("code_svn_repository_mismatch")
        try:
            revision = int(entry.attrib["revision"])
        except (KeyError, ValueError):
            raise CodeKnowledgeError("code_svn_revision_mismatch") from None
        self.preflight(revision)
        return revision

    def _target(self, revision: int, path: str = "") -> str:
        if type(revision) is not int or revision < 0:
            raise CodeKnowledgeError("code_svn_revision_invalid")
        suffix = "/" + quote(relative_path(path), safe="/") if path else ""
        return f"{self.branch_url}{suffix}@{revision}"

    def content(self, path: str, revision: int) -> bytes:
        return self._run("cat", ["-r", str(revision), self._target(revision, path)])

    def inventory(self, path: str, revision: int) -> list[dict[str, Any]]:
        """List a pinned subtree; directory entries and special files remain explicit."""
        return self._list_entries(path, revision, recursive=True)

    def directory_entries(self, path: str, revision: int) -> list[dict[str, Any]]:
        """Preview one directory without fetching any descendant inventory."""
        if path:
            relative_path(path)
        node = xml_document(
            self._run("info", ["--xml", "-r", str(revision), self._target(revision, path)])
        ).find("entry")
        if node is None or node.get("kind") != "dir":
            raise CodeKnowledgeError("CODE_BROWSE_DIRECTORY_REQUIRED")
        return self._list_entries(path, revision, recursive=False)

    def _list_entries(self, path: str, revision: int, *, recursive: bool) -> list[dict[str, Any]]:
        root = xml_document(
            self._run(
                "list",
                [
                    "--xml",
                    *(["--recursive"] if recursive else ["--depth", "immediates"]),
                    "-r",
                    str(revision),
                    self._target(revision, path),
                ],
                timeout=BULK_METADATA_TIMEOUT if recursive else 60,
            )
        )
        result: list[dict[str, Any]] = []
        for entry in root.findall("./list/entry"):
            name = relative_path(entry.findtext("name") or "")
            if not recursive and "/" in name:
                raise CodeKnowledgeError("code_svn_response_invalid")
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
        path: str = "",
        approved: dict[str, "SvnCodeSource"] | None = None,
        capture_floating: bool = False,
    ) -> dict[str, Any]:
        data = self._run(
            "propget",
            [
                "--xml",
                "--recursive",
                "-r",
                str(revision),
                "svn:externals",
                self._target(revision, path),
            ],
            timeout=BULK_METADATA_TIMEOUT,
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
        return value.startswith(
            ("http://", "https://", "svn://", "file://", "^/", "../", "//", "/")
        )

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
    timeout_error: str = "CODE_SVN_TIMEOUT",
    operation: str = "unknown",
) -> bytes:
    """Bound stdout; retain only fixed numeric SVN error codes from stderr."""
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    output = bytearray()
    error_codes: set[bytes] = set()
    error_tail, error_size = b"", 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ)
        while selector.get_map():
            if cancelled():
                raise CodeKnowledgeError("code_collection_interrupted")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodeKnowledgeError(timeout_error)
            for key, _ in selector.select(min(1, remaining)):
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                if key.fileobj is process.stderr:
                    error_size += len(block)
                    error_codes.update(re.findall(rb"E[0-9]{6}", error_tail + block))
                    error_tail = block[-7:]
                    if error_size > 65536:
                        raise CodeKnowledgeError("code_svn_response_too_large")
                else:
                    output.extend(block)
                    if len(output) > limit:
                        raise CodeKnowledgeError("code_svn_response_too_large")
    returncode = process.wait(timeout=max(0.001, deadline - time.monotonic()))
    if returncode:
        for codes, error in [
            ({b"E215004", b"E170001"}, "CODE_SVN_AUTH_FAILED"),
            ({b"E230001"}, "CODE_SVN_CERTIFICATE_INVALID"),
            ({b"E175013", b"E220004"}, "CODE_SVN_ACCESS_DENIED"),
            ({b"E170013", b"E175002", b"E670002"}, "CODE_SVN_CONNECTION_FAILED"),
        ]:
            if error_codes & codes:
                raise SvnCommandFailure(
                    error, operation=operation, returncode=returncode, error_codes=error_codes
                )
        raise SvnCommandFailure(
            "code_svn_request_failed",
            operation=operation,
            returncode=returncode,
            error_codes=error_codes,
        )
    return bytes(output)
