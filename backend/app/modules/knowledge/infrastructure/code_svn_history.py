"""Bounded SVN history at explicit revisions; never changes a working copy.

The service supplies the authorized scope, peg and numeric history window. Results
are transient tool data; persistence stores only permitted metadata and digests.
"""

from datetime import datetime
from typing import Any
from urllib.parse import unquote

from app.modules.knowledge.domain.code_answers import (
    MAX_RESPONSE_BYTES,
    code_path,
    path_in_scope,
    svn_revision,
    utc_time,
)
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_text import decode_source
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource, xml_document
from app.modules.knowledge.infrastructure.code_source import SENSITIVE_NAME, SENSITIVE_CONTENT


class SvnCodeHistory:
    def __init__(self, source: SvnCodeSource, *, paths: list[str], lower: int, upper: int):
        self.source = source
        self.paths = [code_path(p, root=True) for p in paths]
        self.lower, self.upper = svn_revision(lower), svn_revision(upper)
        if not self.paths or lower > upper:
            raise CodeKnowledgeError("CODE_HISTORY_SCOPE_INVALID")

    def _revision(self, n: int) -> int:
        n = svn_revision(n)
        if not self.lower <= n <= self.upper:
            raise CodeKnowledgeError("CODE_HISTORY_VERSION_DENIED")
        return n

    def _path(self, path: str, *, parent: bool = False) -> str:
        path = code_path(path, root=True)
        if not path_in_scope(path, self.paths) and not (
            parent and any(path == "" or p.startswith(path + "/") for p in self.paths)
        ):
            raise CodeKnowledgeError("CODE_HISTORY_PATH_DENIED")
        return path

    def _repository_path(self, path: str) -> str | None:
        prefix = self.source.branch_path
        if path == (prefix or "/"):
            return ""
        if not path.startswith(prefix + "/"):
            return None
        return code_path(path[len(prefix) + 1 :])

    @staticmethod
    def _bounded(value: dict[str, Any]) -> dict[str, Any]:
        if len(canonical_json(value).encode()) > MAX_RESPONSE_BYTES:
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_TOO_LARGE")
        return {**value, "result_hash": digest(value)}

    def info(self, *, path: str, revision: int, peg: int) -> dict[str, Any]:
        path, revision, peg = (
            self._path(path, parent=True),
            self._revision(revision),
            self._revision(peg),
        )
        xml = xml_document(
            self.source._run("info", ["--xml", "-r", str(revision), self.source._target(peg, path)])
        )
        entry = xml.find("entry")
        if entry is None or entry.findtext("repository/uuid") != self.source.expected_uuid:
            raise CodeKnowledgeError("CODE_HISTORY_ENDPOINT_UNAVAILABLE")
        url = unquote(entry.findtext("relative-url") or "")
        resolved = self._repository_path(url[1:]) if url.startswith("^/") else None
        if resolved is None or resolved != path:
            raise CodeKnowledgeError("CODE_HISTORY_PATH_DENIED")
        commit = entry.find("commit")
        if commit is None or entry.get("kind") not in {"file", "dir"}:
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
        return self._bounded(
            dict(
                repository_uuid=self.source.expected_uuid,
                branch_path=self.source.branch_path,
                path=path,
                revision=revision,
                kind=entry.get("kind"),
                last_changed_revision=self._parse_revision(commit.get("revision")),
            )
        )

    def log(
        self,
        *,
        path: str,
        start: int,
        end: int,
        peg: int,
        limit: int = 100,
        before: int | None = None,
        include_message: bool = False,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        path = self._path(path, parent=True)
        start, end, peg = self._revision(start), self._revision(end), self._revision(peg)
        if start > end or type(limit) is not int or not 1 <= limit <= 200:
            raise CodeKnowledgeError("CODE_HISTORY_RANGE_INVALID")
        if (start_time is None) != (end_time is None):
            raise CodeKnowledgeError("CODE_HISTORY_TIME_INVALID")
        if start_time is not None and end_time is not None:
            start_time, end_time = utc_time(start_time), utc_time(end_time)
            if start_time >= end_time:
                raise CodeKnowledgeError("CODE_HISTORY_TIME_INVALID")
        high = end if before is None else self._revision(before)
        if not start <= high <= end:
            raise CodeKnowledgeError("CODE_HISTORY_CURSOR_INVALID")
        low = max(start, high - 9999)
        xml = xml_document(
            self.source._run(
                "log",
                [
                    "--xml",
                    "--verbose",
                    "--limit",
                    str(limit + 1),
                    "-r",
                    f"{high}:{low}",
                    self.source._target(peg, path),
                ],
            )
        )
        if xml.tag != "log":
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
        entries = xml.findall("logentry")
        if len(entries) > limit + 1:
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
        rows, last, partial = [], None, False
        for item in entries[:limit]:
            revision = self._parse_revision(item.get("revision"))
            if not low <= revision <= high or (last is not None and revision >= last):
                raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
            last = revision
            row = self._log_entry(item, revision, include_message)
            partial |= row["paths_truncated"] or row["date"] is None
            date = utc_time(row["date"]) if row["date"] is not None else None
            if (
                start_time is not None
                and end_time is not None
                and (date is None or not start_time <= date < end_time)
            ):
                continue
            if row["paths"]:
                rows.append(row)
        next_revision = (last - 1) if len(entries) > limit and last is not None else (low - 1)
        has_more = next_revision >= start
        return self._bounded(
            dict(
                entries=rows,
                from_revision=start,
                to_revision=end,
                peg_revision=peg,
                scanned_from=low if len(entries) <= limit else last,
                scanned_to=high,
                has_more=has_more,
                next_revision=next_revision if has_more else None,
                partial=partial or has_more,
            )
        )

    def _log_entry(self, item: Any, revision: int, include_message: bool) -> dict[str, Any]:
        paths: list[dict[str, Any]] = []
        omitted = False
        for element in item.findall("./paths/path"):
            path = self._repository_path(element.text or "")
            if path is None or not path_in_scope(path, self.paths):
                omitted = True
                continue
            if len(paths) >= 1000:
                omitted = True
                continue
            action = element.get("action")
            if action not in {"A", "M", "D", "R"}:
                raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
            copy_original = element.get("copyfrom-path")
            copy = copy_original
            copy = self._repository_path(copy) if copy is not None else None
            copy_revision = (
                self._parse_revision(element.get("copyfrom-rev")) if copy is not None else None
            )
            if copy_original is not None and (
                copy is None
                or copy_revision is None
                or not path_in_scope(copy, self.paths)
                or not self.lower <= copy_revision <= self.upper
            ):
                copy, copy_revision, omitted = None, None, True
            paths.append(
                dict(
                    path=path,
                    action=action,
                    kind=element.get("kind", "unknown"),
                    copy_from_path=copy,
                    copy_from_revision=copy_revision,
                )
            )
        date = item.findtext("date")
        try:
            date = utc_time(date).isoformat() if date else None
        except CodeKnowledgeError:
            date = None
        message = item.findtext("msg") if include_message and not omitted else None
        if message and (len(message.encode()) > 8192 or SENSITIVE_CONTENT.search(message)):
            message, omitted = None, True
        author = item.findtext("author")
        if author and len(author) > 500:
            author = None
        return dict(
            revision=revision,
            author=author,
            date=date,
            message=message,
            paths=paths,
            paths_truncated=omitted,
            message_omitted=bool(include_message and (omitted or message is None)),
        )

    def diff(
        self, *, path: str, start: int, end: int, peg: int, mode: str = "summary", offset: int = 0
    ) -> dict[str, Any]:
        path = self._path(path, parent=mode == "summary")
        start, end, peg = self._revision(start), self._revision(end), self._revision(peg)
        if (
            mode not in {"summary", "text"}
            or type(offset) is not int
            or offset < 0
            or offset > 10000
        ):
            raise CodeKnowledgeError("CODE_HISTORY_DIFF_INVALID")
        args = ["--notice-ancestry", "-r", f"{start}:{end}", self.source._target(peg, path)]
        base = dict(from_revision=start, to_revision=end, peg_revision=peg, mode=mode)
        if mode == "text":
            if not path or offset:
                raise CodeKnowledgeError("CODE_HISTORY_SINGLE_FILE_REQUIRED")
            if SENSITIVE_NAME.search(path.rsplit("/", 1)[-1]):
                raise CodeKnowledgeError("CODE_SOURCE_SENSITIVE")
            info = xml_document(
                self.source._run("info", ["--xml", "-r", str(peg), self.source._target(peg, path)])
            )
            entry = info.find("entry")
            if entry is None or entry.get("kind") != "file":
                raise CodeKnowledgeError("CODE_HISTORY_SINGLE_FILE_REQUIRED")
            for endpoint in {start, end}:
                self._verify_file_endpoint(path, endpoint, peg)
            encodings = {}
            for endpoint in {start, end}:
                raw = self.source._run("cat", ["-r", str(endpoint), self.source._target(peg, path)])
                content, encoding = decode_source(raw)
                if SENSITIVE_CONTENT.search(content):
                    raise CodeKnowledgeError("CODE_SOURCE_SENSITIVE")
                encodings[endpoint] = encoding
            data = self.source._run("diff", ["--force", *args])
            if len(data) > 256 * 1024:
                raise CodeKnowledgeError("CODE_HISTORY_DIFF_TOO_LARGE")
            text = decode_diff(data, encodings[start], encodings[end])
            return self._bounded(
                {
                    **base,
                    "text": text,
                    "partial": False,
                    "source_encodings": {"before": encodings[start], "after": encodings[end]},
                }
            )
        xml = xml_document(self.source._run("diff", ["--summarize", "--xml", *args]))
        if xml.tag != "diff":
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
        rows = []
        omitted = False
        for item in xml.findall("./paths/path"):
            url = item.text or ""
            prefix = self.source.branch_url
            if url == prefix:
                relative = ""
            elif url.startswith(prefix + "/"):
                relative = code_path(unquote(url[len(prefix) + 1 :]))
            else:
                raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
            if not path_in_scope(relative, self.paths):
                omitted = True
                continue
            rows.append(
                dict(
                    path=relative,
                    kind=item.get("kind"),
                    content=item.get("item"),
                    properties=item.get("props"),
                )
            )
        rows.sort(key=lambda r: str(r["path"]))
        return self._bounded(
            {
                **base,
                "paths": rows[offset : offset + 1000],
                "has_more": len(rows) > offset + 1000,
                "next_offset": offset + 1000 if len(rows) > offset + 1000 else None,
                "partial": omitted or len(rows) > offset + 1000,
            }
        )

    def _verify_file_endpoint(self, path: str, revision: int, peg: int) -> None:
        # A peg can follow copies outside the authorized branch/path. Checking
        # only the model's current path would expose the old file through diff.
        xml = xml_document(
            self.source._run("info", ["--xml", "-r", str(revision), self.source._target(peg, path)])
        )
        entry = xml.find("entry")
        if (
            entry is None
            or entry.get("kind") != "file"
            or entry.findtext("repository/uuid") != self.source.expected_uuid
        ):
            raise CodeKnowledgeError("CODE_HISTORY_ENDPOINT_UNAVAILABLE")
        url = unquote(entry.findtext("relative-url") or "")
        resolved = self._repository_path(url[1:]) if url.startswith("^/") else None
        if resolved is None or not path_in_scope(resolved, self.paths):
            raise CodeKnowledgeError("CODE_HISTORY_PATH_DENIED")

    def blame(
        self, *, path: str, revision: int, peg: int, start_line: int, end_line: int
    ) -> dict[str, Any]:
        path = self._path(path)
        revision, peg = self._revision(revision), self._revision(peg)
        if (
            not path
            or type(start_line) is not int
            or type(end_line) is not int
            or start_line < 1
            or not start_line <= end_line < start_line + 400
        ):
            raise CodeKnowledgeError("CODE_HISTORY_LINES_INVALID")
        self._verify_file_endpoint(path, revision, peg)
        xml = xml_document(
            self.source._run(
                "blame", ["--xml", "-r", str(revision), self.source._target(peg, path)]
            )
        )
        if xml.tag != "blame":
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
        rows: list[dict[str, Any]] = []
        last = 0
        for item in xml.findall("./target/entry"):
            number = self._parse_revision(item.get("line-number"))
            if number != last + 1:
                raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID")
            last = number
            if start_line <= number <= end_line:
                commit = item.find("commit")
                rows.append(
                    dict(
                        line=number,
                        last_changed_revision=self._parse_revision(commit.get("revision"))
                        if commit is not None
                        else None,
                        author=commit.findtext("author") if commit is not None else None,
                        date=commit.findtext("date") if commit is not None else None,
                    )
                )
        changed_revisions = {
            row["last_changed_revision"] for row in rows if row["last_changed_revision"] is not None
        }
        for changed in changed_revisions:
            self._revision(changed)
            self._verify_file_endpoint(path, changed, peg)
        return self._bounded(
            dict(
                path=path,
                revision=revision,
                peg_revision=peg,
                lines=rows,
                partial=last < end_line,
                total_lines=last,
            )
        )

    @staticmethod
    def _parse_revision(value: Any) -> int:
        try:
            if not isinstance(value, str) or not value.isascii() or not value.isdigit():
                raise ValueError
            return svn_revision(int(value))
        except (ValueError, TypeError):
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_INVALID") from None


def decode_diff(data: bytes, before: str, after: str) -> str:
    """SVN headers use UTF-8, hunk text retains each endpoint's original encoding."""
    if "utf-16" in {before, after}:
        raise CodeKnowledgeError("CODE_HISTORY_ENCODING_UNSUPPORTED")
    hunks = False
    lines = []
    for line in data.splitlines(keepends=True):
        if line.startswith((b"Index: ", b"Property changes on: ")):
            hunks = False
        encoding = "utf-8"
        if hunks and line[:1] in {b"+", b"-", b" "}:
            encoding = before if line.startswith(b"-") else after
        if line.startswith((b"@@ ", b"## ")):
            hunks = True
        try:
            # Do not strip a BOM inside a hunk or normalize EOL differences.
            lines.append(line.decode("utf-8" if encoding == "utf-8-sig" else encoding))
        except UnicodeError:
            raise CodeKnowledgeError("CODE_HISTORY_ENCODING_UNSUPPORTED") from None
    return "".join(lines)
