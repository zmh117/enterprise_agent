from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit


def sdk_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def looks_transient(message: str) -> bool:
    lower = message.lower()
    return any(
        item in lower
        for item in (
            "timeout",
            "timed out",
            "temporarily",
            "rate limit",
            "overloaded",
            "529",
            "503",
            "502",
            "connection",
            "transport",
            "json",
        )
    )


def looks_inconsistent_result(message: str) -> bool:
    lower = message.lower()
    return "error result: success" in lower or ("is_error=true" in lower and "success" in lower)


def looks_invalid_model(message: str) -> bool:
    lower = message.lower()
    return any(
        marker in lower
        for marker in (
            "model not found",
            "invalid model",
            "unknown model",
            "does not exist or you do not have access to it",
        )
    )


def result_error_details(message: Any) -> tuple[str, bool] | None:
    is_error = sdk_value(message, "is_error")
    if is_error is not True:
        return None
    subtype = sdk_value(message, "subtype")
    errors = sdk_value(message, "errors")
    result = sdk_value(message, "result")
    detail = compact_error_detail(
        json.dumps(
            {"subtype": subtype, "errors": errors, "result": result},
            ensure_ascii=False,
            default=str,
        )
    )
    inconsistent = str(result).strip().lower() == "success" or (
        not errors and str(subtype or "").lower() in {"success", "completed"}
    )
    return detail or "Claude runtime returned an error result", inconsistent


def looks_max_turns_exhausted(message: str) -> bool:
    lower = message.lower()
    return "maximum number of turns" in lower or "max turns" in lower


def append_cli_stderr(lines: list[str], line: str, max_chars: int) -> None:
    text = redact_sensitive_text(str(line)).strip()
    if not text:
        return
    lines.append(text)
    total = sum(len(item) for item in lines)
    while lines and total > max_chars:
        removed = lines.pop(0)
        total -= len(removed)


def sdk_error_message(exc: Exception, cli_stderr: list[str]) -> str:
    message = redact_sensitive_text(str(exc)).strip()
    stderr = "\n".join(cli_stderr).strip()
    if stderr and stderr not in message:
        if message:
            return f"{message}\nCLI stderr:\n{stderr}"
        return stderr
    return message or exc.__class__.__name__


def safe_sdk_error_message(prefix: str, detail: str) -> str:
    compact = compact_error_detail(detail)
    return f"{prefix}: {compact}" if compact else prefix


def compact_error_detail(detail: str, max_chars: int = 500) -> str:
    text = redact_sensitive_text(detail)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def redact_sensitive_text(text: str) -> str:
    patterns = (
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(anthropic_api_key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(anthropic_auth_token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)https?://[^\s\]\[\)\(\}\{\"']+", "<redacted-url>"),
    )
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def bounded_safe_diagnostic(value: Any, max_chars: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    return compact_error_detail(text, max_chars=max_chars)


def provider_host(base_url: str) -> str:
    if not base_url:
        return "default"
    try:
        return (urlsplit(base_url).hostname or "invalid").lower()[:255]
    except ValueError:
        return "invalid"


def looks_placeholder_api_key(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized.startswith("<")
        or normalized.startswith("your-")
        or normalized.startswith("your_")
        or normalized in {"your-key", "your-api-key", "test-key", "replace-me"}
        or "你的" in normalized
        or "api key" in normalized
        or "api-key" in normalized
    )
