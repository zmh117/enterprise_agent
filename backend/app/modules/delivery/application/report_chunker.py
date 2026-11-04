from __future__ import annotations

from typing import Any

from app.shared.exceptions import NonRetryableExecutionError


PARAGRAPH_CHUNKING = "paragraph-v1"
FIXED_CHUNKING = "fixed-v1"


class ReportChunker:
    def __init__(self, max_chars: int = 3500, *, version: str = PARAGRAPH_CHUNKING) -> None:
        self.max_chars = max(200, max_chars)
        if version not in {PARAGRAPH_CHUNKING, FIXED_CHUNKING}:
            raise _invalid_plan()
        self.version = version

    def policy(self) -> dict[str, Any]:
        return {"version": self.version, "max_chars": self.max_chars}

    @classmethod
    def from_policy(cls, policy: object) -> ReportChunker:
        if not isinstance(policy, dict) or set(policy) != {"version", "max_chars"}:
            raise _invalid_plan()
        size = policy["max_chars"]
        if type(size) is not int or size < 200 or not isinstance(policy["version"], str):
            raise _invalid_plan()
        return cls(size, version=policy["version"])

    def chunks(self, text: str) -> list[str]:
        return self._chunks(text, self.max_chars)

    def _chunks(self, text: str, limit: int) -> list[str]:
        if len(text) <= limit:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + limit, len(text))
            if self.version == PARAGRAPH_CHUNKING and end < len(text):
                end = _boundary(text, start, end)
            chunks.append(text[start:end])
            start = end
        return chunks

    def titled_chunks(self, *, title: str, text: str) -> list[tuple[str, str]]:
        chunks = self.chunks(text)
        if len(chunks) == 1:
            return [(title, text)]
        if self.version == PARAGRAPH_CHUNKING:
            # The count may gain a digit when reserving prefix space. Never reduce
            # the reservation, so the bounded fixed point cannot oscillate.
            reserved = 0
            while (needed := len(f"part {len(chunks)}/{len(chunks)}\n\n")) > reserved:
                reserved = needed
                chunks = self._chunks(text, self.max_chars - reserved)
        total = len(chunks)
        return [
            (f"{title} part {index + 1}/{total}", f"part {index + 1}/{total}\n\n{chunk}")
            for index, chunk in enumerate(chunks)
        ]


def _boundary(text: str, start: int, end: int) -> int:
    for separators in (("\r\n\r\n", "\n\n"), ("\r\n", "\n")):
        cuts = [
            position + len(separator)
            for separator in separators
            if (position := text.rfind(separator, start + 1, end)) >= 0
        ]
        if cuts:
            return max(cuts)
    return end


def _invalid_plan() -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Delivery text chunking plan is invalid",
        safe_message="投递分片计划无效，不能更改已发送内容",
        error_code="delivery_chunk_plan_invalid",
    )
