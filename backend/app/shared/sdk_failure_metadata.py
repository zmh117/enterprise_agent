from __future__ import annotations

from collections.abc import Mapping


def safe_sdk_failure_metadata(value: object) -> dict[str, object]:
    """Project structured failure facts without provider prose or message content."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    enums = {
        "subtype": {
            "success",
            "completed",
            "error_during_execution",
            "error_max_turns",
            "error_max_budget_usd",
            "error_max_structured_output_retries",
        },
        "terminal_reason": {
            "completed",
            "api_error",
            "max_turns",
            "max_budget_usd",
            "aborted_streaming",
            "aborted_tools",
            "error_during_execution",
        },
    }
    for key, allowed in enums.items():
        item = value.get(key)
        if isinstance(item, str) and item:
            result[key] = item if item in allowed else "unknown"
    for key in ("is_error", "result_present"):
        item = value.get(key)
        if type(item) is bool:
            result[key] = item
    for key in ("api_error_status", "error_count", "duration_ms", "num_turns"):
        item = value.get(key)
        minimum, maximum = (100, 599) if key == "api_error_status" else (0, 2**53 - 1)
        if type(item) is int and minimum <= item <= maximum:
            result[key] = item
    return result
