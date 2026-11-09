"""Safe bounded reads beneath an authorized directory; no collection or snapshots."""

import os
from pathlib import Path, PurePosixPath
import re
import stat
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

SENSITIVE_NAME = re.compile(
    r"(?:^|[._-])(?:env|secret|credentials?|password|token|cookie|config)(?:[._-]|$)", re.I
)
# Conservative admission: exclude the whole file, do not redact while retaining a false hash.
SENSITIVE_CONTENT = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b|"
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_+/=.-]{12,}|"
    r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|cookie)\s*['\"]?\s*[:=]\s*['\"][^'\"\r\n]{3,}['\"]|"
    r"[a-z]+://[^\s/:]+:[^\s/@]+@",
    re.I,
)


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or "\0" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise CodeKnowledgeError("code_source_path_invalid")
    return path.as_posix()


def _read_beneath(root: Path, relative: str, limit: int) -> bytes:
    """Open every component relative to a held directory FD, disallowing symlink races."""
    parts = relative_path(relative).split("/")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise CodeKnowledgeError("code_source_file_size_or_type")
            with os.fdopen(os.dup(file_fd), "rb") as stream:
                data = stream.read(limit + 1)
            after = os.fstat(file_fd)
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or len(data) > limit:
                raise CodeKnowledgeError("code_source_changed")
            return data
        finally:
            os.close(file_fd)
    except OSError:
        raise CodeKnowledgeError("code_source_unreadable_or_link") from None
    finally:
        os.close(descriptor)
