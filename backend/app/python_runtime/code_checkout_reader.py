"""Bounded host-only SVN working-copy metadata and pristine reads, without SVN CLI.

Runtime supports the installed SVN working-copy format 31. Unknown formats fail
closed. No full inventory, source copy or model-accessible .svn path is created.
"""

from contextlib import contextmanager
from collections.abc import Iterator
from hashlib import sha1, sha256
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any
from urllib.parse import quote

from app.modules.knowledge.domain.code_text import decode_source
from app.modules.knowledge.domain.code_answers import code_path, path_in_scope
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_source import (
    _read_beneath,
    SENSITIVE_CONTENT,
    SENSITIVE_NAME,
)

MAX_FILE = 15 * 1024 * 1024


def svn_properties(raw: bytes | None) -> dict[str, str]:  # noqa: C901
    """Parse the bounded property skel emitted by format-31 SVN, no expressions."""
    if raw is None:
        return {}
    if not isinstance(raw, bytes) or len(raw) > 65536:
        raise CodeKnowledgeError("CODE_CHECKOUT_METADATA_INVALID")
    position = 0

    def item(depth: int) -> Any:
        nonlocal position
        if depth > 1:
            raise ValueError
        while position < len(raw) and raw[position : position + 1].isspace():
            position += 1
        if position >= len(raw):
            raise ValueError
        if raw[position] == 40:
            position += 1
            result: list[Any] = []
            while position < len(raw):
                while position < len(raw) and raw[position : position + 1].isspace():
                    position += 1
                if position < len(raw) and raw[position] == 41:
                    position += 1
                    return result
                result.append(item(depth + 1))
                if len(result) > 256:
                    raise ValueError
            raise ValueError
        start = position
        while (
            position < len(raw)
            and not raw[position : position + 1].isspace()
            and raw[position] not in (40, 41)
        ):
            position += 1
        token = raw[start:position]
        if not token:
            raise ValueError
        if token.isdigit():
            length = int(token)
            if position >= len(raw) or raw[position] != 32 or position + 1 + length > len(raw):
                raise ValueError
            position += 1
            value = raw[position : position + length]
            position += length
            return value
        return token

    try:
        values = item(0)
        if not isinstance(values, list) or len(values) % 2 or raw[position:].strip():
            raise ValueError
        result = {
            values[i].decode("utf-8"): values[i + 1].decode("utf-8")
            for i in range(0, len(values), 2)
        }
        if len(result) * 2 != len(values):
            raise ValueError
        return result
    except (ValueError, UnicodeError, AttributeError, IndexError):
        raise CodeKnowledgeError("CODE_CHECKOUT_METADATA_INVALID") from None


class CodeCheckoutReader:
    def __init__(self, root: Path, grant: dict[str, Any]) -> None:
        self.grant = grant
        self.root = root / code_path(grant["directory"])
        self._identity()

    def _identity(self) -> None:
        if self.root.resolve(strict=True) != self.root or self.root.is_symlink():
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
        info = self.root.stat()
        if digest([info.st_dev, info.st_ino]) != self.grant["physical_key"]:
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")

    @contextmanager
    def _metadata(self) -> Iterator[sqlite3.Connection]:
        self._identity()
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = None
        descriptor = None
        connection = None
        try:
            metadata = os.open(
                ".svn", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            descriptor = os.open(
                "wc.db", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=metadata
            )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > 128 * 1024**2:
                raise CodeKnowledgeError("CODE_CHECKOUT_METADATA_INVALID")
            # The production Runtime is Linux on each supported Docker host. A held
            # FD prevents a pathname swap from replacing the checked SQLite file.
            fd_path = Path(f"/proc/self/fd/{descriptor}")
            target = str(fd_path) if fd_path.exists() else str(self.root / ".svn/wc.db")
            connection = sqlite3.connect(
                "file:" + quote(target, safe="/") + "?mode=ro&immutable=1", uri=True, timeout=1
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            if connection.execute("PRAGMA user_version").fetchone()[0] != 31:
                raise CodeKnowledgeError("CODE_CHECKOUT_FORMAT_UNSUPPORTED")
            yield connection
            after = os.fstat(descriptor)
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_CHANGED")
        except (OSError, sqlite3.Error):
            raise CodeKnowledgeError("CODE_CHECKOUT_METADATA_INVALID") from None
        finally:
            if connection is not None:
                connection.close()
            if descriptor is not None:
                os.close(descriptor)
            if metadata is not None:
                os.close(metadata)
            os.close(directory)

    def tracked(self, path: str, *, directory: bool = False) -> dict[str, Any]:
        path = code_path(path, root=directory)
        if not path_in_scope(path, self.grant["allowed_paths"]):
            raise CodeKnowledgeError("CODE_SOURCE_PATH_DENIED")
        with self._metadata() as conn:
            rows = conn.execute(
                "SELECT n.*,r.uuid FROM NODES n JOIN REPOSITORY r ON r.id=n.repos_id WHERE local_relpath=?",
                (path,),
            ).fetchall()
            actual = conn.execute(
                "SELECT 1 FROM ACTUAL_NODE WHERE local_relpath=?", (path,)
            ).fetchone()
            if len(rows) != 1 or actual:
                raise CodeKnowledgeError("CODE_CHECKOUT_DIRTY")
            row = dict(rows[0])
        expected = "/".join(p for p in (self.grant["branch_path"].strip("/"), path) if p)
        if (
            row["op_depth"] != 0
            or row["presence"] != "normal"
            or row["file_external"]
            or row["moved_here"]
            or row["moved_to"]
            or row["symlink_target"]
            or row["revision"] != self.grant["revision"]
            or row["uuid"] != self.grant["repository_uuid"]
            or row["repos_path"] != expected
            or row["kind"] != ("dir" if directory else "file")
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_SOURCE_MISMATCH")
        target = self.root / path
        if target.resolve(strict=True) != target or target.is_symlink():
            raise CodeKnowledgeError("CODE_SOURCE_PATH_DENIED")
        return row

    def read(self, path: str, start: int, limit: int) -> dict[str, Any]:
        if type(start) is not int or type(limit) is not int or start < 1 or not 1 <= limit <= 400:
            raise CodeKnowledgeError("CODE_SOURCE_READ_LIMIT")
        row = self.tracked(path)
        if SENSITIVE_NAME.search(Path(path).name):
            raise CodeKnowledgeError("CODE_SOURCE_SENSITIVE")
        checksum = row["checksum"]
        if not isinstance(checksum, str) or not re.fullmatch(r"\$sha1\$[0-9a-f]{40}", checksum):
            raise CodeKnowledgeError("CODE_CHECKOUT_METADATA_INVALID")
        checksum = checksum.removeprefix("$sha1$")
        pristine = _read_beneath(
            self.root, f".svn/pristine/{checksum[:2]}/{checksum}.svn-base", MAX_FILE
        )
        if sha1(pristine).hexdigest() != checksum:  # SVN format-31's own content address.
            raise CodeKnowledgeError("CODE_CHECKOUT_PRISTINE_CHANGED")
        working = _read_beneath(self.root, path, MAX_FILE)
        text, encoding = decode_source(pristine)
        actual, _ = decode_source(working)
        properties = svn_properties(row["properties"])
        if "svn:special" in properties:
            raise CodeKnowledgeError("CODE_SOURCE_PATH_DENIED")
        equivalent, expected = actual, text
        if "svn:eol-style" in properties:
            if properties["svn:eol-style"] not in {"native", "LF", "CRLF", "CR"}:
                raise CodeKnowledgeError("CODE_CHECKOUT_METADATA_INVALID")
            equivalent, expected = (
                v.replace("\r\n", "\n").replace("\r", "\n") for v in (equivalent, expected)
            )
        keywords = properties.get("svn:keywords", "").split()
        aliases = [
            {"Date", "LastChangedDate"},
            {"Revision", "Rev", "LastChangedRevision"},
            {"Author", "LastChangedBy"},
            {"HeadURL", "URL"},
            {"Id"},
            {"Header"},
        ]
        names = set()
        for keyword in keywords:
            name = keyword.split("=", 1)[0]
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,80}", name):
                raise CodeKnowledgeError("CODE_SOURCE_KEYWORDS_UNSUPPORTED")
            names.update(next((group for group in aliases if name in group), {name}))
        for name in sorted(names):
            expression = re.compile(r"\$" + re.escape(name) + r"(?::[^\r\n$]*)?\$")
            equivalent, expected = (
                expression.sub("$" + name + "$", v) for v in (equivalent, expected)
            )
        if equivalent != expected:
            raise CodeKnowledgeError("CODE_CHECKOUT_DIRTY")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if SENSITIVE_CONTENT.search(text):
            raise CodeKnowledgeError("CODE_SOURCE_SENSITIVE")
        lines = text.splitlines(keepends=True)
        selected = lines[start - 1 : start - 1 + limit]
        excerpt = "".join(selected)
        if not selected or len(excerpt.encode()) > 64 * 1024:
            raise CodeKnowledgeError("CODE_SOURCE_READ_LIMIT")
        return dict(
            text=excerpt,
            line_start=start,
            line_end=start + len(selected) - 1,
            repository_content_hash=sha256(pristine).hexdigest(),
            read_content_hash=sha256(excerpt.encode()).hexdigest(),
            representation=dict(
                source_encoding=encoding,
                newline="LF",
                keyword_policy="repository_unexpanded",
                working_content_hash=sha256(working).hexdigest(),
                line_mapping="identity",
            ),
        )
