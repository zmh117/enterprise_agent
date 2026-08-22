from __future__ import annotations

from io import BytesIO

import pytest

from app.modules.file_workspace.domain import FileAction
from app.modules.file_workspace.text_format_policy import (
    TextFormatCode,
    TextStreamValidator,
    get_text_format_policy,
    text_format_for_name,
    validate_format_action,
)
from app.shared.exceptions import NonRetryableExecutionError


def test_current_text_matrix_is_fixed_and_closed() -> None:
    policy = get_text_format_policy()
    assert [item.code for item in policy.formats] == [
        TextFormatCode.TXT,
        TextFormatCode.LOG,
        TextFormatCode.MARKDOWN,
    ]
    assert policy.by_code("MARKDOWN").writable is True
    assert FileAction.COMMIT not in policy.by_code("LOG").actions
    assert FileAction.DELIVER in policy.by_code("LOG").actions


def test_rule_has_no_runtime_version_selector() -> None:
    with pytest.raises(TypeError):
        get_text_format_policy("text-v2")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        text_format_for_name("notes.txt", policy_version="text-v2")  # type: ignore[call-arg]


def test_log_is_read_only_at_policy_boundary() -> None:
    assert validate_format_action(
        format_code="LOG", action=FileAction.MATERIALIZE
    ).code is TextFormatCode.LOG
    with pytest.raises(NonRetryableExecutionError) as caught:
        validate_format_action(format_code="LOG", action=FileAction.COMMIT)
    assert caught.value.error_code == "file_format_read_only"


@pytest.mark.parametrize(
    ("name", "media_type", "expected_format", "expected_media_type"),
    [
        ("notes.txt", "text/plain", TextFormatCode.TXT, "text/plain"),
        ("trace.log", "text/plain", TextFormatCode.LOG, "text/plain"),
        ("trace.log", "application/octet-stream", TextFormatCode.LOG, "text/plain"),
        ("report.md", "text/markdown", TextFormatCode.MARKDOWN, "text/markdown"),
        ("report.md", "text/plain", TextFormatCode.MARKDOWN, "text/markdown"),
    ],
)
def test_stream_validator_accepts_only_current_extension_mime_pairs(
    name: str,
    media_type: str,
    expected_format: TextFormatCode,
    expected_media_type: str,
) -> None:
    target = BytesIO()
    result = TextStreamValidator().validate_and_copy(
        ["一".encode("utf-8")[:1], "一".encode("utf-8")[1:], b"\n"],
        target,
        display_name=name,
        media_type=media_type,
        agent_output=False,
    )
    assert target.getvalue() == "一\n".encode()
    assert result.format_code is expected_format
    assert result.media_type == expected_media_type


@pytest.mark.parametrize(
    ("name", "media_type", "code"),
    [
        ("trace.log", "text/markdown", "file_mime_invalid"),
        ("notes.md", "application/octet-stream", "file_mime_invalid"),
        ("notes.markdown", "text/markdown", "file_type_unsupported"),
        ("notes.txt", "text/plain", "file_type_invalid"),
    ],
)
def test_stream_validator_fails_closed(name: str, media_type: str, code: str) -> None:
    chunks = [b"value\x00more"] if code == "file_type_invalid" else [b"value"]
    with pytest.raises(NonRetryableExecutionError) as caught:
        TextStreamValidator().validate_and_copy(
            chunks,
            BytesIO(),
            display_name=name,
            media_type=media_type,
            agent_output=False,
        )
    assert caught.value.error_code == code


def test_inputs_allow_utf8_bom_but_outputs_and_log_writes_fail_closed() -> None:
    payload = b"\xef\xbb\xbf# title\n"
    result = TextStreamValidator().validate_and_copy(
        [payload],
        BytesIO(),
        display_name="report.md",
        media_type="text/markdown",
        agent_output=False,
    )
    assert result.had_utf8_bom is True

    with pytest.raises(NonRetryableExecutionError) as bom:
        TextStreamValidator().validate_and_copy(
            [payload],
            BytesIO(),
            display_name="report.md",
            media_type="text/markdown",
            agent_output=True,
        )
    assert bom.value.error_code == "file_output_bom_forbidden"

    target = BytesIO()
    with pytest.raises(NonRetryableExecutionError) as read_only:
        TextStreamValidator().validate_and_copy(
            [b"must-not-write"],
            target,
            display_name="trace.log",
            media_type="text/plain",
            agent_output=True,
        )
    assert read_only.value.error_code == "file_format_read_only"
    assert target.getvalue() == b""
