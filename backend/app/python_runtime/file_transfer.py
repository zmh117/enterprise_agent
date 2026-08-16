from __future__ import annotations

import codecs
import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Protocol


FILE_TRANSFER_META_KEY = "enterprise-agent/file-transfer"
FILE_TRANSFER_PROTOCOL = "enterprise-agent.file-transfer/v1"
_MAX_RELATIVE_PATH_CHARS = 240
_IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")


class FileTransferBoundaryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FileTransferContext:
    job_id: str
    workspace_path: Path
    principal_token: str


@dataclass(frozen=True)
class FileUploadReceipt:
    file_id: str
    version_id: str
    size_bytes: int
    sha256: str
    status: str
    delivery_id: str
    delivery_status: str


class FileTransferPort(Protocol):
    def download(
        self,
        *,
        transfer_id: str,
        job_id: str,
        principal_token: str,
    ) -> Iterable[bytes]: ...

    def upload(
        self,
        *,
        commit_id: str,
        job_id: str,
        principal_token: str,
        content: Iterable[bytes],
    ) -> FileUploadReceipt: ...


def _mapping(value: object, *, code: str = "file_transfer_control_invalid") -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise FileTransferBoundaryError(code, "file transfer control must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise FileTransferBoundaryError(
            "file_transfer_control_invalid",
            "file transfer control contains unknown or missing fields",
        )


def _identifier(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or value[0] not in _IDENTIFIER_CHARS
        or any(character not in _IDENTIFIER_CHARS for character in value)
    ):
        raise FileTransferBoundaryError(
            "file_transfer_control_invalid",
            f"{field} must be an opaque identifier",
        )
    return value


def _relative_txt_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= _MAX_RELATIVE_PATH_CHARS
        or "\\" in value
        or "\x00" in value
        or not value.lower().endswith(".txt")
    ):
        raise FileTransferBoundaryError(
            "file_transfer_path_invalid",
            "relative_path must be a bounded TXT path",
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or "." in path.parts
        or not path.parts
        or path.parts[0] not in {"inputs", "work", "outputs", "tmp"}
    ):
        raise FileTransferBoundaryError(
            "file_transfer_path_invalid",
            "relative_path must remain inside the Job Sandbox",
        )
    return value


def _size(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FileTransferBoundaryError(
            "file_transfer_control_invalid",
            f"{field} must be a non-negative integer",
        )
    return value


def _sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FileTransferBoundaryError(
            "file_transfer_control_invalid",
            f"{field} must be a lowercase SHA-256 digest",
        )
    return value


def parse_file_transfer_control(result: object) -> dict[str, object]:
    envelope = _mapping(result)
    meta = _mapping(envelope.get("_meta"))
    control = _mapping(meta.get(FILE_TRANSFER_META_KEY))
    if control.get("protocol") != FILE_TRANSFER_PROTOCOL:
        raise FileTransferBoundaryError(
            "file_transfer_protocol_unsupported",
            "unsupported file transfer protocol",
        )
    if control.get("action") == "MATERIALIZE":
        _exact_keys(
            control,
            {
                "protocol",
                "action",
                "transfer_id",
                "sandbox_entry_handle",
                "relative_path",
                "expected_size_bytes",
                "expected_sha256",
            },
        )
        return {
            "protocol": FILE_TRANSFER_PROTOCOL,
            "action": "MATERIALIZE",
            "transfer_id": _identifier(control.get("transfer_id"), "transfer_id"),
            "sandbox_entry_handle": _identifier(
                control.get("sandbox_entry_handle"), "sandbox_entry_handle"
            ),
            "relative_path": _relative_txt_path(control.get("relative_path")),
            "expected_size_bytes": _size(control.get("expected_size_bytes"), "expected_size_bytes"),
            "expected_sha256": _sha256(control.get("expected_sha256"), "expected_sha256"),
        }
    if control.get("action") == "UPLOAD_COMMIT":
        _exact_keys(
            control,
            {"protocol", "action", "commit_id", "sandbox_entry_handle"},
        )
        return {
            "protocol": FILE_TRANSFER_PROTOCOL,
            "action": "UPLOAD_COMMIT",
            "commit_id": _identifier(control.get("commit_id"), "commit_id"),
            "sandbox_entry_handle": _identifier(
                control.get("sandbox_entry_handle"), "sandbox_entry_handle"
            ),
        }
    raise FileTransferBoundaryError(
        "file_transfer_action_unsupported",
        "unsupported file transfer action",
    )


def _sandbox_path(workspace: Path, relative_path: str) -> Path:
    root = workspace.resolve()
    target = root / relative_path
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise FileTransferBoundaryError(
            "file_transfer_path_invalid",
            "file transfer target escaped the Job Sandbox",
        ) from exc
    if target == root:
        raise FileTransferBoundaryError(
            "file_transfer_path_invalid",
            "file transfer target escaped the Job Sandbox",
        )
    return target


def _reject_symlinks(workspace: Path, target: Path) -> None:
    current = workspace.resolve()
    for part in target.relative_to(current).parts:
        current /= part
        if current.exists() or current.is_symlink():
            state = current.lstat()
            if stat.S_ISLNK(state.st_mode):
                raise FileTransferBoundaryError(
                    "file_transfer_symlink_denied",
                    "file transfer path contains a symbolic link",
                )
            if not (stat.S_ISDIR(state.st_mode) or stat.S_ISREG(state.st_mode)):
                raise FileTransferBoundaryError(
                    "file_transfer_entry_invalid",
                    "file transfer path contains a special file",
                )


class FileTransferCoordinator:
    def __init__(self, port: FileTransferPort) -> None:
        self._port = port
        self._entries: dict[str, tuple[str, Path]] = {}

    def select_sandbox_output(
        self,
        *,
        relative_path: str,
        context: FileTransferContext,
        maximum_size_bytes: int = 15 * 1024 * 1024,
    ) -> dict[str, object]:
        safe_path = _relative_txt_path(relative_path)
        if PurePosixPath(safe_path).parts[0] not in {"work", "outputs"}:
            raise FileTransferBoundaryError(
                "file_transfer_path_invalid",
                "only work or outputs TXT files can be selected",
            )
        target = _sandbox_path(context.workspace_path, safe_path)
        _reject_symlinks(context.workspace_path, target)
        state = target.lstat()
        if not stat.S_ISREG(state.st_mode):
            raise FileTransferBoundaryError(
                "file_transfer_entry_invalid",
                "sandbox entry must reference a regular file",
            )
        if state.st_size > maximum_size_bytes:
            raise FileTransferBoundaryError(
                "file_transfer_size_mismatch",
                "sandbox output exceeds the TXT size limit",
            )
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with target.open("rb") as source:
                while chunk := source.read(64 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > maximum_size_bytes:
                        raise FileTransferBoundaryError(
                            "file_transfer_size_mismatch",
                            "sandbox output exceeds the TXT size limit",
                        )
                    digest.update(chunk)
                    decoder.decode(chunk, final=False)
                decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise FileTransferBoundaryError(
                "file_transfer_encoding_invalid",
                "sandbox output must be valid UTF-8",
            ) from exc
        handle = f"sandbox-entry:{uuid.uuid4()}"
        self._entries[handle] = (safe_path, target)
        return {
            "action": "SELECTED",
            "sandbox_entry_handle": handle,
            "relative_path": safe_path,
            "size_bytes": size_bytes,
            "sha256": digest.hexdigest(),
        }

    def register_sandbox_entry(
        self,
        *,
        sandbox_entry_handle: str,
        relative_path: str,
        context: FileTransferContext,
    ) -> None:
        handle = _identifier(sandbox_entry_handle, "sandbox_entry_handle")
        if handle in self._entries:
            raise FileTransferBoundaryError(
                "file_transfer_handle_conflict",
                "sandbox entry handle is already bound",
            )
        safe_path = _relative_txt_path(relative_path)
        target = _sandbox_path(context.workspace_path, safe_path)
        _reject_symlinks(context.workspace_path, target)
        state = target.lstat()
        if not stat.S_ISREG(state.st_mode):
            raise FileTransferBoundaryError(
                "file_transfer_entry_invalid",
                "sandbox entry must reference a regular file",
            )
        self._entries[handle] = (safe_path, target)

    def process_mcp_control_result(
        self,
        result: object,
        context: FileTransferContext,
    ) -> dict[str, object]:
        control = parse_file_transfer_control(result)
        if control["action"] == "MATERIALIZE":
            return self._materialize(control, context)
        return self._upload(control, context)

    def _materialize(
        self,
        control: Mapping[str, object],
        context: FileTransferContext,
    ) -> dict[str, object]:
        handle = str(control["sandbox_entry_handle"])
        if handle in self._entries:
            raise FileTransferBoundaryError(
                "file_transfer_handle_conflict",
                "sandbox entry handle is already bound",
            )
        relative_path = str(control["relative_path"])
        target = _sandbox_path(context.workspace_path, relative_path)
        _reject_symlinks(context.workspace_path, target)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.sha256()
        size_bytes = 0
        expected_size = _size(control["expected_size_bytes"], "expected_size_bytes")
        try:
            with target.open("xb") as output:
                os.chmod(target, 0o600)
                for chunk in self._port.download(
                    transfer_id=str(control["transfer_id"]),
                    job_id=context.job_id,
                    principal_token=context.principal_token,
                ):
                    if not isinstance(chunk, bytes):
                        raise FileTransferBoundaryError(
                            "file_transfer_chunk_invalid",
                            "download yielded a non-bytes chunk",
                        )
                    size_bytes += len(chunk)
                    if size_bytes > expected_size:
                        raise FileTransferBoundaryError(
                            "file_transfer_size_mismatch",
                            "download exceeded the expected size",
                        )
                    digest.update(chunk)
                    output.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        actual_sha256 = digest.hexdigest()
        if size_bytes != expected_size or actual_sha256 != str(control["expected_sha256"]):
            target.unlink(missing_ok=True)
            raise FileTransferBoundaryError(
                "file_transfer_integrity_mismatch",
                "download did not match the frozen file version",
            )
        self._entries[handle] = (relative_path, target)
        return {
            "action": "MATERIALIZED",
            "sandbox_entry_handle": handle,
            "relative_path": relative_path,
            "size_bytes": size_bytes,
            "sha256": actual_sha256,
        }

    def _upload(
        self,
        control: Mapping[str, object],
        context: FileTransferContext,
    ) -> dict[str, object]:
        handle = str(control["sandbox_entry_handle"])
        entry = self._entries.get(handle)
        if entry is None:
            raise FileTransferBoundaryError(
                "file_transfer_handle_unknown",
                "sandbox entry handle is not materialized",
            )
        _relative_path, target = entry
        _reject_symlinks(context.workspace_path, target)
        state = target.lstat()
        if not stat.S_ISREG(state.st_mode):
            raise FileTransferBoundaryError(
                "file_transfer_entry_invalid",
                "sandbox entry must reference a regular file",
            )
        digest = hashlib.sha256()
        size_bytes = 0

        def content() -> Iterable[bytes]:
            nonlocal size_bytes
            with target.open("rb") as source:
                while chunk := source.read(64 * 1024):
                    size_bytes += len(chunk)
                    digest.update(chunk)
                    yield chunk

        receipt = self._port.upload(
            commit_id=str(control["commit_id"]),
            job_id=context.job_id,
            principal_token=context.principal_token,
            content=content(),
        )
        actual_sha256 = digest.hexdigest()
        if (
            size_bytes != state.st_size
            or receipt.size_bytes != size_bytes
            or receipt.sha256 != actual_sha256
        ):
            raise FileTransferBoundaryError(
                "file_transfer_receipt_mismatch",
                "upload receipt did not match the local sandbox entry",
            )
        _identifier(receipt.version_id, "version_id")
        _identifier(receipt.file_id, "file_id")
        _sha256(receipt.sha256, "sha256")
        if receipt.status not in {"COMMITTED", "CONFLICT"}:
            raise FileTransferBoundaryError(
                "file_transfer_receipt_invalid",
                "upload receipt contained an invalid commit status",
            )
        valid_delivery_statuses = {
            "NOT_REQUESTED",
            "PENDING",
            "RUNNING",
            "RETRY_WAIT",
            "SUCCEEDED",
            "FAILED",
            "DEAD",
            "SKIPPED",
        }
        if receipt.delivery_status not in valid_delivery_statuses or bool(
            receipt.delivery_id
        ) == (receipt.delivery_status == "NOT_REQUESTED"):
            raise FileTransferBoundaryError(
                "file_transfer_receipt_invalid",
                "upload receipt contained an invalid Delivery binding",
            )
        if receipt.delivery_id:
            _identifier(receipt.delivery_id, "delivery_id")
        return {
            "action": "COMMITTED",
            "sandbox_entry_handle": handle,
            "commit_id": str(control["commit_id"]),
            "file_id": receipt.file_id,
            "version_id": receipt.version_id,
            "size_bytes": size_bytes,
            "sha256": actual_sha256,
            "status": receipt.status,
            "delivery_id": receipt.delivery_id,
            "delivery_status": receipt.delivery_status,
        }
