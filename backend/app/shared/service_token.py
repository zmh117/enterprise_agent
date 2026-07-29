from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path


_MAX_FILE_BYTES = 16 * 1024
_MIN_TOKEN_CHARS = 32
_MAX_TOKEN_CHARS = 4096


class ServiceTokenSet:
    """In-memory current/next service tokens with fixed-length digest checks."""

    __slots__ = ("_current", "_current_digest", "_next_digest", "_next_enabled")

    def __init__(self, *, current: str, next_token: str = "") -> None:
        current = _validate_token(current, field="current")
        next_token = (
            _validate_token(next_token, field="next")
            if next_token
            else ""
        )
        current_digest = _digest(current)
        next_digest = _digest(next_token) if next_token else bytes(32)
        if next_token and hmac.compare_digest(current_digest, next_digest):
            raise RuntimeError("Service Token current and next must be different")
        self._current = current
        self._current_digest = current_digest
        self._next_digest = next_digest
        self._next_enabled = bool(next_token)

    @classmethod
    def from_file(
        cls,
        path: str,
        *,
        required: bool,
    ) -> ServiceTokenSet | None:
        configured_path = path.strip()
        if not configured_path:
            if required:
                raise RuntimeError(
                    "INTERNAL_API_AUTH_TOKEN_FILE is required for this runtime"
                )
            return None
        token_path = Path(configured_path)
        try:
            if token_path.stat().st_size > _MAX_FILE_BYTES:
                raise RuntimeError("Internal API service Token file is too large")
            payload = json.loads(token_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Configured Internal API service Token file was not found"
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Configured Internal API service Token file is unreadable or invalid"
            ) from exc
        if not isinstance(payload, dict) or set(payload) - {"current", "next"}:
            raise RuntimeError(
                "Internal API service Token file must contain only current and optional next"
            )
        return cls(
            current=str(payload.get("current") or ""),
            next_token=str(payload.get("next") or ""),
        )

    @property
    def outbound_token(self) -> str:
        return self._current

    @property
    def rotation_enabled(self) -> bool:
        return self._next_enabled

    def matches(self, supplied: str) -> bool:
        supplied_digest = _digest(supplied)
        current_matches = hmac.compare_digest(
            supplied_digest,
            self._current_digest,
        )
        next_matches = hmac.compare_digest(
            supplied_digest,
            self._next_digest,
        )
        return current_matches or (self._next_enabled and next_matches)

    def matches_bearer_header(self, header: str) -> bool:
        scheme, separator, supplied = header.strip().partition(" ")
        if not separator or scheme.lower() != "bearer" or not supplied:
            supplied = ""
        return self.matches(supplied)

    def __repr__(self) -> str:
        return (
            "<ServiceTokenSet current=configured "
            f"next={'configured' if self._next_enabled else 'disabled'}>"
        )


def _validate_token(value: str, *, field: str) -> str:
    if (
        not _MIN_TOKEN_CHARS <= len(value) <= _MAX_TOKEN_CHARS
        or value != value.strip()
        or any(char.isspace() or ord(char) < 33 for char in value)
    ):
        raise RuntimeError(
            f"Internal API service Token {field} must be "
            f"{_MIN_TOKEN_CHARS}-{_MAX_TOKEN_CHARS} non-whitespace characters"
        )
    return value


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()
