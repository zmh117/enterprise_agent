from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, Request as FastAPIRequest


class LocalPlatformError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = {"error": {"code": code, "message": message}}


def envelope(summary: dict[str, Any], request: FastAPIRequest, source: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "raw": summary,
        "truncated": False,
        "metadata": {
            "request_id": request.headers.get("x-correlation-id", "-"),
            "source": source,
            "duration_ms": 1,
        },
    }


def tool_not_configured(tool_name: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "tool_not_configured",
                "message": f"{tool_name} tool is not configured in local internal platform",
            }
        },
    )


def safe_error_text(text: str, max_chars: int = 300) -> str:
    redacted = redact_text(text)
    compact = " ".join(redacted.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def redact_text(text: str) -> str:
    patterns = (
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(password\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(secret\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
    )
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted
