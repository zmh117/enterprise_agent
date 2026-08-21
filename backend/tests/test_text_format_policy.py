from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest

from app.modules.file_workspace.domain import FileAction
from app.modules.file_workspace.text_format_policy import (
    FileFormatPolicyVersion,
    TextFormatCode,
    TextStreamValidator,
    get_text_format_policy,
    policy_runtime_protocol_version,
    text_format_for_name,
    validate_format_action,
)
from app.shared.exceptions import NonRetryableExecutionError
from app.python_runtime.job_sandbox import (
    JobSandboxError,
    JobSandboxLimits,
    JobSandboxManager,
)


SHARED_FIXTURE = (
    Path(__file__).parents[2] / "contracts" / "agent-runtime" / "text-format-policy-v2.fixture.json"
)


def test_text_v1_remains_txt_only_and_text_v2_matrix_is_closed() -> None:
    v1 = get_text_format_policy("text-v1")
    v2 = get_text_format_policy("text-v2")

    assert [item.code for item in v1.formats] == [TextFormatCode.TXT]
    assert [item.code for item in v2.formats] == [
        TextFormatCode.TXT,
        TextFormatCode.LOG,
        TextFormatCode.MARKDOWN,
    ]
    assert FileAction.COMMIT not in v2.by_code("LOG").actions
    assert FileAction.EDIT not in v2.by_code("LOG").actions
    assert FileAction.DELIVER in v2.by_code("LOG").actions
    assert v2.by_code("MARKDOWN").writable is True
    assert policy_runtime_protocol_version("text-v1") == "1.2"
    assert policy_runtime_protocol_version("text-v2") == "1.3"


@pytest.mark.parametrize("name", ["trace.log", "notes.md", "notes.markdown"])
def test_text_v1_does_not_inherit_new_formats(name: str) -> None:
    with pytest.raises(NonRetryableExecutionError) as caught:
        text_format_for_name(name, policy_version="text-v1")
    assert caught.value.error_code == "file_type_unsupported"


def test_log_is_read_only_at_policy_boundary() -> None:
    assert (
        validate_format_action(
            policy_version="text-v2",
            format_code="LOG",
            action=FileAction.MATERIALIZE,
        ).code
        is TextFormatCode.LOG
    )
    with pytest.raises(NonRetryableExecutionError) as caught:
        validate_format_action(
            policy_version="text-v2",
            format_code="LOG",
            action=FileAction.COMMIT,
        )
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
def test_stream_validator_accepts_only_registered_extension_mime_pairs(
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
        policy_version=FileFormatPolicyVersion.TEXT_V2,
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
def test_stream_validator_fails_closed_for_mime_extension_and_binary_conflicts(
    name: str,
    media_type: str,
    code: str,
) -> None:
    chunks = [b"value\x00more"] if code == "file_type_invalid" else [b"value"]
    with pytest.raises(NonRetryableExecutionError) as caught:
        TextStreamValidator().validate_and_copy(
            chunks,
            BytesIO(),
            display_name=name,
            media_type=media_type,
            agent_output=False,
            policy_version="text-v2",
        )
    assert caught.value.error_code == code


def test_inputs_allow_utf8_bom_but_writable_outputs_reject_it() -> None:
    payload = b"\xef\xbb\xbf# title\n"
    input_result = TextStreamValidator().validate_and_copy(
        [payload],
        BytesIO(),
        display_name="report.md",
        media_type="text/markdown",
        agent_output=False,
        policy_version="text-v2",
    )
    assert input_result.had_utf8_bom is True

    with pytest.raises(NonRetryableExecutionError) as caught:
        TextStreamValidator().validate_and_copy(
            [payload],
            BytesIO(),
            display_name="report.md",
            media_type="text/markdown",
            agent_output=True,
            policy_version="text-v2",
        )
    assert caught.value.error_code == "file_output_bom_forbidden"


def test_agent_output_rejects_log_before_copying_content() -> None:
    target = BytesIO()
    with pytest.raises(NonRetryableExecutionError) as caught:
        TextStreamValidator().validate_and_copy(
            [b"must-not-write"],
            target,
            display_name="trace.log",
            media_type="text/plain",
            agent_output=True,
            policy_version="text-v2",
        )
    assert caught.value.error_code == "file_format_read_only"
    assert target.getvalue() == b""


def test_shared_fixture_matches_python_metadata_mime_action_and_byte_policy() -> None:
    fixture = json.loads(SHARED_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == 1
    for item in fixture["metadata_cases"]:
        try:
            result = TextStreamValidator().validate_and_copy(
                [b"safe\n"],
                BytesIO(),
                display_name=item["display_name"],
                media_type=item["media_type"],
                agent_output=bool(item.get("agent_output")),
                policy_version=item["policy_version"],
            )
        except NonRetryableExecutionError as exc:
            assert exc.error_code == item.get("expected_error"), item["id"]
        else:
            assert result.format_code.value == item["expected_format"], item["id"]
            assert result.media_type == item["canonical_media_type"], item["id"]

    for item in fixture["action_cases"]:
        try:
            definition = validate_format_action(
                policy_version=item["policy_version"],
                format_code=item["format_code"],
                action=FileAction(item["action"]),
            )
        except NonRetryableExecutionError as exc:
            assert exc.error_code == item.get("expected_error"), item["id"]
        else:
            assert definition.code.value == item["expected_format"], item["id"]

    for item in fixture["content_cases"]:
        validator = TextStreamValidator(max_bytes=int(item.get("max_bytes") or 15 * 1024 * 1024))
        try:
            result = validator.validate_and_copy(
                [base64.b64decode(item["bytes_base64"])],
                BytesIO(),
                display_name="content.txt",
                media_type="text/plain",
                agent_output=bool(item["agent_output"]),
                policy_version="text-v2",
            )
        except NonRetryableExecutionError as exc:
            assert exc.error_code == item.get("expected_error"), item["id"]
        else:
            assert result.had_utf8_bom is bool(item["had_utf8_bom"]), item["id"]


def test_shared_fixture_matches_python_sandbox_path_and_symlink_policy(tmp_path: Path) -> None:
    fixture = json.loads(SHARED_FIXTURE.read_text(encoding="utf-8"))
    for item in fixture["sandbox_cases"]:
        max_file_bytes = int(item.get("max_file_bytes") or 15 * 1024 * 1024)
        manager = JobSandboxManager(
            tmp_path / item["id"],
            limits=JobSandboxLimits(
                capacity_bytes=max(max_file_bytes, 1024),
                max_files=64,
                max_file_bytes=max_file_bytes,
            ),
        )
        sandbox = manager.create(
            f"fixture-{item['id']}",
            file_format_policy_version=item["policy_version"],
        )
        try:
            target = sandbox.path / item["path"]
            if item.get("existing_file"):
                target.write_text("existing", encoding="utf-8")
            if item.get("symlink"):
                outside = tmp_path / f"outside-{item['id']}.txt"
                outside.write_text("outside", encoding="utf-8")
                target.symlink_to(outside)
            raw_input = (
                {
                    "file_path": item["path"],
                    "content": "x" * int(item.get("content_size") or 1),
                }
                if item["tool"] == "Write"
                else {"file_path": item["path"]}
            )
            try:
                normalized = sandbox.authorize_tool(item["tool"], raw_input)
            except JobSandboxError as exc:
                assert exc.code == item.get("expected_error"), item["id"]
            else:
                assert normalized["file_path"] == item["expected_path"], item["id"]
        finally:
            sandbox.cleanup()
