from __future__ import annotations

import pytest

from app.shared.sdk_failure_metadata import safe_sdk_failure_metadata


def test_sdk_failure_metadata_drops_prose_and_validates_types() -> None:
    assert safe_sdk_failure_metadata(
        {
            "subtype": "success",
            "terminal_reason": "api_error",
            "is_error": True,
            "api_error_status": 429,
            "error_count": 0,
            "duration_ms": 1234,
            "num_turns": 2,
            "result_present": True,
            "result": "synthetic-private-response",
            "errors": ["synthetic-private-error"],
            "stderr": "synthetic-private-stderr",
        }
    ) == {
        "subtype": "success",
        "terminal_reason": "api_error",
        "is_error": True,
        "api_error_status": 429,
        "error_count": 0,
        "duration_ms": 1234,
        "num_turns": 2,
        "result_present": True,
    }


@pytest.mark.parametrize("value", [None, [], "synthetic-private-response"])
def test_sdk_failure_metadata_rejects_non_mappings(value: object) -> None:
    assert safe_sdk_failure_metadata(value) == {}


def test_sdk_failure_metadata_does_not_echo_unknown_enums_or_invalid_scalars() -> None:
    assert safe_sdk_failure_metadata(
        {
            "subtype": "synthetic-private-subtype",
            "terminal_reason": "synthetic-private-reason",
            "api_error_status": True,
            "duration_ms": -1,
            "num_turns": 2**60,
            "error_count": "5",
            "is_error": "true",
            "result_present": 1,
        }
    ) == {"subtype": "unknown", "terminal_reason": "unknown"}


@pytest.mark.parametrize("status", [99, 600, 429.0, "429"])
def test_sdk_failure_metadata_rejects_invalid_http_status(status: object) -> None:
    assert safe_sdk_failure_metadata({"api_error_status": status}) == {}
