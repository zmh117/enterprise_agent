"""Fixed, bounded database value decoding. No provider, configuration or script hooks."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import re
import time
from typing import Any
import zlib

from app.shared.query_result_contract import FIELD_DECODING_POLICY, QUERY_RESULT_MAX_BYTES


CHUNK_BYTES = 64 * 1024
_HEX = re.compile(rb"[0-9a-fA-F]+")


class InputBudgetExceeded(Exception):
    """The next complete cell cannot be obtained within the query input budget."""


@dataclass
class DecodeBudget:
    max_bytes: int = QUERY_RESULT_MAX_BYTES
    deadline: float | None = None
    input_bytes: int = 0
    expanded_bytes: int = 0

    @property
    def input_remaining(self) -> int:
        return max(0, self.max_bytes - self.input_bytes)

    @property
    def expansion_remaining(self) -> int:
        return max(0, self.max_bytes - self.expanded_bytes)

    def check_time(self) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("Database result processing timed out")

    def check_input_size(self, size: int) -> None:
        self.check_time()
        if size < 0 or size > self.input_remaining:
            raise InputBudgetExceeded

    def consume_input(self, size: int) -> None:
        self.check_input_size(size)
        self.input_bytes += size


def _zlib_header(value: bytes) -> bool:
    return (
        len(value) >= 2
        and value[0] & 15 == 8
        and value[0] >> 4 <= 7
        and (value[0] * 256 + value[1]) % 31 == 0
    )


def _wrapped_candidate(value: bytes) -> tuple[bytes, str] | None:
    # Full strict validation preserves ordinary values and rejects noncanonical pad bits.
    if len(value) % 4 == 0:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            pass
        else:
            if _zlib_header(decoded) and base64.b64encode(decoded) == value:
                return decoded, "base64_zlib"
    hex_value = value[2:] if value.startswith((b"0x", b"0X")) else value
    if len(hex_value) % 2 == 0 and _HEX.fullmatch(hex_value):
        decoded = binascii.unhexlify(hex_value)
        if _zlib_header(decoded):
            return decoded, "hex_zlib"
    return None


def _expand(value: bytes, budget: DecodeBudget) -> tuple[bytes | None, str]:
    if value[1] & 32:
        return None, "unsupported_dictionary"
    if not budget.expansion_remaining:
        return None, "decode_limit_exceeded"
    stream = zlib.decompressobj()
    output: list[bytes] = []
    pending = b""
    offset = 0
    while True:
        budget.check_time()
        if not pending and offset < len(value):
            pending = value[offset : offset + CHUNK_BYTES]
            offset += len(pending)
        remaining = budget.expansion_remaining
        # At an exact boundary, one byte probes overflow. Zero must never mean unlimited.
        allowance = min(CHUNK_BYTES, remaining + 1)
        try:
            part = stream.decompress(pending, allowance)
        except zlib.error:
            # zlib may discard produced bytes on error. Charge the reserved chunk
            # conservatively rather than restoring its unavailable output budget.
            budget.expanded_bytes += min(allowance, remaining)
            return None, "invalid_zlib"
        budget.check_time()
        budget.expanded_bytes += min(len(part), remaining)
        if len(part) > remaining:
            return None, "decode_limit_exceeded"
        output.append(part)
        pending = stream.unconsumed_tail
        if stream.eof:
            if stream.unused_data or pending or offset < len(value):
                return None, "invalid_zlib"
            return b"".join(output), "decoded"
        if not pending and offset == len(value) and len(part) < allowance:
            return None, "invalid_zlib"


def _binary_original(value: bytes) -> dict[str, Any]:
    return {
        "type": "binary",
        "encoding": "base64",
        "data": base64.b64encode(value).decode("ascii"),
        "size_bytes": len(value),
    }


def decode_value(value: Any, budget: DecodeBudget) -> tuple[Any, dict[str, Any] | None]:
    """Return a complete projection and safe cell facts; input overflow rejects the row."""
    budget.check_time()
    binary = isinstance(value, (bytes, bytearray, memoryview))
    if not binary and not isinstance(value, str):
        return value, None
    # Reject by character/byte count before copying or UTF-8 encoding a huge scalar.
    size = value.nbytes if isinstance(value, memoryview) else len(value)
    budget.check_input_size(size)
    raw = bytes(value) if binary else value.encode("utf-8")
    budget.consume_input(len(raw))
    candidate = (raw, "raw_zlib") if binary and _zlib_header(raw) else None
    if candidate is None and raw.isascii():
        candidate = _wrapped_candidate(raw)
    if candidate is None:
        if not binary:
            return value, None
        return _binary_original(raw), {
            "status": "binary_uninterpreted",
            "input_format": "binary",
            "input_size_bytes": len(raw),
        }
    compressed, input_format = candidate
    expanded, status = _expand(compressed, budget)
    facts: dict[str, Any] = {
        "status": status,
        "input_format": input_format,
        "input_size_bytes": len(raw),
    }
    if expanded is not None:
        try:
            text = expanded.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            facts["status"] = "unsupported_text_encoding"
        else:
            facts["decoded_size_bytes"] = len(expanded)
            budget.check_time()
            return text, facts
    return _binary_original(raw) if binary else value, facts


def decoding_metadata(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not cells:
        return None
    candidates = sum(cell["status"] != "binary_uninterpreted" for cell in cells)
    decoded = sum(cell["status"] == "decoded" for cell in cells)
    return {
        "policy_version": FIELD_DECODING_POLICY,
        "candidate_count": candidates,
        "decoded_count": decoded,
        "failed_count": candidates - decoded,
        "complete": candidates == decoded,
        "cells": cells,
    }
