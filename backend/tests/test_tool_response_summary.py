from __future__ import annotations

import json

import pytest

from app.shared.tool_response_summary import MAX_TOOL_SUMMARY_SOURCE_CHARS, tool_response_summary


@pytest.mark.parametrize(
    "wrapper",
    [
        lambda value: value,
        json.dumps,
        lambda value: {"payload": json.dumps(value), "truncated": False},
        lambda value: {"structuredContent": value},
        lambda value: {"content": [{"type": "text", "text": json.dumps(value)}]},
        lambda value: {
            "payload": json.dumps(
                [{"type": "text", "text": json.dumps({"runtime_file_bridge": value})}]
            )
        },
    ],
)
def test_metadata_is_extracted_before_any_text_truncation(wrapper) -> None:
    metadata = {
        "returned": 51,
        "total": 51,
        "cumulative_returned": 51,
        "truncated": False,
        "complete": True,
        "untrusted_data": True,
    }
    source = {
        "items": [{"name": "synthetic-private-body" * 200}],
        "result_file": "private/path",
        "next_cursor": "opaque",
        **metadata,
    }
    assert tool_response_summary(wrapper(source)) == metadata


@pytest.mark.parametrize(
    "value",
    [
        '{"items":[{"name":"synthetic-private-body',
        {"payload": '{"returned":51}', "truncated": True},
        {"items": [{"returned": 99}]},
        [1, 2, 3],
        "x" * (MAX_TOOL_SUMMARY_SOURCE_CHARS + 1),
        {"returned": True, "total": -1, "size_bytes": "15", "truncated": "false"},
        {"failure": {"raw_message": "synthetic-private-body"}},
    ],
)
def test_invalid_or_unsupported_body_is_not_used_as_a_summary(value: object) -> None:
    assert tool_response_summary(value) == {"available": False}


def test_failure_summary_is_bounded_and_secret_filtered() -> None:
    result = tool_response_summary(
        {
            "failure": {
                "code": "ones_provider_schema_invalid",
                "safe_message": "字段无效 token=synthetic-private-token " + "x" * 600,
            }
        }
    )
    assert result["error_code"] == "ones_provider_schema_invalid"
    assert len(result["error"]) <= 500
    assert "synthetic-private-token" not in result["error"]


def test_file_metadata_does_not_imply_a_commit() -> None:
    result = tool_response_summary(
        {
            "runtime_file_bridge": {
                "selected": True,
                "size_bytes": 18,
                "relative_path": "private/path",
                "intent_token": "synthetic-private-token",
            }
        }
    )
    assert result == {"selected": True, "size_bytes": 18}
    assert tool_response_summary({"file_tool_result": "omitted"}) == {"content_omitted": True}
