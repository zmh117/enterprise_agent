from __future__ import annotations

import json
import re
from typing import Any


REDACTED = "[REDACTED]"

_PLATFORM_SECRET_REF = re.compile(r"^secret://platform/[a-z][a-z0-9_-]{0,127}$")
_SENSITIVE_KEY_PARTS = (
    "apikey",
    "authorization",
    "ciphertext",
    "credential",
    "masterkey",
    "nonce",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "token",
)
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b("
    r"api[_-]?key|authorization|bearer|client[_-]?secret|"
    r"master[_-]?key|password|passwd|secret|token"
    r")\b(\s*[:=]\s*)([^\s,;&]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_MASTER_KEY_PATTERN = re.compile(r"\bEA_MASTER_KEY_V1:[A-Za-z0-9_-]{20,}\b")
_PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_URI_CREDENTIAL_PATTERN = re.compile(
    r"(?P<prefix>[a-z][a-z0-9+.-]*://[^:/@\s]+:)"
    r"(?P<password>[^@\s/]+)"
    r"(?P<suffix>@)",
    re.IGNORECASE,
)


def is_platform_secret_ref(value: str) -> bool:
    return bool(_PLATFORM_SECRET_REF.fullmatch(value))


def is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_sensitive_text(value: str, *, parse_json: bool = True) -> str:
    if is_platform_secret_ref(value):
        return value
    stripped = value.strip()
    if parse_json and stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, (dict, list)):
                return json.dumps(
                    sanitize_for_persistence(parsed),
                    ensure_ascii=False,
                )
    if _PRIVATE_KEY_PATTERN.search(value):
        return REDACTED
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    redacted = _MASTER_KEY_PATTERN.sub(REDACTED, redacted)
    redacted = _URI_CREDENTIAL_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}{match.group('suffix')}",
        redacted,
    )
    return _ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        redacted,
    )


def sanitize_for_persistence(value: Any, *, _depth: int = 0) -> Any:
    if _depth >= 32:
        return REDACTED
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if is_sensitive_key(text_key) and not isinstance(
                item,
                (dict, list, tuple),
            ):
                if isinstance(item, str) and is_platform_secret_ref(item):
                    sanitized[text_key] = item
                else:
                    sanitized[text_key] = REDACTED
                continue
            sanitized[text_key] = sanitize_for_persistence(
                item,
                _depth=_depth + 1,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_for_persistence(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive_text(str(value), parse_json=False)
