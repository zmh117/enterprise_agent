from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from app.modules.agent.infrastructure.generated_runtime_contracts import (
    AgentExecutionRequestV1,
    CONTRACT_SCHEMA_PATH,
    validate_contract,
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
) -> AgentExecutionRequestV1:
    limits_path = CONTRACT_SCHEMA_PATH.with_name("limits.json")
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
        validate_contract("AgentExecutionRequestV1", payload)
    except ValueError as exc:
        raise RuntimeProtocolError("runtime_request_invalid", str(exc)) from exc
    assert isinstance(payload, dict)
    actual = canonical_request_digest(payload)
    if actual != payload["request_digest"]:
        raise RuntimeProtocolError(
            "runtime_request_digest_mismatch",
            "request digest does not match the canonical request body",
        )
    return cast(AgentExecutionRequestV1, payload)
