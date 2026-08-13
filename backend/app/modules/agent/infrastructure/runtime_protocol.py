from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from app.modules.agent.infrastructure.generated_runtime_contracts import (
    AgentExecutionRequestV1,
    CONTRACT_SCHEMA_PATH,
    validate_contract as validate_v1_contract,
)
from app.modules.agent.infrastructure.generated_runtime_contracts_v1_1 import (
    AgentExecutionRequestV11,
    CONTRACT_SCHEMA_PATH as CONTRACT_SCHEMA_PATH_V11,
    validate_contract as validate_v11_contract,
)
from app.modules.agent.infrastructure.generated_runtime_contracts_v1_2 import (
    AgentExecutionRequestV12,
    CONTRACT_SCHEMA_PATH as CONTRACT_SCHEMA_PATH_V12,
    validate_contract as validate_v12_contract,
)

CURRENT_RUNTIME_PROTOCOL_VERSION = "1.2"
SUPPORTED_RUNTIME_PROTOCOL_VERSIONS = (
    "1.0",
    "1.1",
    CURRENT_RUNTIME_PROTOCOL_VERSION,
)


class RuntimeProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_request_digest(payload: dict[str, Any]) -> str:
    digest_input = dict(payload)
    digest_input.pop("request_digest", None)
    serialized = json.dumps(
        digest_input,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def validate_execution_request(
    payload: object,
    *,
    encoded_bytes: int | None = None,
) -> AgentExecutionRequestV1 | AgentExecutionRequestV11 | AgentExecutionRequestV12:
    protocol_version = _protocol_version(payload)
    contract_path = {
        "1.0": CONTRACT_SCHEMA_PATH,
        "1.1": CONTRACT_SCHEMA_PATH_V11,
        "1.2": CONTRACT_SCHEMA_PATH_V12,
    }[protocol_version]
    limits_path = contract_path.with_name("limits.json")
    limits = json.loads(limits_path.read_text(encoding="utf-8"))
    size = encoded_bytes
    if size is None:
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > int(limits["max_request_bytes"]):
        raise RuntimeProtocolError(
            "runtime_request_too_large",
            f"request is {size} bytes; maximum is {limits['max_request_bytes']}",
        )
    try:
        request_contract = {
            "1.0": "AgentExecutionRequestV1",
            "1.1": "AgentExecutionRequestV11",
            "1.2": "AgentExecutionRequestV12",
        }[protocol_version]
        validate_runtime_contract(
            request_contract,
            payload,
            protocol_version=protocol_version,
        )
    except ValueError as exc:
        raise RuntimeProtocolError("runtime_request_invalid", str(exc)) from exc
    assert isinstance(payload, dict)
    actual = canonical_request_digest(payload)
    if actual != payload["request_digest"]:
        raise RuntimeProtocolError(
            "runtime_request_digest_mismatch",
            "request digest does not match the canonical request body",
        )
    return cast(
        AgentExecutionRequestV1 | AgentExecutionRequestV11 | AgentExecutionRequestV12,
        payload,
    )


def validate_runtime_contract(
    definition_name: str,
    payload: object,
    *,
    protocol_version: str | None = None,
) -> None:
    version = protocol_version or _protocol_version(payload)
    if version == "1.2":
        validate_v12_contract(definition_name, payload)
        return
    if version == "1.1":
        validate_v11_contract(definition_name, payload)
        return
    if version == "1.0":
        validate_v1_contract(definition_name, payload)
        return
    raise ValueError(f"unsupported runtime protocol version: {version}")


def _protocol_version(payload: object) -> str:
    if isinstance(payload, dict):
        value = payload.get("protocol_version")
        if value in SUPPORTED_RUNTIME_PROTOCOL_VERSIONS:
            return str(value)
    return "1.0"
