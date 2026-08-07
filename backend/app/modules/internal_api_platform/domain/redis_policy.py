from __future__ import annotations

from .errors import PolicyViolation

_READ_COMMANDS = {"get", "scan"}


def assert_read_command(command: str) -> None:
    if command.lower() not in _READ_COMMANDS:
        raise PolicyViolation(f"Redis command '{command}' is not read-only")


def enforce_key_namespace(
    key: str,
    *,
    key_prefix: str | None = None,
    key_prefixes: tuple[str, ...] | list[str] | None = None,
) -> str | None:
    """Require an exact GET key to start with one frozen namespace prefix."""

    prefixes = _prefixes(key_prefix=key_prefix, key_prefixes=key_prefixes)
    if not prefixes:
        return None
    matched = next((prefix for prefix in prefixes if key.startswith(prefix)), None)
    if matched is None:
        raise PolicyViolation("Redis key is outside the allowed Workshop namespaces")
    return matched


def enforce_scan_pattern(
    pattern: str,
    *,
    key_prefix: str | None = None,
    key_prefixes: tuple[str, ...] | list[str] | None = None,
    scan_limit: int,
    limit: int,
) -> str:
    if limit < 1 or limit > scan_limit:
        raise PolicyViolation("Redis scan limit exceeds configured maximum")
    if len(pattern) > 1024:
        raise PolicyViolation("Redis scan pattern exceeds configured maximum")
    if pattern in {"", "*"}:
        raise PolicyViolation("Redis scan pattern must be bounded")
    if any(character in pattern for character in ("?", "^", "\\", "{", "}", "(", ")", "|")):
        raise PolicyViolation("Redis scan unsupported wildcard syntax is not allowed")
    prefixes = _prefixes(key_prefix=key_prefix, key_prefixes=key_prefixes)
    if not prefixes:
        if pattern[0] == "*":
            raise PolicyViolation("Redis scan pattern must not start with a wildcard")
        return _escape_literal_brackets(pattern)
    matched = next((prefix for prefix in prefixes if pattern.startswith(prefix)), None)
    if matched is None:
        raise PolicyViolation(
            "Redis scan pattern must start with a complete allowed Workshop namespace"
        )
    first_wildcard = pattern.find("*")
    if first_wildcard < 0:
        first_wildcard = len(pattern)
    if first_wildcard < len(matched):
        raise PolicyViolation("Redis scan wildcard appears before the complete Workshop namespace")
    # Redis SCAN uses glob syntax. The MES namespaces use square brackets as
    # literal key characters, so escape them before handing the pattern to Redis.
    return _escape_literal_brackets(pattern)


def _escape_literal_brackets(pattern: str) -> str:
    return pattern.replace("[", "\\[").replace("]", "\\]")


def _prefixes(
    *,
    key_prefix: str | None,
    key_prefixes: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    values = tuple(str(value) for value in (key_prefixes or ()) if str(value))
    if key_prefix:
        values = (str(key_prefix), *values)
    return tuple(dict.fromkeys(values))
