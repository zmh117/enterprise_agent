from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.agent.infrastructure.generated_runtime_contracts import (
    CONTRACT_SCHEMA_SHA256,
    validate_contract,
)
from app.modules.agent.infrastructure.generated_runtime_contracts_v1_1 import (
    CONTRACT_SCHEMA_SHA256 as CONTRACT_SCHEMA_SHA256_V11,
    validate_contract as validate_v11_contract,
)
from app.modules.agent.infrastructure.generated_runtime_contracts_v1_2 import (
    CONTRACT_SCHEMA_SHA256 as CONTRACT_SCHEMA_SHA256_V12,
)
from app.modules.agent.infrastructure.generated_runtime_contracts_v1_3 import (
    CONTRACT_SCHEMA_SHA256 as CONTRACT_SCHEMA_SHA256_V13,
)
from app.modules.agent.infrastructure.runtime_protocol import (
    RuntimeProtocolError,
    SUPPORTED_RUNTIME_PROTOCOL_VERSIONS,
    canonical_request_digest,
    validate_execution_request,
    validate_runtime_contract,
)


CONTRACT_ROOT = Path(__file__).parents[2] / "contracts" / "agent-runtime" / "v1"
CONTRACT_ROOT_V11 = Path(__file__).parents[2] / "contracts" / "agent-runtime" / "v1.1"
CONTRACT_ROOT_V12 = Path(__file__).parents[2] / "contracts" / "agent-runtime" / "v1.2"
CONTRACT_ROOT_V13 = Path(__file__).parents[2] / "contracts" / "agent-runtime" / "v1.3"
CONTRACT_VERSIONS = {
    "1.0": (CONTRACT_ROOT, CONTRACT_SCHEMA_SHA256),
    "1.1": (CONTRACT_ROOT_V11, CONTRACT_SCHEMA_SHA256_V11),
    "1.2": (CONTRACT_ROOT_V12, CONTRACT_SCHEMA_SHA256_V12),
    "1.3": (CONTRACT_ROOT_V13, CONTRACT_SCHEMA_SHA256_V13),
}


def _request() -> dict[str, Any]:
    return json.loads(
        (CONTRACT_ROOT / "golden" / "execution-request.json").read_text(encoding="utf-8")
    )


def test_repository_contract_fact_source_is_complete_and_hashes_match() -> None:
    assert tuple(CONTRACT_VERSIONS) == SUPPORTED_RUNTIME_PROTOCOL_VERSIONS
    baseline_errors: dict[str, str] | None = None

    for protocol_version, (root, expected_schema_hash) in CONTRACT_VERSIONS.items():
        required_files = {
            root / "protocol.schema.json",
            root / "limits.json",
            root / "errors.json",
            root / "golden" / "execution-request.json",
            root / "golden" / "platform-secret-python.json",
            root / "golden" / "safe-runtime-fixture.json",
        }
        assert all(path.is_file() for path in required_files)

        schema_bytes = (root / "protocol.schema.json").read_bytes()
        assert hashlib.sha256(schema_bytes).hexdigest() == expected_schema_hash

        errors = json.loads((root / "errors.json").read_text(encoding="utf-8"))
        assert errors["protocol_version"] == protocol_version
        error_classes = {
            str(item["code"]): str(item["retry_class"]) for item in errors["errors"]
        }
        if baseline_errors is None:
            baseline_errors = error_classes
        else:
            assert baseline_errors.items() <= error_classes.items()

        request = json.loads(
            (root / "golden" / "execution-request.json").read_text(encoding="utf-8")
        )
        assert request["protocol_version"] == protocol_version
        assert canonical_request_digest(request) == request["request_digest"]
        assert validate_execution_request(request) == request

        historical = json.loads(
            (root / "golden" / "safe-runtime-fixture.json").read_text(encoding="utf-8")
        )
        validate_runtime_contract(
            "ToolEvent",
            historical["tool_event"],
            protocol_version=protocol_version,
        )
        validate_runtime_contract(
            "RuntimeFailure",
            historical["failure"],
            protocol_version=protocol_version,
        )


@pytest.mark.parametrize("protocol_version", SUPPORTED_RUNTIME_PROTOCOL_VERSIONS)
def test_python_contract_covers_full_lifecycle_for_every_supported_version(
    protocol_version: str,
) -> None:
    root, _schema_hash = CONTRACT_VERSIONS[protocol_version]
    request = json.loads(
        (root / "golden" / "execution-request.json").read_text(encoding="utf-8")
    )
    fixture = json.loads(
        (root / "golden" / "safe-runtime-fixture.json").read_text(encoding="utf-8")
    )
    base_event = {
        "protocol_version": protocol_version,
        "invocation_id": request["invocation_id"],
        "request_digest": request["request_digest"],
        "timestamp": "2026-08-17T00:00:00Z",
    }
    accepted = {
        **base_event,
        "sequence": 1,
        "event_type": "execution_started",
        "payload": fixture["runtime_provenance"],
    }
    tool = {
        **base_event,
        "sequence": 2,
        "event_type": "tool_event",
        "payload": fixture["tool_event"],
    }
    validate_runtime_contract("RuntimeEvent", accepted, protocol_version=protocol_version)
    validate_runtime_contract("RuntimeEvent", tool, protocol_version=protocol_version)

    common_terminal = {
        "protocol_version": protocol_version,
        "invocation_id": request["invocation_id"],
        "request_digest": request["request_digest"],
        "last_sequence": 3,
        "usage": fixture["usage"],
        "runtime_provenance": fixture["runtime_provenance"],
        **({"accounting": fixture["accounting"]} if protocol_version >= "1.2" else {}),
    }
    failures = {
        "FAILED": fixture["failure"],
        "CANCELLED": {
            "code": "runtime_cancelled",
            "retry_class": "NEVER",
            "safe_message": "Agent execution cancelled",
        },
        "TIMEOUT": {
            "code": "runtime_timeout",
            "retry_class": "TRANSIENT",
            "safe_message": "Agent execution timed out",
        },
    }
    succeeded = {**common_terminal, "status": "SUCCEEDED", "final_answer": "fixture result"}
    validate_runtime_contract("TerminalResult", succeeded, protocol_version=protocol_version)
    for status, failure in failures.items():
        terminal_status = "FAILED" if status == "TIMEOUT" else status
        terminal = {**common_terminal, "status": terminal_status, "failure": failure}
        validate_runtime_contract("TerminalResult", terminal, protocol_version=protocol_version)

    cancel = {
        "protocol_version": protocol_version,
        "invocation_id": request["invocation_id"],
        "request_digest": request["request_digest"],
        "reason": "WORKER_TIMEOUT",
    }
    validate_runtime_contract("CancelRequest", cancel, protocol_version=protocol_version)


def test_python_accepts_typescript_golden_request_and_digest() -> None:
    request = _request()

    assert canonical_request_digest(request) == request["request_digest"]
    assert validate_execution_request(request) == request


def test_worker_dual_reads_v1_and_v11_while_schemas_remain_strict() -> None:
    request_v1 = _request()
    request_v11 = json.loads(
        (CONTRACT_ROOT_V11 / "golden" / "execution-request.json").read_text(encoding="utf-8")
    )

    assert validate_execution_request(request_v1) == request_v1
    assert validate_execution_request(request_v11) == request_v11
    with pytest.raises(ValueError):
        validate_contract("AgentExecutionRequestV1", request_v11)
    with pytest.raises(ValueError):
        validate_v11_contract("AgentExecutionRequestV11", request_v1)


def test_worker_reads_v12_observability_events_and_keeps_older_minors() -> None:
    request_v12 = json.loads(
        (CONTRACT_ROOT_V12 / "golden" / "execution-request.json").read_text(encoding="utf-8")
    )
    fixture = json.loads(
        (CONTRACT_ROOT_V12 / "golden" / "safe-runtime-fixture.json").read_text(encoding="utf-8")
    )

    assert validate_execution_request(request_v12) == request_v12
    for name in (
        "runtime_initialized_event",
        "model_call_event",
        "api_retry_event",
        "terminal_event",
    ):
        validate_runtime_contract("RuntimeEvent", fixture[name], protocol_version="1.2")


def test_worker_reads_v13_file_policy_and_rejects_log_action_expansion() -> None:
    request = json.loads(
        (CONTRACT_ROOT_V13 / "golden" / "execution-request.json").read_text(encoding="utf-8")
    )
    request["file_context"]["file_manifest"] = {
        "schema_version": 3,
        "file_format_policy_version": "text-v2",
        "manifest_hash": "a" * 64,
        "observed_at": "2026-08-17T00:00:00Z",
        "items": [
            {
                "file_id": "file-log-1",
                "version_id": "version-log-1",
                "display_name": "service.log",
                "format_code": "LOG",
                "source_kind": "CURRENT_MESSAGE",
                "allowed_actions": [
                    "READ_METADATA",
                    "MATERIALIZE",
                    "RETAIN",
                    "DELIVER",
                ],
                "auto_materialize": True,
                "conflict_candidate": False,
                "source_received_at": "2026-08-17T00:00:00Z",
                "version_created_at": "2026-08-17T00:00:00Z",
            }
        ],
    }
    request["request_digest"] = canonical_request_digest(request)
    assert validate_execution_request(request) == request

    forged = copy.deepcopy(request)
    forged["file_context"]["file_manifest"]["items"][0]["allowed_actions"].append("EDIT")
    forged["request_digest"] = canonical_request_digest(forged)
    with pytest.raises(RuntimeProtocolError) as invalid:
        validate_execution_request(forged)
    assert invalid.value.code == "runtime_file_actions_invalid"


def _v13_document_manifest_request() -> dict[str, Any]:
    return json.loads(
        (CONTRACT_ROOT_V13 / "golden" / "execution-request-file-manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_worker_reads_v13_document_manifest_with_markdown_representation() -> None:
    request = _v13_document_manifest_request()
    manifest = request["file_context"]["file_manifest"]

    assert manifest["schema_version"] == 4
    document = next(item for item in manifest["items"] if item["format_code"] == "DOCX")
    assert document["representation_kind"] == "MARKDOWN"
    assert manifest["readability_notices"][0]["status"] == "UNAVAILABLE"
    assert canonical_request_digest(request) == request["request_digest"]
    assert validate_execution_request(request) == request


def test_worker_reads_v13_manifest_readability_notices_and_rejects_unknown_status() -> None:
    request = _v13_document_manifest_request()
    request["file_context"]["file_manifest"]["readability_notices"] = [
        {"file_name": "partial.pdf", "status": "PARTIAL", "error_code": ""},
        {"file_name": "empty.png", "status": "NO_TEXT", "error_code": "docling_no_text"},
    ]
    request["request_digest"] = canonical_request_digest(request)
    assert validate_execution_request(request) == request

    forged = copy.deepcopy(request)
    forged["file_context"]["file_manifest"]["readability_notices"][0]["status"] = "AVAILABLE"
    forged["request_digest"] = canonical_request_digest(forged)
    with pytest.raises(RuntimeProtocolError) as invalid:
        validate_execution_request(forged)
    assert invalid.value.code == "runtime_request_invalid"


def test_worker_rejects_v13_document_item_without_complete_representation() -> None:
    request = _v13_document_manifest_request()
    document = next(
        item
        for item in request["file_context"]["file_manifest"]["items"]
        if item["format_code"] == "DOCX"
    )
    del document["representation_sha256"]
    request["request_digest"] = canonical_request_digest(request)

    with pytest.raises(RuntimeProtocolError) as invalid:
        validate_execution_request(request)
    assert invalid.value.code == "runtime_request_invalid"


def test_worker_rejects_v13_text_item_carrying_document_representation() -> None:
    request = _v13_document_manifest_request()
    items = request["file_context"]["file_manifest"]["items"]
    document = next(item for item in items if item["format_code"] == "DOCX")
    text = next(item for item in items if item["format_code"] == "TXT")
    for field in (
        "representation_id",
        "representation_kind",
        "representation_size_bytes",
        "representation_sha256",
        "representation_format_code",
        "representation_created_at",
    ):
        text[field] = document[field]
    request["request_digest"] = canonical_request_digest(request)

    with pytest.raises(RuntimeProtocolError) as invalid:
        validate_execution_request(request)
    assert invalid.value.code == "runtime_file_representation_invalid"


def test_v13_schema_keeps_representation_fields_out_of_version_three_manifests() -> None:
    request = _v13_document_manifest_request()
    request["file_context"]["file_manifest"]["schema_version"] = 3
    request["request_digest"] = canonical_request_digest(request)

    with pytest.raises(RuntimeProtocolError) as invalid:
        validate_execution_request(request)
    assert invalid.value.code == "runtime_request_invalid"


def test_worker_v11_accepts_exact_origins_and_old_worker_rejects_new_event() -> None:
    fixture = json.loads(
        (CONTRACT_ROOT_V11 / "golden" / "safe-runtime-fixture.json").read_text(encoding="utf-8")
    )
    event = fixture["tool_event"]

    validate_runtime_contract("ToolEvent", event, protocol_version="1.1")
    with pytest.raises(ValueError):
        validate_contract("ToolEvent", event)

    sdk_event = {
        **event,
        "tool_origin": "unknown",
        "server_code": None,
        "mcp_call_id": None,
        "persisted_tool_call_id": None,
    }
    validate_runtime_contract("ToolEvent", sdk_event, protocol_version="1.1")
    validate_runtime_contract(
        "ToolEvent",
        {**event, "server_code": "future-readonly-mcp"},
        protocol_version="1.1",
    )
    with pytest.raises(ValueError):
        validate_runtime_contract(
            "ToolEvent",
            {**sdk_event, "server_code": "tool-mcp"},
            protocol_version="1.1",
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.update({"protocol_version": "2.0"}),
    ],
)
def test_python_contract_rejects_unknown_and_unsupported_fields(mutate: Any) -> None:
    request = _request()
    mutate(request)

    with pytest.raises(ValueError, match="invalid AgentExecutionRequestV1"):
        validate_contract("AgentExecutionRequestV1", request)


def test_python_boundary_rejects_digest_mismatch_and_size_limit() -> None:
    request = _request()
    changed = copy.deepcopy(request)
    changed["prompt"]["user_question"] = "changed after signing"

    with pytest.raises(RuntimeProtocolError) as mismatch:
        validate_execution_request(changed)
    assert mismatch.value.code == "runtime_request_digest_mismatch"

    with pytest.raises(RuntimeProtocolError) as too_large:
        validate_execution_request(request, encoded_bytes=524289)
    assert too_large.value.code == "runtime_request_too_large"


def test_python_validates_stable_safe_runtime_fixture() -> None:
    fixture = json.loads(
        (CONTRACT_ROOT / "golden" / "safe-runtime-fixture.json").read_text(encoding="utf-8")
    )

    validate_contract("ToolEvent", fixture["tool_event"])
    validate_contract("Usage", fixture["usage"])
    validate_contract("RuntimeProvenance", fixture["runtime_provenance"])
    validate_contract("RuntimeFailure", fixture["failure"])
