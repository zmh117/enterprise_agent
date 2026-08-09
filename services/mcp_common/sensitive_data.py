from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:password|passwd|secret|token|authorization|cookie|credential|dsn|connection_string|api_key)(?:$|_)",
    re.IGNORECASE,
)
_AUTH_VALUE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[a-z0-9._~+/=-]{6,}"
)
_CONNECTION_URI = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|redis|rediss|mongodb(?:\+srv)?|oracle|sqlserver|jdbc:[a-z0-9]+)://[^\s\"']+"
)
_KEY_VALUE_SECRET = re.compile(
    r"(?i)\b(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+"
)


def sanitize_sensitive_data(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        redacted_fields = 0
        for key, item in value.items():
            normalized_key = str(key)
            if _SENSITIVE_KEY.search(normalized_key):
                redacted_fields += 1
                continue
            sanitized[normalized_key] = sanitize_sensitive_data(item)
        if redacted_fields:
            sanitized["redacted_fields"] = f"[REDACTED:{redacted_fields}]"
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_sensitive_data(item) for item in value]
    if isinstance(value, str):
        if _SENSITIVE_KEY.fullmatch(value.strip()):
            return "[REDACTED]"
        redacted = _AUTH_VALUE.sub("[REDACTED]", value)
        redacted = _CONNECTION_URI.sub("[REDACTED]", redacted)
        return _KEY_VALUE_SECRET.sub("[REDACTED]", redacted)
    return value
