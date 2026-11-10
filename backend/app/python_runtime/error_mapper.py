from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit


_MODEL_ACCESS_FAILURES = {
    401: (
        "runtime_model_authentication",
        "模型服务认证失败：API Key 无效或已失效，请管理员检查并更新模型连接的 API Key 后重试。",
    ),
    403: (
        "runtime_model_permission_denied",
        "模型服务拒绝访问：当前凭据无权访问该模型或资源，请管理员检查模型授权。",
    ),
}
_MODEL_ACCESS_ERROR_TYPES = {
    "authentication_failed": 401,
    "authentication_error": 401,
    "invalid_api_key": 401,
    "permission_error": 403,
    "permission_denied_error": 403,
}


def sdk_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def is_max_turns_failure(source: Any) -> bool:
    """Use SDK terminal facts, never text from assistant or tool messages."""
    data = getattr(source, "data", None) if isinstance(source, Exception) else None
    payload = data if isinstance(data, dict) else source
    is_result = (
        sdk_value(payload, "type") == "result"
        or type(payload).__name__ == "ResultMessage"
        or (type(source).__name__ == "ResultError" and isinstance(data, dict))
    )
    return (
        is_result
        and sdk_value(payload, "is_error") is True
        and (
            sdk_value(payload, "subtype") == "error_max_turns"
            or sdk_value(payload, "terminal_reason") == "max_turns"
        )
    )


def model_access_failure(source: Any) -> tuple[str, str] | None:
    """Classify model-boundary failures, never ordinary assistant/tool content."""
    is_exception = isinstance(source, Exception)
    data = getattr(source, "data", None) if is_exception else None
    payload = data if isinstance(data, dict) else source
    error = sdk_value(payload, "error")
    error_type = error if isinstance(error, str) else sdk_value(error, "type")
    is_assistant = (
        sdk_value(payload, "type") == "assistant" or type(payload).__name__ == "AssistantMessage"
    )
    is_result = sdk_value(payload, "type") == "result" or type(payload).__name__ == "ResultMessage"
    if not (
        is_exception
        or (is_result and sdk_value(payload, "is_error") is True)
        or (is_assistant and error_type == "authentication_failed")
    ):
        return None
    status = sdk_value(payload, "api_error_status")
    if status is None and is_exception:
        status = getattr(source, "status_code", None)
    # A concrete HTTP status takes precedence over lower-fidelity text/type hints.
    if type(status) is int and 100 <= status <= 599:
        return _MODEL_ACCESS_FAILURES.get(status)
    if isinstance(error_type, str) and error_type in _MODEL_ACCESS_ERROR_TYPES:
        return _MODEL_ACCESS_FAILURES[_MODEL_ACCESS_ERROR_TYPES[error_type]]
    texts = [sdk_value(payload, "result")]
    errors = sdk_value(payload, "errors")
    if isinstance(errors, list):
        texts.extend(errors[:5])
    if is_exception:
        texts.append(str(source))
    return _legacy_model_access_failure(texts)


def _legacy_model_access_failure(texts: list[Any]) -> tuple[str, str] | None:
    # Older CLI versions expose the HTTP status only in this API-error envelope.
    # Do not scan arbitrary prose, tool results, or stderr for auth-related words.
    for text in texts:
        if not isinstance(text, str):
            continue
        match = re.match(
            r"^\s*(?:Claude Code returned an error result:\s*)?API Error:\s*(\d{3})\b",
            text[:256],
            re.IGNORECASE,
        )
        if match:
            return _MODEL_ACCESS_FAILURES.get(int(match.group(1)))
    return None


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
        (
            r"(?i)(x-(?:mcp-principal-token-[a-z0-9-]+|file-principal-token)"
            r"[\"']?\s*[:=]\s*[\"']?)[^\s,;\"']+",
            r"\1<redacted>",
        ),
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
