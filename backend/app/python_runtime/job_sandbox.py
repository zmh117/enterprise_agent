from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Never

from app.modules.file_workspace.text_format_policy import (
    get_text_format_policy,
    text_format_for_name,
)
from app.shared.exceptions import NonRetryableExecutionError


SANDBOX_MARKER = ".enterprise-agent-sandbox.json"
SANDBOX_SCHEMA_VERSION = 1
SANDBOX_FILE_LIMIT = 64
SANDBOX_CAPACITY_BYTES = 224 * 1024 * 1024
SANDBOX_FILE_BYTES = 15 * 1024 * 1024
SANDBOX_INPUT_FILE_LIMIT = 40
SANDBOX_WORK_OUTPUT_FILE_LIMIT = 16
SANDBOX_TMP_FILE_LIMIT = 8
FILE_TOOL_NAMES = ("Read", "Glob", "Grep", "Edit", "Write")
ALLOWED_FILE_TOOLS = frozenset(FILE_TOOL_NAMES)
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
    max_input_files: int = SANDBOX_INPUT_FILE_LIMIT
    max_work_output_files: int = SANDBOX_WORK_OUTPUT_FILE_LIMIT
    max_tmp_files: int = SANDBOX_TMP_FILE_LIMIT

    def __post_init__(self) -> None:
        if (
            self.capacity_bytes < self.max_file_bytes
            or self.max_files < 1
            or self.max_file_bytes < 1
            or self.max_input_files < 1
            or self.max_work_output_files < 1
            or self.max_tmp_files < 1
            or self.max_input_files + self.max_work_output_files + self.max_tmp_files
            > self.max_files
        ):
            raise ValueError("Job Sandbox limits are invalid")


@dataclass(frozen=True, slots=True)
class SandboxInputReservation:
    token: str
    identity: tuple[str, str]
    expected_size_bytes: int
    relative_path: str = ""
    committed: bool = False
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class SandboxReservation:
    token: str
    partition: str
    relative_path: str
    expected_size_bytes: int


@dataclass(frozen=True, slots=True)
class SandboxCommittedInput:
    identity: tuple[str, str]
    relative_path: str
    absolute_path: Path = field(repr=False)
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SandboxRuntimeArtifactReservation:
    token: str
    relative_path: str
    staging_relative_path: str
    maximum_size_bytes: int


@dataclass(frozen=True, slots=True)
class SandboxRuntimeArtifact:
    relative_path: str
    absolute_path: Path = field(repr=False)
    size_bytes: int
    sha256: str
    request_digest: str
    public_payload: Mapping[str, object]


@dataclass(slots=True)
class _PendingReservation:
    token: str
    partition: str
    expected_size_bytes: int
    identity: tuple[str, str] | None = None
    relative_path: str = ""
    staging_relative_path: str = ""


@dataclass(frozen=True, slots=True)
class _CommittedInput:
    identity: tuple[str, str]
    relative_path: str
    size_bytes: int
    sha256: str
    device: int
    inode: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _RuntimeArtifact:
    relative_path: str
    size_bytes: int
    sha256: str
    request_digest: str
    public_payload: Mapping[str, object]


@dataclass(slots=True)
class JobSandbox:
    job_id: str
    path: Path
    limits: JobSandboxLimits
    _budget_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _pending: dict[str, _PendingReservation] = field(default_factory=dict, repr=False)
    _input_tokens: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _committed_inputs: dict[tuple[str, str], _CommittedInput] = field(
        default_factory=dict, repr=False
    )
    _write_reservations: dict[str, str] = field(default_factory=dict, repr=False)
    _runtime_artifacts: dict[str, _RuntimeArtifact] = field(default_factory=dict, repr=False)

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def authorize_tool(self, tool_name: str, raw_input: object) -> dict[str, object]:
        if tool_name not in ALLOWED_FILE_TOOLS or not isinstance(raw_input, dict):
            self._deny("sandbox_tool_denied", "tool is not allowed in the Job Sandbox")
        value = dict(raw_input)
        expected = {
            "Read": {"file_path", "offset", "limit", "pages"},
            "Glob": {"pattern", "path"},
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
        directory_tool = tool_name in {"Glob", "Grep"}
        path_field = "path" if directory_tool else "file_path"
        raw_path = value.get(path_field, "." if directory_tool else "")
        relative = (
            self._directory_path(raw_path)
            if tool_name == "Glob"
            else self._relative_path(
                raw_path,
                allow_root=tool_name == "Grep",
                write=tool_name in {"Write", "Edit"},
            )
        )
        target = self._target(relative, allow_root=directory_tool)
        self._reject_symlinks(target)
        if tool_name in {"Read", "Glob", "Grep"}:
            if not target.exists():
                self._deny("sandbox_entry_missing", "sandbox entry does not exist")
            if tool_name == "Read" and not target.is_file():
                self._deny("sandbox_entry_invalid", "Read requires a regular text file")
            if tool_name == "Glob" and not target.is_dir():
                self._deny("sandbox_entry_invalid", "Glob requires a regular directory")
            if tool_name == "Grep" and not (target.is_dir() or target.is_file()):
                self._deny("sandbox_entry_invalid", "Grep requires a regular path")
            if tool_name == "Grep":
                pattern = value.get("pattern")
                if not isinstance(pattern, str) or not 1 <= len(pattern) <= 1024:
                    self._deny("sandbox_tool_input_invalid", "Grep pattern is invalid")
            if tool_name == "Glob":
                self._glob_pattern(value.get("pattern"))
        else:
            self._authorize_write(tool_name, target, value)
        value[path_field] = relative
        return value

    def _authorize_write(self, tool_name: str, target: Path, value: Mapping[str, object]) -> None:
        relative = target.relative_to(self.path.resolve(strict=True)).as_posix()
        top_level = PurePosixPath(relative).parts[0]
        if relative in self._runtime_artifacts:
            self._deny(
                "sandbox_file_read_only",
                "Runtime-generated evidence artifacts are read-only",
            )
        if top_level == "tmp" or (top_level == "inputs" and not target.exists()):
            self._deny(
                "sandbox_write_partition_denied",
                "Agent cannot create inputs or write internal temporary files",
            )
        if target.exists() and not target.is_file():
            self._deny("sandbox_entry_invalid", "write target must be a regular file")
        content = value.get("content") if tool_name == "Write" else value.get("new_string")
        if not isinstance(content, str):
            self._deny("sandbox_tool_input_invalid", "write content must be text")
        incoming = len(content.encode("utf-8"))
        if incoming > self.limits.max_file_bytes:
            self._deny("sandbox_file_limit_exceeded", "text file exceeds the sandbox limit")
        with self._budget_lock:
            self._reconcile_write_reservations()
            previous = target.stat().st_size if target.exists() else 0
            projected = max(previous, incoming)
            old_token = self._write_reservations.get(relative)
            if old_token:
                self._pending.pop(old_token, None)
            token = self._reserve_locked(
                partition="inputs" if top_level == "inputs" else "work_outputs",
                expected_size_bytes=projected,
                relative_path=relative,
                replacing_size_bytes=previous,
                replacing_file=target.exists(),
            )
            self._write_reservations[relative] = token
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def reserve_input(
        self, *, identity: tuple[str, str], expected_size_bytes: int
    ) -> SandboxInputReservation:
        """Reserve one exact File/Version before any target file is created."""

        if expected_size_bytes < 0 or expected_size_bytes > self.limits.max_file_bytes:
            self._deny("sandbox_file_limit_exceeded", "input exceeds the sandbox file limit")
        with self._budget_lock:
            committed = self._committed_inputs.get(identity)
            if committed is not None:
                if committed.size_bytes != expected_size_bytes:
                    self._deny(
                        "sandbox_input_identity_conflict",
                        "input identity was already materialized with different content",
                    )
                return SandboxInputReservation(
                    token="",
                    identity=identity,
                    expected_size_bytes=committed.size_bytes,
                    relative_path=committed.relative_path,
                    committed=True,
                    sha256=committed.sha256,
                )
            existing_token = self._input_tokens.get(identity)
            if existing_token:
                pending = self._pending[existing_token]
                if pending.expected_size_bytes != expected_size_bytes:
                    self._deny(
                        "sandbox_input_identity_conflict",
                        "input identity reservation size changed",
                    )
                return SandboxInputReservation(
                    token=pending.token,
                    identity=identity,
                    expected_size_bytes=pending.expected_size_bytes,
                    relative_path=pending.relative_path,
                )
            token = self._reserve_locked(
                partition="inputs",
                expected_size_bytes=expected_size_bytes,
                identity=identity,
            )
            self._input_tokens[identity] = token
            return SandboxInputReservation(token, identity, expected_size_bytes)

    def reserve_input_batch(
        self, entries: list[tuple[tuple[str, str], int]]
    ) -> list[SandboxInputReservation]:
        """Atomically reserve a complete automatic-input batch."""

        created: list[SandboxInputReservation] = []
        with self._budget_lock:
            preexisting_tokens = set(self._pending)
            try:
                for identity, expected_size_bytes in entries:
                    created.append(
                        self.reserve_input(
                            identity=identity,
                            expected_size_bytes=expected_size_bytes,
                        )
                    )
            except Exception:
                for reservation in created:
                    if (
                        reservation.token
                        and reservation.token not in preexisting_tokens
                        and not reservation.committed
                    ):
                        self._release_input_locked(reservation.identity)
                raise
        return created

    def reserve_work_output(
        self, *, relative_path: str, expected_size_bytes: int
    ) -> SandboxReservation:
        return self._reserve_named_path(
            partition="work_outputs",
            relative_path=relative_path,
            expected_size_bytes=expected_size_bytes,
            allowed_top_levels={"work", "outputs"},
        )

    def reserve_tmp(self, *, relative_path: str, expected_size_bytes: int) -> SandboxReservation:
        return self._reserve_named_path(
            partition="tmp",
            relative_path=relative_path,
            expected_size_bytes=expected_size_bytes,
            allowed_top_levels={"tmp"},
        )

    def resolve_committed_log_input(self, relative_path: str) -> SandboxCommittedInput:
        """Resolve one exact materialized LOG without broadening Job file authority."""

        path = self._strict_log_input_path(relative_path)
        with self._budget_lock:
            matches = [
                item for item in self._committed_inputs.values() if item.relative_path == path
            ]
            if len(matches) != 1:
                self._deny(
                    "log_evidence_input_not_materialized",
                    "log evidence input is not an exact committed materialization",
                )
            committed = matches[0]
            target = self.path / path
            self._reject_symlinks(target)
            try:
                state = target.lstat()
            except OSError:
                self._deny(
                    "log_evidence_input_not_materialized",
                    "log evidence input is unavailable",
                )
            if not stat.S_ISREG(state.st_mode):
                self._deny(
                    "sandbox_special_file_denied",
                    "log evidence input must be a regular file",
                )
            if (
                state.st_size != committed.size_bytes
                or state.st_dev != committed.device
                or state.st_ino != committed.inode
                or state.st_mtime_ns != committed.modified_ns
            ):
                self._deny(
                    "log_evidence_source_integrity_error",
                    "materialized log content facts changed",
                )
            return SandboxCommittedInput(
                identity=committed.identity,
                relative_path=committed.relative_path,
                absolute_path=target,
                size_bytes=committed.size_bytes,
                sha256=committed.sha256,
            )

    def reserve_runtime_artifact(
        self,
        *,
        relative_path: str,
        maximum_size_bytes: int,
    ) -> SandboxRuntimeArtifactReservation:
        """Reserve one final work/output slot with an unpublished staging name."""

        path = PurePosixPath(relative_path)
        if (
            path.is_absolute()
            or str(path) != relative_path
            or not path.parts
            or path.parts[0] not in {"work", "outputs"}
            or "." in path.parts
            or ".." in path.parts
            or path.suffix.casefold() != ".md"
        ):
            self._deny("sandbox_path_invalid", "Runtime artifact path is invalid")
        if maximum_size_bytes < 1 or maximum_size_bytes > self.limits.max_file_bytes:
            self._deny(
                "sandbox_file_limit_exceeded",
                "Runtime artifact exceeds the sandbox file limit",
            )
        with self._budget_lock:
            target = self.path / relative_path
            self._reject_symlinks(target)
            if target.exists() or relative_path in self._runtime_artifacts:
                self._deny("sandbox_entry_conflict", "Runtime artifact already exists")
            token = self._reserve_locked(
                partition="work_outputs",
                expected_size_bytes=maximum_size_bytes,
                relative_path=relative_path,
            )
            staging_name = f".{path.name}.{token.rsplit(':', 1)[-1]}.partial"
            staging_relative_path = str(path.with_name(staging_name))
            self._pending[token].staging_relative_path = staging_relative_path
            staging = self.path / staging_relative_path
            self._reject_symlinks(staging)
            staging.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            return SandboxRuntimeArtifactReservation(
                token=token,
                relative_path=relative_path,
                staging_relative_path=staging_relative_path,
                maximum_size_bytes=maximum_size_bytes,
            )

    def publish_runtime_artifact(
        self,
        reservation: SandboxRuntimeArtifactReservation,
        *,
        expected_size_bytes: int,
        expected_sha256: str,
        request_digest: str,
        public_payload: Mapping[str, object],
    ) -> SandboxRuntimeArtifact:
        """Validate and atomically publish one Runtime-owned read-only artifact."""

        with self._budget_lock:
            pending = self._pending.get(reservation.token)
            if (
                pending is None
                or pending.partition != "work_outputs"
                or pending.relative_path != reservation.relative_path
                or pending.staging_relative_path != reservation.staging_relative_path
            ):
                self._deny(
                    "sandbox_reservation_invalid",
                    "Runtime artifact reservation is inconsistent",
                )
            staging = self.path / reservation.staging_relative_path
            target = self.path / reservation.relative_path
            self._reject_symlinks(staging)
            self._reject_symlinks(target)
            try:
                state = staging.lstat()
            except OSError:
                self._deny(
                    "sandbox_reservation_invalid",
                    "Runtime artifact staging file is unavailable",
                )
            if (
                not stat.S_ISREG(state.st_mode)
                or expected_size_bytes < 0
                or expected_size_bytes != state.st_size
                or expected_size_bytes > pending.expected_size_bytes
                or target.exists()
            ):
                self._deny(
                    "sandbox_reservation_invalid",
                    "Runtime artifact staging file is inconsistent",
                )
            actual_sha256 = self._file_sha256(staging)
            if actual_sha256 != expected_sha256:
                self._deny(
                    "log_evidence_pack_integrity_error",
                    "Runtime artifact hash verification failed",
                )
            staging.replace(target)
            os.chmod(target, 0o400)
            artifact = _RuntimeArtifact(
                relative_path=reservation.relative_path,
                size_bytes=expected_size_bytes,
                sha256=actual_sha256,
                request_digest=request_digest,
                public_payload=dict(public_payload),
            )
            self._runtime_artifacts[reservation.relative_path] = artifact
            self._pending.pop(reservation.token, None)
            return self._public_runtime_artifact(artifact)

    def release_runtime_artifact(self, reservation: SandboxRuntimeArtifactReservation) -> None:
        with self._budget_lock:
            pending = self._pending.get(reservation.token)
            if pending is not None:
                (self.path / reservation.staging_relative_path).unlink(missing_ok=True)
                self._pending.pop(reservation.token, None)

    def runtime_artifact(
        self, *, relative_path: str, request_digest: str
    ) -> SandboxRuntimeArtifact | None:
        with self._budget_lock:
            artifact = self._runtime_artifacts.get(relative_path)
            if artifact is None or artifact.request_digest != request_digest:
                return None
            target = self.path / artifact.relative_path
            self._reject_symlinks(target)
            try:
                state = target.lstat()
            except OSError:
                self._deny(
                    "log_evidence_pack_integrity_error",
                    "Runtime evidence artifact is unavailable",
                )
            if (
                not stat.S_ISREG(state.st_mode)
                or state.st_size != artifact.size_bytes
                or self._file_sha256(target) != artifact.sha256
            ):
                self._deny(
                    "log_evidence_pack_integrity_error",
                    "Runtime evidence artifact failed integrity verification",
                )
            return self._public_runtime_artifact(artifact)

    def commit_reservation(self, reservation: SandboxReservation) -> None:
        with self._budget_lock:
            pending = self._pending.get(reservation.token)
            target = self.path / reservation.relative_path
            if (
                pending is None
                or pending.partition != reservation.partition
                or pending.relative_path != reservation.relative_path
                or not target.is_file()
                or target.stat().st_size > pending.expected_size_bytes
            ):
                self._deny("sandbox_reservation_invalid", "sandbox reservation is inconsistent")
            self._pending.pop(reservation.token, None)

    def release_reservation(self, reservation: SandboxReservation) -> None:
        with self._budget_lock:
            self._pending.pop(reservation.token, None)

    def reconcile(self) -> None:
        with self._budget_lock:
            self._reconcile_write_reservations()

    def assert_within_limits(self) -> None:
        with self._budget_lock:
            self._reconcile_write_reservations()
            usage = self.partition_usage()
            pending = list(self._pending.values())
            limits = {
                "inputs": self.limits.max_input_files,
                "work_outputs": self.limits.max_work_output_files,
                "tmp": self.limits.max_tmp_files,
            }
            for partition, limit in limits.items():
                count = usage[partition][0] + sum(
                    1 for item in pending if item.partition == partition
                )
                if count > limit:
                    self._deny("sandbox_file_count_exceeded", "sandbox partition exceeded")
            count = sum(item[0] for item in usage.values()) + len(pending)
            size = sum(item[1] for item in usage.values()) + sum(
                item.expected_size_bytes for item in pending
            )
            if count > self.limits.max_files:
                self._deny("sandbox_file_count_exceeded", "sandbox file count exceeded")
            if size > self.limits.capacity_bytes:
                self._deny("sandbox_capacity_exceeded", "sandbox capacity exceeded")

    def bind_input_reservation(
        self, reservation: SandboxInputReservation, *, relative_path: str
    ) -> SandboxInputReservation:
        with self._budget_lock:
            if reservation.committed:
                if reservation.relative_path != relative_path:
                    self._deny(
                        "sandbox_input_identity_conflict",
                        "materialized input path changed",
                    )
                return reservation
            pending = self._pending.get(reservation.token)
            if pending is None or pending.identity != reservation.identity:
                self._deny("sandbox_reservation_invalid", "input reservation is unavailable")
            path = PurePosixPath(relative_path)
            if not path.parts or path.parts[0] != "inputs":
                self._deny("sandbox_partition_invalid", "input path is outside inputs")
            if pending.relative_path and pending.relative_path != relative_path:
                self._deny("sandbox_input_identity_conflict", "input path changed")
            target = self.path / relative_path
            if target.exists():
                self._deny("sandbox_entry_conflict", "input target already exists")
            if any(
                item.relative_path == relative_path and item.token != pending.token
                for item in self._pending.values()
            ):
                self._deny("sandbox_entry_conflict", "input target is already reserved")
            pending.relative_path = relative_path
            return SandboxInputReservation(
                pending.token,
                reservation.identity,
                pending.expected_size_bytes,
                relative_path,
            )

    def commit_input_reservation(
        self,
        reservation: SandboxInputReservation,
        *,
        size_bytes: int,
        sha256: str,
    ) -> SandboxInputReservation:
        with self._budget_lock:
            pending = self._pending.get(reservation.token)
            if (
                pending is None
                or pending.identity != reservation.identity
                or not pending.relative_path
                or size_bytes != pending.expected_size_bytes
            ):
                self._deny("sandbox_reservation_invalid", "input reservation is inconsistent")
            target = self.path / pending.relative_path
            self._reject_symlinks(target)
            try:
                state = target.lstat()
            except OSError:
                self._deny(
                    "sandbox_reservation_invalid",
                    "materialized input is unavailable",
                )
            if not stat.S_ISREG(state.st_mode) or state.st_size != size_bytes:
                self._deny(
                    "sandbox_reservation_invalid",
                    "materialized input is inconsistent",
                )
            self._pending.pop(pending.token, None)
            self._input_tokens.pop(reservation.identity, None)
            committed = _CommittedInput(
                reservation.identity,
                pending.relative_path,
                size_bytes,
                sha256,
                state.st_dev,
                state.st_ino,
                state.st_mtime_ns,
            )
            self._committed_inputs[reservation.identity] = committed
            return SandboxInputReservation(
                token="",
                identity=reservation.identity,
                expected_size_bytes=size_bytes,
                relative_path=committed.relative_path,
                committed=True,
                sha256=sha256,
            )

    def release_input_reservation(self, identity: tuple[str, str]) -> None:
        with self._budget_lock:
            self._release_input_locked(identity)

    def rollback_inputs(self, identities: list[tuple[str, str]]) -> None:
        """Remove every pending or completed member of a failed automatic batch."""

        with self._budget_lock:
            for identity in identities:
                self._release_input_locked(identity)
                committed = self._committed_inputs.pop(identity, None)
                if committed is not None:
                    (self.path / committed.relative_path).unlink(missing_ok=True)

    def committed_input(self, identity: tuple[str, str]) -> SandboxInputReservation | None:
        with self._budget_lock:
            committed = self._committed_inputs.get(identity)
            if committed is None:
                return None
            return SandboxInputReservation(
                token="",
                identity=identity,
                expected_size_bytes=committed.size_bytes,
                relative_path=committed.relative_path,
                committed=True,
                sha256=committed.sha256,
            )

    def partition_usage(self) -> dict[str, tuple[int, int]]:
        usage = {"inputs": [0, 0], "work_outputs": [0, 0], "tmp": [0, 0]}
        staging_paths = {
            item.staging_relative_path
            for item in self._pending.values()
            if item.staging_relative_path
        }
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
                if entry.relative_to(self.path).as_posix() in staging_paths:
                    continue
                state = entry.lstat()
                if stat.S_ISLNK(state.st_mode):
                    self._deny("sandbox_symlink_denied", "sandbox contains a symlink")
                if not stat.S_ISREG(state.st_mode):
                    self._deny("sandbox_special_file_denied", "sandbox contains a special file")
                relative = entry.relative_to(self.path)
                top = relative.parts[0]
                partition = (
                    "inputs" if top == "inputs" else "tmp" if top == "tmp" else "work_outputs"
                )
                usage[partition][0] += 1
                usage[partition][1] += state.st_size
        return {key: (value[0], value[1]) for key, value in usage.items()}

    def _reserve_locked(
        self,
        *,
        partition: str,
        expected_size_bytes: int,
        identity: tuple[str, str] | None = None,
        relative_path: str = "",
        replacing_size_bytes: int = 0,
        replacing_file: bool = False,
    ) -> str:
        usage = self.partition_usage()
        pending = list(self._pending.values())
        partition_count = usage[partition][0] + sum(
            1 for item in pending if item.partition == partition
        )
        total_count = sum(item[0] for item in usage.values()) + len(pending)
        if replacing_file:
            partition_count -= 1
            total_count -= 1
        partition_limit = {
            "inputs": self.limits.max_input_files,
            "work_outputs": self.limits.max_work_output_files,
            "tmp": self.limits.max_tmp_files,
        }[partition]
        if partition_count >= partition_limit or total_count >= self.limits.max_files:
            code = (
                "sandbox_input_file_count_exceeded"
                if partition == "inputs"
                else "sandbox_file_count_exceeded"
            )
            self._deny(code, "sandbox file partition is exhausted")
        total_bytes = sum(item[1] for item in usage.values()) + sum(
            item.expected_size_bytes for item in pending
        )
        total_bytes -= replacing_size_bytes
        if total_bytes + expected_size_bytes > self.limits.capacity_bytes:
            self._deny("sandbox_capacity_exceeded", "sandbox capacity is exhausted")
        token = f"sandbox-reservation:{uuid.uuid4()}"
        self._pending[token] = _PendingReservation(
            token=token,
            partition=partition,
            expected_size_bytes=expected_size_bytes,
            identity=identity,
            relative_path=relative_path,
        )
        return token

    def _strict_log_input_path(self, value: object) -> str:
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 240
            or "\\" in value
            or "\x00" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            self._deny("log_evidence_path_invalid", "log evidence path is invalid")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or str(path) != value
            or not path.parts
            or path.parts[0] != "inputs"
            or "." in path.parts
            or ".." in path.parts
            or path.suffix.casefold() != ".log"
        ):
            self._deny(
                "log_evidence_path_invalid",
                "log evidence path must target an inputs LOG",
            )
        return value

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(64 * 1024):
                    digest.update(chunk)
        except OSError as exc:
            raise JobSandboxError(
                "log_evidence_pack_integrity_error",
                "Runtime artifact could not be verified",
            ) from exc
        return digest.hexdigest()

    def _public_runtime_artifact(self, artifact: _RuntimeArtifact) -> SandboxRuntimeArtifact:
        return SandboxRuntimeArtifact(
            relative_path=artifact.relative_path,
            absolute_path=self.path / artifact.relative_path,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            request_digest=artifact.request_digest,
            public_payload=dict(artifact.public_payload),
        )

    def _reserve_named_path(
        self,
        *,
        partition: str,
        relative_path: str,
        expected_size_bytes: int,
        allowed_top_levels: set[str],
    ) -> SandboxReservation:
        path = PurePosixPath(relative_path)
        if (
            path.is_absolute()
            or str(path) != relative_path
            or not path.parts
            or path.parts[0] not in allowed_top_levels
            or "." in path.parts
            or ".." in path.parts
        ):
            self._deny("sandbox_path_invalid", "sandbox reservation path is invalid")
        if expected_size_bytes < 0 or expected_size_bytes > self.limits.max_file_bytes:
            self._deny("sandbox_file_limit_exceeded", "sandbox file exceeds its limit")
        with self._budget_lock:
            target = self.path / relative_path
            self._reject_symlinks(target)
            if target.exists():
                self._deny("sandbox_entry_conflict", "sandbox target already exists")
            token = self._reserve_locked(
                partition=partition,
                expected_size_bytes=expected_size_bytes,
                relative_path=relative_path,
            )
            return SandboxReservation(token, partition, relative_path, expected_size_bytes)

    def _release_input_locked(self, identity: tuple[str, str]) -> None:
        token = self._input_tokens.pop(identity, None)
        if token:
            self._pending.pop(token, None)

    def _reconcile_write_reservations(self) -> None:
        for relative_path, token in list(self._write_reservations.items()):
            pending = self._pending.get(token)
            target = self.path / relative_path
            if (
                pending is not None
                and target.exists()
                and target.stat().st_size <= pending.expected_size_bytes
            ):
                self._pending.pop(token, None)
                self._write_reservations.pop(relative_path, None)

    def usage(self) -> tuple[int, int]:
        usage = self.partition_usage()
        return sum(item[0] for item in usage.values()), sum(item[1] for item in usage.values())

    def _relative_path(self, value: object, *, allow_root: bool, write: bool = False) -> str:
        value = self._sdk_relative_path(value, allow_root=allow_root)
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
        try:
            definition = text_format_for_name(path.name)
        except NonRetryableExecutionError:
            self._deny("sandbox_file_type_denied", "file format is not allowed")
        if write and path.parts[:2] == ("inputs", "readonly"):
            self._deny(
                "sandbox_file_read_only",
                "governed representation inputs are read-only",
            )
        if write and not definition.writable:
            self._deny("sandbox_file_read_only", "this file format is read-only")
        return value

    def _directory_path(self, value: object) -> str:
        value = self._sdk_relative_path(value, allow_root=True)
        if not isinstance(value, str) or not 1 <= len(value) <= 240:
            self._deny("sandbox_path_invalid", "sandbox path is invalid")
        if "\\" in value or "\x00" in value:
            self._deny("sandbox_path_invalid", "sandbox path is invalid")
        if value == ".":
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
        return value

    def _sdk_relative_path(self, value: object, *, allow_root: bool) -> object:
        """Normalize an SDK-resolved in-sandbox absolute path back to its contract path.

        Claude Code resolves built-in file tool paths against ``cwd`` before it
        asks ``can_use_tool``. The model contract remains relative-only, while
        this callback boundary accepts only the exact random Job Sandbox root.
        """
        if not isinstance(value, str) or not PurePosixPath(value).is_absolute():
            return value
        if (
            not 1 <= len(value) <= 4096
            or "\\" in value
            or "\x00" in value
            or str(PurePosixPath(value)) != value
            or "." in PurePosixPath(value).parts
            or ".." in PurePosixPath(value).parts
        ):
            self._deny("sandbox_path_invalid", "sandbox path is invalid")
        root = PurePosixPath(self.path.resolve(strict=True).as_posix())
        try:
            relative = PurePosixPath(value).relative_to(root)
        except ValueError:
            self._deny("sandbox_path_invalid", "sandbox path escaped its Job boundary")
        if not relative.parts:
            if allow_root:
                return "."
            self._deny("sandbox_path_invalid", "sandbox path escaped its Job boundary")
        return relative.as_posix()

    def _glob_pattern(self, value: object) -> None:
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 1024
            or "\\" in value
            or "\x00" in value
            or PurePosixPath(value).is_absolute()
            or "." in PurePosixPath(value).parts
            or ".." in PurePosixPath(value).parts
        ):
            self._deny(
                "sandbox_tool_input_invalid",
                "Glob pattern must be a safe relative pattern",
            )
        allowed = tuple(definition.extension for definition in get_text_format_policy().formats)
        lowered = value.lower()
        if not lowered.endswith(allowed) and not any(
            f"{extension[1:]}}}" in lowered for extension in allowed
        ):
            self._deny(
                "sandbox_tool_input_invalid",
                "Glob pattern must target an allowed text format",
            )

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
        root = self.path.resolve(strict=True)
        current = root
        try:
            parts = target.relative_to(self.path).parts
        except ValueError:
            try:
                parts = target.relative_to(root).parts
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

    def create(
        self,
        job_id: str,
    ) -> JobSandbox:
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
        return JobSandbox(
            job_id=job_id,
            path=path,
            limits=self.limits,
        )

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
        if not 1 <= len(value) <= 128 or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
            for character in value
        ):
            raise JobSandboxError("sandbox_job_id_invalid", "Job id is invalid")
