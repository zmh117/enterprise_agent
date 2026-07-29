from __future__ import annotations

import json
from typing import Any

from app.shared.secret_redaction import is_sensitive_key, sanitize_for_persistence


def mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if is_sensitive_key(key) and not isinstance(item, (dict, list, tuple))
                else mask_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask_sensitive(item) for item in value]
    return value


def bounded_summary(payload: Any, max_chars: int = 4000) -> dict[str, Any]:
    masked = sanitize_for_persistence(payload)
    serialized = json.dumps(masked, ensure_ascii=False, default=str)
    truncated = len(serialized) > max_chars
    if truncated:
        serialized = serialized[:max_chars]
    return {"payload": serialized, "truncated": truncated}
