from __future__ import annotations

from typing import Any, Mapping

import jsonschema
import pytest

from app.modules.file_workspace.contracts import (
    ATTACHMENT_TASK_CONTRACT_VERSION,
    ATTACHMENT_TASK_V0_SCHEMA,
    ATTACHMENT_TASK_V1_SCHEMA,
    FILE_ERROR_CATALOG,
    FILE_MCP_PATH,
    FILE_MCP_SERVER_CODE,
    FILE_TOOL_MANIFEST,
    FILE_TRANSFER_META_KEY,
    FILE_TRANSFER_PROTOCOL,
    INTERNAL_STREAMING_API,
)
from app.python_runtime.file_transfer import (
    FILE_TRANSFER_META_KEY as PYTHON_FILE_TRANSFER_META_KEY,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.python_runtime.file_transfer import (
    FILE_TRANSFER_PROTOCOL as PYTHON_FILE_TRANSFER_PROTOCOL,
)


EXPECTED_FILE_TOOLS = {
    "task_workspace_get",
    "task_workspace_list_files",
    "task_workspace_search_files",
    "file_get_metadata",
    "file_prepare_materialization",
    "file_create_commit_intent",
    "file_retain_version",
    "file_deliver_version",
}
FORBIDDEN_INPUT_FIELDS = {
    "authorization",
    "headers",
    "user_id",
    "tenant_id",
    "workspace_id",
    "reply_route",
    "url",
    "path",
    "relative_path",
    "bucket",
    "object_key",
    "credential",
    "credential_ref",
    "server_url",
    "script",
    "shell",
}


def _property_names(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {name for child in value.values() for name in _property_names(child)}
    if isinstance(value, list):
        return {name for child in value for name in _property_names(child)}
    return set()


def _validate(schema: Mapping[str, Any], payload: Mapping[str, object]) -> None:
    jsonschema.Draft202012Validator(dict(schema)).validate(payload)


def test_file_tool_manifest_is_fixed_closed_and_contains_no_execution_escape_hatches() -> None:
    assert FILE_MCP_SERVER_CODE == "file-service"
    assert FILE_MCP_PATH == "/mcp"
    assert set(FILE_TOOL_MANIFEST) == EXPECTED_FILE_TOOLS
    assert (
        FILE_TOOL_MANIFEST["file_get_metadata"].schema_hash
        == FILE_TOOL_MANIFEST["file_retain_version"].schema_hash
        == FILE_TOOL_MANIFEST["file_deliver_version"].schema_hash
    )
    for identifier, tool in FILE_TOOL_MANIFEST.items():
        assert tool.identifier == identifier
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False
        assert len(tool.schema_hash) == 64
        assert not (_property_names(tool.input_schema) & FORBIDDEN_INPUT_FIELDS)
        global_tool = MCP_TOOL_MANIFEST[identifier]
        assert global_tool.server_code == FILE_MCP_SERVER_CODE
        assert global_tool.schema_hash == tool.schema_hash
        assert global_tool.read_only is (not tool.mutating)


def test_file_tool_descriptions_define_catalog_document_materialization_handoff() -> None:
    search = FILE_TOOL_MANIFEST["task_workspace_search_files"].description
    metadata = FILE_TOOL_MANIFEST["file_get_metadata"].description
    materialize = FILE_TOOL_MANIFEST["file_prepare_materialization"].description

    assert "直接调用file_prepare_materialization" in search
    assert "不要先调用file_get_metadata" in search
    assert "DIRECT_TEXT、AVAILABLE或PARTIAL" in search
    assert "PROCESSING表示仍在处理" in search
    assert "NO_TEXT、FAILED和CONTENT_UNAVAILABLE" in search
    assert "仅查询当前Job初始File Manifest" in metadata
    assert "不要对task_workspace_search_files返回的目录候选" in metadata
    assert "初始Manifest条目" in materialize
    assert "冻结目录候选" in materialize
    assert "DIRECT_TEXT的TXT、只读LOG和Markdown" in materialize
    assert "PDF、DOCX、PPTX、XLSX、PNG、JPEG和WebP" in materialize
    assert "只读Markdown representation" in materialize
    assert "原始二进制不进入Sandbox" in materialize


def test_file_tool_descriptions_define_commit_and_delivery_handoff() -> None:
    commit = FILE_TOOL_MANIFEST["file_create_commit_intent"].description
    deliver = FILE_TOOL_MANIFEST["file_deliver_version"].description

    assert "文件持久化步骤2/2" in commit
    assert "必须先调用select_sandbox_output" in commit
    assert "delivery_mode=DEFAULT" in commit
    assert "只有明确要求仅保存到工作区" in commit
    assert "delivery_status=PENDING表示已排队" in commit
    assert "不要再调用file_deliver_version" in commit
    assert "当前Job以WORKSPACE_ONLY成功提交" in deliver
    assert "必须传精确file_id/version_id" in deliver
    assert "新生成文件使用DEFAULT提交后已自动创建交付" in deliver


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_INPUT_FIELDS))
def test_file_tool_schemas_reject_identity_location_and_dynamic_execution_fields(
    forbidden: str,
) -> None:
    schema = FILE_TOOL_MANIFEST["task_workspace_get"].input_schema
    with pytest.raises(jsonschema.ValidationError):
        _validate(schema, {forbidden: "forbidden"})


def test_file_commit_schema_distinguishes_new_file_and_existing_version() -> None:
    schema = FILE_TOOL_MANIFEST["file_create_commit_intent"].input_schema
    base = {
        "sandbox_entry_handle": "entry-1",
        "display_name": "result.txt",
        "user_intent": "GENERATE",
        "delivery_mode": "DEFAULT",
    }
    _validate(schema, base)
    _validate(schema, {**base, "display_name": "result.md"})
    with pytest.raises(jsonschema.ValidationError):
        _validate(schema, {**base, "display_name": "result.log"})
    _validate(
        schema,
        {
            **base,
            "user_intent": "MODIFY",
            "file_id": "file-1",
            "base_version_id": "version-1",
        },
    )
    with pytest.raises(jsonschema.ValidationError):
        _validate(schema, {**base, "file_id": "file-1"})
    with pytest.raises(jsonschema.ValidationError):
        _validate(schema, {**base, "url": "https://example.invalid"})

    materialize = FILE_TOOL_MANIFEST["file_prepare_materialization"].input_schema
    for name in ("source.txt", "trace.log", "notes.md"):
        _validate(
            materialize,
            {"file_id": "file-1", "version_id": "version-1", "preferred_name": name},
        )
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            materialize,
            {
                "file_id": "file-1",
                "version_id": "version-1",
                "preferred_name": "notes.markdown",
            },
        )


def test_internal_streaming_api_is_fixed_private_and_never_carries_credentials_in_paths() -> None:
    assert {(endpoint.method, endpoint.path_template) for endpoint in INTERNAL_STREAMING_API} == {
        ("GET", "/internal/v1/file-transfers/{transfer_id}/content"),
        ("PUT", "/internal/v1/file-commits/{commit_id}/content"),
        ("POST", "/internal/v1/attachments/{attachment_id}/content"),
    }
    for endpoint in INTERNAL_STREAMING_API:
        lowered = endpoint.path_template.lower()
        assert "?" not in endpoint.path_template
        assert not any(
            value in lowered
            for value in ("token", "secret", "credential", "bucket", "object", "url")
        )
        assert endpoint.maximum_body_bytes <= 25 * 1024 * 1024


def test_attachment_queue_contract_accepts_inflight_v0_and_versioned_v1_only() -> None:
    _validate(
        ATTACHMENT_TASK_V0_SCHEMA,
        {"attachment_id": "attachment-1", "correlation_id": "correlation-1"},
    )
    _validate(
        ATTACHMENT_TASK_V1_SCHEMA,
        {
            "contract_version": ATTACHMENT_TASK_CONTRACT_VERSION,
            "attachment_id": "attachment-1",
            "correlation_id": "correlation-1",
            "source_idempotency_key": "attachment-1",
            "requested_at": "2026-08-14T00:00:00+00:00",
        },
    )
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            ATTACHMENT_TASK_V1_SCHEMA,
            {
                "contract_version": ATTACHMENT_TASK_CONTRACT_VERSION,
                "attachment_id": "attachment-1",
                "correlation_id": "correlation-1",
                "source_idempotency_key": "attachment-1",
                "object_key": "forbidden",
            },
        )


def test_file_transfer_protocol_and_stable_errors_are_cross_runtime_safe() -> None:
    assert FILE_TRANSFER_PROTOCOL == PYTHON_FILE_TRANSFER_PROTOCOL
    assert FILE_TRANSFER_META_KEY == PYTHON_FILE_TRANSFER_META_KEY
    expected_runtime_errors = {
        "file_transfer_control_invalid",
        "file_transfer_protocol_unsupported",
        "file_transfer_action_unsupported",
        "file_transfer_path_invalid",
        "file_transfer_handle_conflict",
        "file_transfer_handle_unknown",
        "file_transfer_size_mismatch",
        "file_transfer_integrity_mismatch",
        "file_transfer_receipt_mismatch",
    }
    assert expected_runtime_errors <= set(FILE_ERROR_CATALOG)
    assert all(
        error.safe_message and "secret" not in error.safe_message.lower()
        for error in FILE_ERROR_CATALOG.values()
    )
