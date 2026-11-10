"""Durable working-copy identity, with a separate per-process replacement guard."""

from contextlib import contextmanager
from collections.abc import Iterator
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest

MARKER = "enterprise-agent-identity"
PREFIX = "checkout-v1:"
KEY = re.compile(r"checkout-v1:[a-f0-9]{32}\n?")


def local_identity(directory: Path) -> tuple[int, int]:
    try:
        if not directory.is_absolute() or directory.resolve(strict=True) != directory:
            raise ValueError
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError
        return info.st_dev, info.st_ino
    except PermissionError:
        raise CodeKnowledgeError("CODE_CHECKOUT_PERMISSION_DENIED") from None
    except (OSError, ValueError):
        raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED") from None


@contextmanager
def _metadata_directory(directory: Path) -> Iterator[int]:
    root = metadata = None
    try:
        local_identity(directory)
        root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.open(".svn", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        yield metadata
    except PermissionError:
        raise CodeKnowledgeError("CODE_CHECKOUT_PERMISSION_DENIED") from None
    except OSError:
        raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED") from None
    finally:
        if metadata is not None:
            os.close(metadata)
        if root is not None:
            os.close(root)


def _read(parent: int) -> str:
    descriptor = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 80:
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
        value = os.read(descriptor, 81).decode("ascii")
        if not KEY.fullmatch(value):
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
        return value.rstrip("\n")
    except UnicodeError:
        raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED") from None
    finally:
        os.close(descriptor)


def persistent_identity(directory: Path, *, create: bool = False) -> str:
    """Creation is restricted to a caller already holding exclusive ownership."""
    before = local_identity(directory)
    with _metadata_directory(directory) as parent:
        try:
            value = _read(parent)
        except FileNotFoundError:
            if not create:
                raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED") from None
            value = PREFIX + uuid4().hex
            temporary = ".identity-" + uuid4().hex
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o644,
                dir_fd=parent,
            )
            try:
                os.write(descriptor, (value + "\n").encode())
                # The caller retains umask 077 for credentials; only this public
                # identity marker must be readable by the shared source group.
                os.fchmod(descriptor, 0o640)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                # No replacement: another creator or a planted marker must survive.
                os.link(
                    temporary, MARKER, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                )
            finally:
                os.unlink(temporary, dir_fd=parent)
            os.fsync(parent)
            value = _read(parent)
    if local_identity(directory) != before:
        raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
    return value


class CheckoutIdentity:
    def __init__(self, directory: Path, key: str) -> None:
        self.directory, self.key = directory, key
        self.local = local_identity(directory)
        self.check()

    def check(self) -> None:
        if local_identity(self.directory) != self.local:
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
        # Legacy registrations remain strictly checked until explicit maintenance.
        actual = (
            persistent_identity(self.directory)
            if self.key.startswith(PREFIX)
            else digest(list(self.local))
        )
        if actual != self.key:
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
