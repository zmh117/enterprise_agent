"""Bounded Tool Call metadata; never a preview of business or file content."""

from __future__ import annotations

import json
import re
from typing import Any

from app.shared.secret_redaction import redact_sensitive_text


MAX_TOOL_SUMMARY_SOURCE_CHARS = 1_048_576
_COUNTS = (
    "returned",
    "total",
    "cumulative_returned",
    "count",
    "row_count",
    "line_count",
    "size_bytes",
    "content_bytes",
    "input_count",
    "scanned_bytes",
    "candidate_count",
    "retained_count",
    "omitted_count",
)
_FLAGS = (
    "truncated",
    "pagination_limit_reached",
    "untrusted_data",
    "complete",
    "is_error",
    "available",
    "selected",
    "committed",
    "reused",
    "coverage_complete",
    "content_omitted",
)


def tool_response_summary(value: object) -> dict[str, Any]:
    source = _source(value)
    if source is None:
        return {"available": False}
    result: dict[str, Any] = {}
    for field in _COUNTS:
        number = source.get(field)
        if type(number) is int and 0 <= number <= 9_007_199_254_740_991:
            result[field] = number
    for field in _FLAGS:
        if type(source.get(field)) is bool:
            result[field] = source[field]
    if source.get("file_tool_result") == "omitted":
        result["content_omitted"] = True
    error = source.get("error")
    if isinstance(error, str) and error:
        result["error"] = redact_sensitive_text(error, parse_json=False)[:500]
    code = source.get("error_code")
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", code):
        result["error_code"] = code
    failure = source.get("failure")
    if isinstance(failure, dict) and not ("error" in result or "error_code" in result):
        failure_summary = tool_response_summary(
            {"error": failure.get("safe_message"), "error_code": failure.get("code")}
        )
        result.update({key: value for key, value in failure_summary.items() if key != "available"})
    return result or {"available": False}


def _source(value: object, depth: int = 0) -> dict[str, Any] | None:
    if depth >= 6:
        return None
    if isinstance(value, str):
        if len(value) > MAX_TOOL_SUMMARY_SOURCE_CHARS:
            return None
        try:
            return _source(json.loads(value), depth + 1)
        except (ValueError, RecursionError):
            return None
    if isinstance(value, list):
        # Only the standard single JSON text block is a metadata envelope.
        if len(value) == 1:
            block = value[0]
            if isinstance(block, dict) and block.get("type") == "text":
                return _source(block.get("text"), depth + 1)
        return None
    if not isinstance(value, dict):
        return None
    for field in ("structuredContent", "structured_content", "runtime_file_bridge"):
        if field in value:
            return _source(value[field], depth + 1)
    if "payload" in value:
        # This flag describes transport truncation, not result completeness.
        if value.get("truncated") is True:
            return None
        return _source(value["payload"], depth + 1)
    if "content" in value and isinstance(value["content"], list):
        return _source(value["content"], depth + 1)
    return value
