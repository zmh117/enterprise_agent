from __future__ import annotations

import json
from typing import Any

SENSITIVE_KEYS = {"password", "secret", "token", "authorization", "apikey", "api_key"}


def mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if key.lower() in SENSITIVE_KEYS else mask_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def bounded_summary(payload: Any, max_chars: int = 4000) -> dict[str, Any]:
    masked = mask_sensitive(payload)
    serialized = json.dumps(masked, ensure_ascii=False, default=str)
    truncated = len(serialized) > max_chars
    if truncated:
        serialized = serialized[:max_chars]
    return {"payload": serialized, "truncated": truncated}
