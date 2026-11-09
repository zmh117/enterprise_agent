"""Bounded transient SVN tool responses. No persistence or logging of payloads."""

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import threading
import time
from collections.abc import Callable
from typing import Any

from app.modules.knowledge.domain.code_answers import MAX_RESPONSE_BYTES, utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import canonical_json, digest

# Administrative names only; raw SVN/source responses retain the 512 KiB limit.
MAX_DIRECTORY_PREVIEW_BYTES = 2 * 1024 * 1024


def directory_preview(payload: dict[str, Any]) -> bool:
    return (
        set(payload) == {"revision", "repository_uuid", "directories", "files", "registration_hash"}
        and type(payload["revision"]) is int
        and all(isinstance(payload[k], str) for k in ("repository_uuid", "registration_hash"))
        and all(
            isinstance(payload[k], list) and all(isinstance(p, str) for p in payload[k])
            for k in ("directories", "files")
        )
    )


@dataclass(frozen=True, repr=False)
class _Result:
    payload: bytes
    result_hash: str
    expires_at: float


class CodeResultBuffer:
    def __init__(
        self,
        *,
        capacity: int = 8 * 1024 * 1024,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if not 1 <= capacity <= 8 * 1024 * 1024:
            raise ValueError("Invalid transient buffer capacity")
        self.capacity, self.clock, self.wall_clock = capacity, clock, wall_clock
        self._lock = threading.RLock()
        self._items: dict[tuple[str, int], _Result] = {}
        self._bytes = 0

    def _expire(self) -> None:
        for key, item in list(self._items.items()):
            if item.expires_at <= self.clock():
                self._bytes -= len(item.payload)
                del self._items[key]

    def put(
        self,
        operation_id: str,
        claim: int,
        payload: dict[str, Any],
        *,
        deadline_at: Any,
        is_directory_preview: bool = False,
    ) -> str:
        if not isinstance(payload, dict) or type(claim) is not int or claim < 1:
            raise CodeKnowledgeError("CODE_RESULT_INVALID")
        if is_directory_preview and not directory_preview(payload):
            raise CodeKnowledgeError("CODE_RESULT_INVALID")
        encoded = canonical_json(payload).encode()
        limit = MAX_DIRECTORY_PREVIEW_BYTES if is_directory_preview else MAX_RESPONSE_BYTES
        if len(encoded) > limit:
            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_TOO_LARGE")
        remaining = min(60.0, (utc_time(deadline_at) - self.wall_clock()).total_seconds())
        if remaining <= 0:
            raise CodeKnowledgeError("CODE_OPERATION_EXPIRED")
        result_hash = digest(payload)
        key = (operation_id, claim)
        with self._lock:
            self._expire()
            existing = self._items.get(key)
            if existing:
                if existing.result_hash != result_hash:
                    raise CodeKnowledgeError("CODE_HISTORY_RESULT_CHANGED")
                return result_hash  # A replay must not extend its lifetime.
            if self._bytes + len(encoded) > self.capacity:
                raise CodeKnowledgeError("CODE_RESULT_BUFFER_FULL")
            self._items[key] = _Result(encoded, result_hash, self.clock() + remaining)
            self._bytes += len(encoded)
        return result_hash

    def get(self, operation_id: str, claim: int, *, expected_hash: str) -> dict[str, Any]:
        with self._lock:
            self._expire()
            item = self._items.get((operation_id, claim))
            if item is None:
                raise CodeKnowledgeError("CODE_RESULT_EXPIRED")
            if item.result_hash != expected_hash:
                raise CodeKnowledgeError("CODE_HISTORY_RESULT_CHANGED")
            # Decode into an independent response, never return mutable cache state.
            return dict(json.loads(item.payload))

    def discard(self, operation_id: str) -> None:
        with self._lock:
            for key in [key for key in self._items if key[0] == operation_id]:
                self._bytes -= len(self._items.pop(key).payload)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0
