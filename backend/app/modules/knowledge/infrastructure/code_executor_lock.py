"""Local stop proof retained by SVN children when their Worker dies.

Workers use Linux containers on one Docker host with the same checkout bind.
DB leases govern admission; inherited locks prove local I/O has actually stopped.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import stat
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

_DESCRIPTORS: ContextVar[tuple[int, ...]] = ContextVar("code_execution_descriptors", default=())


def inherited_execution_fds() -> tuple[int, ...]:
    return _DESCRIPTORS.get()


class ExecutorLock:
    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    def bind(self, row: dict[str, Any]) -> None:
        value = {key: row[key] for key in ("id", "owner_instance_id", "claim_version")}
        encoded = json.dumps(value, sort_keys=True).encode()
        if len(encoded) > 1024:
            raise CodeKnowledgeError("CODE_EXECUTOR_PROOF_INVALID")
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        os.ftruncate(self.descriptor, 0)
        os.write(self.descriptor, encoded)
        os.fsync(self.descriptor)

    def proves_stopped(self, row: dict[str, Any]) -> bool:
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        raw = os.read(self.descriptor, 1025)
        try:
            return len(raw) <= 1024 and json.loads(raw) == {
                key: row[key] for key in ("id", "owner_instance_id", "claim_version")
            }
        except ValueError:
            return False


@contextmanager
def execution_lock(root: Path, namespace: str, identifier: str) -> Iterator[ExecutorLock]:
    if namespace not in {"svn", "index"} or root.resolve(strict=True) != root:
        raise CodeKnowledgeError("CODE_EXECUTOR_PROOF_INVALID")
    directory = root / ".executor-locks"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.resolve(strict=True) != directory:
        raise CodeKnowledgeError("CODE_EXECUTOR_PROOF_INVALID")
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    token = None
    try:
        name = namespace + "-" + sha256(identifier.encode()).hexdigest()
        descriptor = os.open(
            name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, mode=0o600, dir_fd=parent
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > 1024:
            raise CodeKnowledgeError("CODE_EXECUTOR_PROOF_INVALID")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CodeKnowledgeError("CODE_EXECUTOR_STILL_RUNNING") from None
        token = _DESCRIPTORS.set((*_DESCRIPTORS.get(), descriptor))
        yield ExecutorLock(descriptor)
    finally:
        if token is not None:
            _DESCRIPTORS.reset(token)
        # Close, never LOCK_UN: an inherited descriptor retains the same lock
        # until the child exits even if its parent dies during cleanup.
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)
