from __future__ import annotations

import json
from pathlib import Path

from app.modules.agent.infrastructure.generated_runtime_contracts import validate_contract
from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest


GOLDEN = Path("contracts/agent-runtime/v1/golden")


def test_python_and_historical_typescript_facts_keep_contract_semantics() -> None:
    base_request = json.loads((GOLDEN / "execution-request.json").read_text(encoding="utf-8"))
    safe = json.loads((GOLDEN / "safe-runtime-fixture.json").read_text(encoding="utf-8"))

    # TypeScript remains a read-only historical enum value so persisted events
    # stay verifiable after the implementation is removed.
    for runtime_kind, sdk_version in (
        ("python-v1", "0.2.134"),
        ("typescript-v1", "0.3.226"),
    ):
        request = {**base_request, "runtime_kind": runtime_kind}
        request["request_digest"] = canonical_request_digest(request)
        validate_contract("AgentExecutionRequestV1", request)

        provenance = {
            **safe["runtime_provenance"],
            "runtime_kind": runtime_kind,
            "sdk_version": sdk_version,
        }
        validate_contract("RuntimeProvenance", provenance)

        terminal_base = {
            "protocol_version": "1.0",
            "invocation_id": request["invocation_id"],
            "request_digest": request["request_digest"],
            "last_sequence": 4,
            "usage": safe["usage"],
            "runtime_provenance": provenance,
        }
        for terminal in (
            {**terminal_base, "status": "SUCCEEDED", "final_answer": "safe result"},
            {**terminal_base, "status": "FAILED", "failure": safe["failure"]},
            {
                **terminal_base,
                "status": "CANCELLED",
                "failure": {
                    "code": "runtime_cancelled",
                    "retry_class": "NEVER",
                    "safe_message": "Agent 执行已取消",
                },
            },
        ):
            validate_contract("TerminalResult", terminal)

        events = (
            ("execution_started", provenance),
            ("tool_event", safe["tool_event"]),
            ("assistant_text", {"text": "bounded diagnostic"}),
            (
                "terminal",
                {**terminal_base, "status": "SUCCEEDED", "final_answer": "safe result"},
            ),
        )
        for sequence, (event_type, payload) in enumerate(events, start=1):
            validate_contract(
                "RuntimeEvent",
                {
                    "protocol_version": "1.0",
                    "invocation_id": request["invocation_id"],
                    "request_digest": request["request_digest"],
                    "sequence": sequence,
                    "event_type": event_type,
                    "timestamp": "2026-08-11T00:00:00Z",
                    "payload": payload,
                },
            )
