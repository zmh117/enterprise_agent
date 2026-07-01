from __future__ import annotations

from .errors import PolicyViolation

_READ_COMMANDS = {"get", "scan"}


def assert_read_command(command: str) -> None:
    if command.lower() not in _READ_COMMANDS:
        raise PolicyViolation(f"Redis command '{command}' is not read-only")


def enforce_key_namespace(key: str, *, key_prefix: str | None) -> None:
    """A workshop-scoped key must live inside the workshop key prefix."""

    if key_prefix and not key.startswith(key_prefix):
        raise PolicyViolation(f"Redis key is outside the allowed workshop namespace '{key_prefix}'")


def enforce_scan_pattern(
    pattern: str, *, key_prefix: str | None, scan_limit: int, limit: int
) -> None:
    if limit < 1 or limit > scan_limit:
        raise PolicyViolation("Redis scan limit exceeds configured maximum")
    if pattern in {"", "*"}:
        raise PolicyViolation("Redis scan pattern must be bounded")
    if key_prefix and not pattern.startswith(key_prefix):
        raise PolicyViolation(
            f"Redis scan pattern is outside the allowed workshop namespace '{key_prefix}'"
        )
