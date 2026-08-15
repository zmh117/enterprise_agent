from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Never


SANDBOX_MARKER = ".enterprise-agent-sandbox.json"
SANDBOX_SCHEMA_VERSION = 1
SANDBOX_FILE_LIMIT = 40
SANDBOX_CAPACITY_BYTES = 224 * 1024 * 1024
SANDBOX_FILE_BYTES = 15 * 1024 * 1024
ALLOWED_FILE_TOOLS = frozenset({"Read", "Grep", "Write", "Edit"})
ALLOWED_TOP_LEVEL = frozenset({"inputs", "work", "outputs", "tmp"})


class JobSandboxError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class JobSandboxLimits:
    capacity_bytes: int = SANDBOX_CAPACITY_BYTES
    max_files: int = SANDBOX_FILE_LIMIT
    max_file_bytes: int = SANDBOX_FILE_BYTES

    def __post_init__(self) -> None:
        if (
            self.capacity_bytes < self.max_file_bytes
            or self.max_files < 1
            or self.max_file_bytes < 1
        ):
            raise ValueError("Job Sandbox limits are invalid")


@dataclass(slots=True)
class JobSandbox:
    job_id: str
    path: Path
    limits: JobSandboxLimits

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def authorize_tool(self, tool_name: str, raw_input: object) -> dict[str, object]:
        if tool_name not in ALLOWED_FILE_TOOLS or not isinstance(raw_input, dict):
            self._deny("sandbox_tool_denied", "tool is not allowed in the Job Sandbox")
        value = dict(raw_input)
        expected = {
            "Read": {"file_path", "offset", "limit", "pages"},
            "Grep": {
                "pattern",
                "path",
                "glob",
                "output_mode",
                "-B",
                "-A",
                "-C",
                "-n",
                "-i",
                "type",
                "head_limit",
                "offset",
                "multiline",
            },
            "Write": {"file_path", "content"},
            "Edit": {"file_path", "old_string", "new_string", "replace_all"},
        }[tool_name]
        if not set(value) <= expected:
            self._deny("sandbox_tool_input_invalid", "tool input contains unknown fields")
        path_field = "path" if tool_name == "Grep" else "file_path"
        raw_path = value.get(path_field, "." if tool_name == "Grep" else "")
        relative = self._relative_path(raw_path, allow_root=tool_name == "Grep")
        target = self._target(relative, allow_root=tool_name == "Grep")
        self._reject_symlinks(target)
        if tool_name in {"Read", "Grep"}:
            if not target.exists():
                self._deny("sandbox_entry_missing", "sandbox entry does not exist")
            if tool_name == "Read" and not target.is_file():
                self._deny("sandbox_entry_invalid", "Read requires a regular TXT file")
            if tool_name == "Grep" and not (target.is_dir() or target.is_file()):
                self._deny("sandbox_entry_invalid", "Grep requires a regular path")
            if tool_name == "Grep":
                pattern = value.get("pattern")
                if not isinstance(pattern, str) or not 1 <= len(pattern) <= 1024:
                    self._deny("sandbox_tool_input_invalid", "Grep pattern is invalid")
        else:
            self._authorize_write(tool_name, target, value)
        value[path_field] = relative
        return value

    def _authorize_write(
        self, tool_name: str, target: Path, value: Mapping[str, object]
    ) -> None:
        if target.exists() and not target.is_file():
            self._deny("sandbox_entry_invalid", "write target must be a regular file")
        content = value.get("content") if tool_name == "Write" else value.get("new_string")
        if not isinstance(content, str):
            self._deny("sandbox_tool_input_invalid", "write content must be text")
        incoming = len(content.encode("utf-8"))
        if incoming > self.limits.max_file_bytes:
            self._deny("sandbox_file_limit_exceeded", "TXT file exceeds the sandbox limit")
        file_count, total_bytes = self.usage()
        previous = target.stat().st_size if target.exists() else 0
        if not target.exists() and file_count >= self.limits.max_files:
            self._deny("sandbox_file_count_exceeded", "sandbox file count is exhausted")
        if total_bytes - previous + max(previous, incoming) > self.limits.capacity_bytes:
            self._deny("sandbox_capacity_exceeded", "sandbox capacity is exhausted")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def usage(self) -> tuple[int, int]:
        count = 0
        size_bytes = 0
        for root, directories, files in os.walk(self.path, followlinks=False):
            root_path = Path(root)
            for name in directories:
                entry = root_path / name
                if entry.is_symlink():
                    self._deny("sandbox_symlink_denied", "sandbox contains a symlink")
            for name in files:
                if name == SANDBOX_MARKER:
                    continue
                entry = root_path / name
                state = entry.lstat()
                if stat.S_ISLNK(state.st_mode):
                    self._deny("sandbox_symlink_denied", "sandbox contains a symlink")
                if not stat.S_ISREG(state.st_mode):
                    self._deny("sandbox_special_file_denied", "sandbox contains a special file")
                count += 1
                size_bytes += state.st_size
        return count, size_bytes

    def _relative_path(self, value: object, *, allow_root: bool) -> str:
        if not isinstance(value, str) or not 1 <= len(value) <= 240:
            self._deny("sandbox_path_invalid", "sandbox path is invalid")
        if "\\" in value or "\x00" in value:
            self._deny("sandbox_path_invalid", "sandbox path is invalid")
        if value == "." and allow_root:
            return value
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or str(path) != value
            or "." in path.parts
            or ".." in path.parts
            or not path.parts
            or path.parts[0] not in ALLOWED_TOP_LEVEL
        ):
            self._deny("sandbox_path_invalid", "sandbox path escaped its Job boundary")
        if path.suffix.lower() != ".txt":
            self._deny("sandbox_file_type_denied", "only TXT files are allowed")
        return value

    def _target(self, relative: str, *, allow_root: bool) -> Path:
        root = self.path.resolve(strict=True)
        if relative == "." and allow_root:
            return root
        target = root / relative
        try:
            target.relative_to(root)
        except ValueError:
            self._deny("sandbox_path_invalid", "sandbox path escaped its Job boundary")
        return target

    def _reject_symlinks(self, target: Path) -> None:
        current = self.path
        try:
            parts = target.relative_to(self.path).parts
        except ValueError:
            self._deny("sandbox_path_invalid", "sandbox path escaped its Job boundary")
        for part in parts:
            current /= part
            if current.exists() or current.is_symlink():
                state = current.lstat()
                if stat.S_ISLNK(state.st_mode):
                    self._deny("sandbox_symlink_denied", "symbolic links are not allowed")
                if not (stat.S_ISDIR(state.st_mode) or stat.S_ISREG(state.st_mode)):
                    self._deny("sandbox_special_file_denied", "special files are not allowed")

    @staticmethod
    def _deny(code: str, message: str) -> Never:
        raise JobSandboxError(code, message)


class JobSandboxManager:
    def __init__(
        self,
        root: Path,
        *,
        limits: JobSandboxLimits | None = None,
    ) -> None:
        self.root = root
        self.limits = limits or JobSandboxLimits()

    def create(self, job_id: str) -> JobSandbox:
        self._identifier(job_id)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:24]
        path = self.root / f"job-{digest}-{uuid.uuid4().hex}"
        path.mkdir(mode=0o700)
        for name in sorted(ALLOWED_TOP_LEVEL):
            (path / name).mkdir(mode=0o700)
        marker = {
            "schema_version": SANDBOX_SCHEMA_VERSION,
            "job_id": job_id,
        }
        (path / SANDBOX_MARKER).write_text(
            json.dumps(marker, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(path / SANDBOX_MARKER, 0o600)
        return JobSandbox(job_id=job_id, path=path, limits=self.limits)

    def cleanup_residuals(self, is_job_running: Callable[[str], bool]) -> list[str]:
        if not self.root.exists():
            return []
        cleaned: list[str] = []
        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or path.is_symlink() or not path.name.startswith("job-"):
                continue
            marker_path = path / SANDBOX_MARKER
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                not isinstance(marker, dict)
                or set(marker) != {"schema_version", "job_id"}
                or marker.get("schema_version") != SANDBOX_SCHEMA_VERSION
                or not isinstance(marker.get("job_id"), str)
            ):
                continue
            job_id = str(marker["job_id"])
            try:
                self._identifier(job_id)
            except JobSandboxError:
                continue
            if is_job_running(job_id):
                continue
            shutil.rmtree(path)
            cleaned.append(job_id)
        return cleaned

    @staticmethod
    def _identifier(value: str) -> None:
        if (
            not 1 <= len(value) <= 128
            or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for character in value)
        ):
            raise JobSandboxError("sandbox_job_id_invalid", "Job id is invalid")
