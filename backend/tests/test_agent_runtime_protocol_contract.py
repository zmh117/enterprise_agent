from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.modules.agent.infrastructure.generated_runtime_contracts_v1_4 import (
    CONTRACT_SCHEMA_SHA256,
    validate_contract,
)
from app.modules.agent.infrastructure.runtime_protocol import (
    RuntimeProtocolError,
    SUPPORTED_RUNTIME_PROTOCOL_VERSIONS,
    canonical_request_digest,
    validate_execution_request,
    validate_runtime_contract,
)
from app.shared.tool_contract import MAX_TOOL_CONTRACT_ITEMS


CONTRACT_ROOT = Path(__file__).parents[2] / "contracts" / "agent-runtime" / "v1.4"


def _request(name: str = "execution-request.json") -> dict[str, object]:
    return json.loads((CONTRACT_ROOT / "golden" / name).read_text(encoding="utf-8"))


def test_only_current_runtime_contract_is_published_and_hash_matches() -> None:
    assert SUPPORTED_RUNTIME_PROTOCOL_VERSIONS == ("1.4",)
    assert hashlib.sha256((CONTRACT_ROOT / "protocol.schema.json").read_bytes()).hexdigest() == (
        CONTRACT_SCHEMA_SHA256
    )
    assert not any((CONTRACT_ROOT.parent / "v1").rglob("*.*"))
    assert not any((CONTRACT_ROOT.parent / "v1.1").rglob("*.*"))
    assert not any((CONTRACT_ROOT.parent / "v1.2").rglob("*.*"))


def test_current_empty_file_context_request_is_valid() -> None:
    request = _request()
    assert request["protocol_version"] == "1.4"
    assert request["runtime_kind"] == "python-v1"
    assert request["file_context"] == {"file_manifest": None}
    assert canonical_request_digest(request) == request["request_digest"]
    assert validate_execution_request(request) == request


def test_current_manifest_is_v5_and_passes_unchanged() -> None:
    request = _request("execution-request-file-manifest.json")
    manifest = request["file_context"]["file_manifest"]
    assert manifest["schema_version"] == 5
    assert manifest["workspace_catalog_revision_id"]
    assert all("materialization_size_bytes" in item for item in manifest["items"])
    assert canonical_request_digest(request) == request["request_digest"]
    assert validate_execution_request(request) == request


def test_non_v5_manifest_is_rejected_without_projection() -> None:
    request = _request("execution-request-file-manifest.json")
    request["file_context"]["file_manifest"]["schema_version"] = 4
    request["request_digest"] = canonical_request_digest(request)
    with pytest.raises(RuntimeProtocolError) as invalid:
        validate_execution_request(request)
    assert invalid.value.code == "runtime_request_invalid"


def test_document_representation_must_be_complete() -> None:
    request = _request("execution-request-file-manifest.json")
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


def test_digest_and_request_size_are_enforced() -> None:
    request = _request()
    changed = copy.deepcopy(request)
    changed["prompt"]["user_question"] = "changed after signing"
    with pytest.raises(RuntimeProtocolError) as mismatch:
        validate_execution_request(changed)
    assert mismatch.value.code == "runtime_request_digest_mismatch"

    with pytest.raises(RuntimeProtocolError) as too_large:
        validate_execution_request(request, encoded_bytes=524289)
    assert too_large.value.code == "runtime_request_too_large"


def test_current_safe_runtime_fixture_covers_runtime_contracts() -> None:
    fixture = json.loads(
        (CONTRACT_ROOT / "golden" / "safe-runtime-fixture.json").read_text(encoding="utf-8")
    )
    keys = {
        "ToolEvent": "tool_event",
        "Usage": "usage",
        "RuntimeProvenance": "runtime_provenance",
        "RuntimeFailure": "failure",
    }
    for name, key in keys.items():
        validate_contract(name, fixture[key])
        validate_runtime_contract(name, fixture[key], protocol_version="1.4")


def test_tool_contract_limits_and_stable_failure_classes_match_runtime() -> None:
    limits = json.loads((CONTRACT_ROOT / "limits.json").read_text(encoding="utf-8"))
    errors = json.loads((CONTRACT_ROOT / "errors.json").read_text(encoding="utf-8"))
    retry_classes = {item["code"]: item["retry_class"] for item in errors["errors"]}

    assert limits["protocol_version"] == "1.4"
    assert limits["max_tool_contract_items"] == MAX_TOOL_CONTRACT_ITEMS == 128
    assert len(retry_classes) == len(errors["errors"])
    assert {
        code: retry_classes[code]
        for code in (
            "runtime_tool_contract_missing_remote",
            "runtime_tool_contract_schema_mismatch",
            "runtime_tool_contract_unauthorized_effective",
            "runtime_tool_contract_prompt_overclaim",
            "runtime_tool_contract_observation_invalid",
            "runtime_tool_contract_build_mismatch",
            "runtime_tool_contract_remote_not_observed",
        )
    } == {
        "runtime_tool_contract_missing_remote": "NEVER",
        "runtime_tool_contract_schema_mismatch": "NEVER",
        "runtime_tool_contract_unauthorized_effective": "NEVER",
        "runtime_tool_contract_prompt_overclaim": "NEVER",
        "runtime_tool_contract_observation_invalid": "NEVER",
        "runtime_tool_contract_build_mismatch": "NEVER",
        "runtime_tool_contract_remote_not_observed": "TRANSIENT",
    }
