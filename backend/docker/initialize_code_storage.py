"""Prepare only the configured code-storage directories; never inspect their files."""

import errno
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
from uuid import uuid4


class InitializationError(Exception):
    pass


def validate_state_root(value: str) -> None:
    if not value or any(ord(char) < 32 for char in value):
        raise InitializationError("code_directory_path_invalid")
    path_type = PureWindowsPath if PureWindowsPath(value).drive else PurePosixPath
    path = path_type(value)
    if len(path.parts) < 3 or ".." in path.parts:
        raise InitializationError("code_directory_path_invalid")


def open_directories(checkout: Path, state: Path) -> list[tuple[int, int, int, int]]:
    """Hold no-follow descriptors, including parents, before modifying metadata."""
    opened: list[tuple[int, int, int, int]] = []

    def directory(path, uid, gid, mode, parent=None):
        if parent is not None:
            try:
                os.mkdir(path, mode=0o755, dir_fd=parent)
            except FileExistsError:
                pass
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        opened.append((fd, uid, gid, mode))
        return fd

    try:
        source = directory(checkout, 10003, 10010, 0o750)
        root = directory(state, 10003, 10003, 0o755)
        a, b = os.fstat(source), os.fstat(root)
        if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino):
            raise InitializationError("code_directory_overlap")
        directory("configuration", 10003, 10003, 0o755, root)
        client = directory("client", 10003, 10003, 0o755, root)
        directory("trusted-ca", 10003, 10003, 0o755, client)
        return opened
    except BaseException:
        for fd, *_ in opened:
            os.close(fd)
        raise


def as_user(uid: int, gid: int, action) -> None:
    child = os.fork()
    if child == 0:
        try:
            os.setgroups([10010])
            os.setgid(gid)
            os.setuid(uid)
            os.umask(0o027)
            action()
        except BaseException:
            os._exit(1)
        os._exit(0)
    _, status = os.waitpid(child, 0)
    if status != 0:
        raise InitializationError("code_directory_access_probe_failed")


def probe_access(checkout: Path, state: Path) -> None:
    # O_EXCL prevents collisions. Only this invocation's synthetic probe is removed.
    probe = checkout / (".ea-storage-check-" + uuid4().hex)

    def write():
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        os.close(fd)
        for path in (state, state / "configuration", state / "client/trusted-ca"):
            if not os.access(path, os.R_OK | os.X_OK):
                raise InitializationError("code_directory_access_probe_failed")

    def read():
        fd = os.open(probe, os.O_RDONLY | os.O_NOFOLLOW)
        os.close(fd)

    try:
        as_user(10003, 10010, write)
        as_user(10002, 10002, read)
    finally:
        probe.unlink(missing_ok=True)


def initialize(checkout: Path, state: Path) -> str:
    opened = open_directories(checkout, state)
    translated = False
    try:
        for fd, uid, gid, mode in opened:
            info = os.fstat(fd)
            if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode):
                continue
            try:
                os.fchown(fd, uid, gid)
                os.fchmod(fd, mode)
            except OSError as exc:
                # Desktop shared filesystems can translate metadata. Actual access
                # is mandatory below; unrelated IO errors are never downgraded.
                if exc.errno not in {errno.EPERM, errno.EOPNOTSUPP}:
                    raise
            info = os.fstat(fd)
            translated |= (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode)
        probe_access(checkout, state)
    finally:
        for fd, *_ in opened:
            os.close(fd)
    return "translated_access_verified" if translated else "posix_access_verified"


def main() -> int:
    try:
        validate_state_root(os.environ.get("CODE_INIT_STATE_HOST_PATH", ""))
        mode = initialize(Path("/storage/checkout"), Path("/storage/state"))
    except (OSError, InitializationError) as exc:
        code = str(exc) if isinstance(exc, InitializationError) else "code_directory_init_failed"
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ready", "permissions": mode}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
