from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.agent.infrastructure.generated_runtime_contracts import validate_contract
from app.modules.agent.infrastructure.runtime_protocol import (
    RuntimeProtocolError,
    canonical_request_digest,
    validate_execution_request,
)


CONTRACT_ROOT = Path(__file__).parents[2] / "agent-runtime" / "contracts" / "v1"


def _request() -> dict[str, Any]:
    return json.loads(
        (CONTRACT_ROOT / "golden" / "execution-request.json").read_text(encoding="utf-8")
    )


def test_python_accepts_typescript_golden_request_and_digest() -> None:
    request = _request()

    assert canonical_request_digest(request) == request["request_digest"]
    assert validate_execution_request(request) == request


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
