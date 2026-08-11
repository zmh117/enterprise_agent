from __future__ import annotations

import pytest

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    AgentRunResult,
)
from app.modules.agent.infrastructure.routed_runtime_client import RuntimeClientRegistry
from app.shared.exceptions import NonRetryableExecutionError


class RecordingRuntimeClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(final_answer=self.answer)

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]:
        self.requests.append(request)
        return {"status": "cancelled", "reason": reason}


def request(runtime_kind: str, protocol: str = "1.0") -> AgentRunRequest:
    return AgentRunRequest(
        job_id="job-1",
        user_id="user-1",
        project_code="project-1",
        context=AgentExecutionContext(
            system_role="readonly",
            safety_rules=[],
            user_question="question",
            project_code="project-1",
            allowed_tools=[],
            tool_restrictions=[],
            skills={},
            retrieved_context={},
            conversation_summary="",
            runtime_kind=runtime_kind,
            runtime_protocol_version=protocol,
        ),
    )


def test_registry_routes_only_by_frozen_runtime_kind_without_fallback() -> None:
    python = RecordingRuntimeClient("python")
    typescript = RecordingRuntimeClient("typescript")
    registry = RuntimeClientRegistry(
        {"python-v1": python, "typescript-v1": typescript}
    )

    assert registry.run(request("python-v1")).final_answer == "python"
    assert registry.run(request("typescript-v1")).final_answer == "typescript"
    assert len(python.requests) == 1
    assert len(typescript.requests) == 1


def test_registry_rejects_unknown_unconfigured_and_protocol_conflicts() -> None:
    registry = RuntimeClientRegistry({"python-v1": RecordingRuntimeClient("python")})

    expected = [
        (request("ruby-v1"), "agent_runtime_kind_unsupported"),
        (request("typescript-v1"), "agent_runtime_unconfigured"),
        (request("python-v1", "2.0"), "agent_runtime_protocol_unsupported"),
    ]
    for value, code in expected:
        with pytest.raises(NonRetryableExecutionError) as raised:
            registry.run(value)
        assert raised.value.error_code == code

    with pytest.raises(ValueError):
        RuntimeClientRegistry({"runtime-from-request-url": RecordingRuntimeClient("bad")})
