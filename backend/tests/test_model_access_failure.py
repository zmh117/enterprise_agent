from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.python_runtime.error_mapper import model_access_failure


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"api_error_status": 401}, "runtime_model_authentication"),
        ({"api_error_status": 403}, "runtime_model_permission_denied"),
        ({"error": {"type": "authentication_error"}}, "runtime_model_authentication"),
        ({"error": {"type": "invalid_api_key"}}, "runtime_model_authentication"),
        ({"error": {"type": "permission_error"}}, "runtime_model_permission_denied"),
        ({"result": "API Error: 401 synthetic-private-key"}, "runtime_model_authentication"),
        ({"errors": ["API Error: 403 synthetic-private-body"]}, "runtime_model_permission_denied"),
    ],
)
def test_access_failure_overrides_success_subtype(fields: dict[str, Any], code: str) -> None:
    failure = model_access_failure(
        {
            "type": "result",
            "is_error": True,
            "subtype": "success",
            "errors": [],
            **fields,
        }
    )
    assert failure is not None and failure[0] == code
    assert "synthetic-private" not in str(failure)
    assert "重试策略" not in failure[1]


@pytest.mark.parametrize("status", [429, 500, 503, 529])
def test_explicit_transient_status_wins_over_auth_words(status: int) -> None:
    assert (
        model_access_failure(
            {
                "type": "result",
                "is_error": True,
                "subtype": "success",
                "api_error_status": status,
                "result": "API Error: 401",
                "error": {"type": "authentication_error"},
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "source",
    [
        {"type": "result", "is_error": False, "api_error_status": 401},
        {"type": "assistant", "content": [{"type": "text", "text": "API Error: 401"}]},
        {"type": "user", "is_error": True, "result": "API Error: 401"},
        {"type": "tool_result", "is_error": True, "result": "API Error: 401"},
        {"type": "result", "is_error": True, "result": "The document says API Error: 401"},
        {"type": "result", "is_error": True, "result": "invalid API key"},
        {"type": "result", "is_error": True, "api_error_status": "401"},
        {"type": "result", "is_error": True, "error": ["authentication_error"]},
        RuntimeError("upstream failed without status"),
        SimpleNamespace(content="authentication_failed"),
    ],
)
def test_unconfirmed_or_non_model_errors_are_not_misclassified(source: object) -> None:
    assert model_access_failure(source) is None


def test_legacy_sdk_exception_has_bounded_auth_envelope() -> None:
    failure = model_access_failure(
        RuntimeError("Claude Code returned an error result: API Error: 401 synthetic-private-key")
    )
    assert failure is not None and failure[0] == "runtime_model_authentication"
    assert "synthetic-private" not in str(failure)


def test_typed_http_exception_uses_status_code() -> None:
    error = RuntimeError("synthetic-private-key")
    error.status_code = 401  # type: ignore[attr-defined]
    failure = model_access_failure(error)
    assert failure is not None and failure[0] == "runtime_model_authentication"
