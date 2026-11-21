"""Collect only main-session assistant Markdown. SDK result messages may repeat the last turn."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.python_runtime.sdk_event_normalizer import extract_text_blocks, sdk_message_type, sdk_value


def observe_partial(browser: BrowserAnswer | None, message: Any) -> bool:
    if browser is None:
        return False
    browser.observe(message)
    return sdk_message_type(message) in {"streamevent", "stream_event"}


class BrowserAnswer:
    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit
        self.session = ""
        self.current = ""
        self.blocks: set[int] = set()
        self.partial: dict[str, list[str]] = {}
        self.complete: dict[str, list[str]] = {}
        self.seen: set[str] = set()
        self.order: list[str] = []
        self.last_visible = ""
        self.pending = ""
        self.last_flush = 0.0

    def is_main_result(self, message: Any) -> bool:
        return (
            bool(self.session)
            and sdk_message_type(message) == "result"
            and sdk_value(message, "session_id") == self.session
            and sdk_value(message, "parent_tool_use_id") is None
        )

    def observe(self, message: Any) -> None:
        kind = sdk_message_type(message)
        if kind == "system" and sdk_value(message, "subtype") == "init" and not self.session:
            self.session = str((sdk_value(message, "data") or {}).get("session_id") or "")
            return
        if not self.session or sdk_value(message, "session_id") != self.session:
            return
        if sdk_value(message, "parent_tool_use_id") is not None:
            return
        if kind == "assistant" and not sdk_value(message, "error"):
            mid = sdk_value(message, "message_id")
            uid = sdk_value(message, "uuid")
            if mid and uid and uid not in self.seen:
                self.seen.add(uid)
                self._register(mid)
                self.complete.setdefault(mid, []).extend(extract_text_blocks(message))
            return
        if kind not in {"streamevent", "stream_event"}:
            return
        event = sdk_value(message, "event") or {}
        tag = event.get("type")
        index = event.get("index")
        if tag == "message_start":
            meta = event.get("message") or {}
            self.current = meta.get("id", "") if meta.get("role") == "assistant" else ""
            self.blocks.clear()
            if self.current:
                self._register(self.current)
        elif tag == "content_block_start" and self.current:
            block = event.get("content_block") or {}
            if isinstance(index, int) and block.get("type") == "text":
                self.blocks.add(index)
                self._append(block.get("text"))
        elif tag == "content_block_delta" and self.current and index in self.blocks:
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                self._append(delta.get("text"))
        elif tag == "content_block_stop":
            self.blocks.discard(index)
            self.flush()
        elif tag == "message_stop":
            self.flush()
            self.current = ""
            self.blocks.clear()

    def _register(self, mid: str) -> None:
        if mid not in self.partial:
            self.order.append(mid)
            self.partial[mid] = []

    def _append(self, text: Any) -> None:
        if not isinstance(text, str) or not text:
            return
        self.partial[self.current].append(text)
        if self.last_visible and self.last_visible != self.current:
            self.pending += "\n\n"
        self.last_visible = self.current
        self.pending += text
        if len(self.pending) >= 1024 or time.monotonic() - self.last_flush >= 0.06:
            self.flush()

    def flush(self) -> None:
        while self.pending:
            # Remain below the wire limit even for escaped or non-BMP text.
            batch, self.pending = self.pending[:4096], self.pending[4096:]
            self.emit(batch)
        self.last_flush = time.monotonic()

    def final(self, fallback: str) -> str:
        self.flush()
        turns = ["".join(self.complete.get(mid) or self.partial[mid]) for mid in self.order]
        return "\n\n".join(turn for turn in turns if turn) or fallback
