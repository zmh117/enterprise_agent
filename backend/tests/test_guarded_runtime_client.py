from __future__ import annotations

import pytest

from app.modules.agent.application.runtime_client import GuardedAgentRuntimeClient
from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    AgentRunResult,
)
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


class RunOnlyRuntimeClient:
    def run(self, request: AgentRunRequest) -> AgentRunResult:
        return AgentRunResult(final_answer=request.job_id)


def request(runtime_kind: str, protocol: str = "1.5") -> AgentRunRequest:
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


def test_guard_delegates_only_current_python_runtime() -> None:
    python = RecordingRuntimeClient("python")
    client = GuardedAgentRuntimeClient(python)

    assert client.run(request("python-v1")).final_answer == "python"
    assert len(python.requests) == 1
    for _attempt in range(2):
        with pytest.raises(NonRetryableExecutionError) as retired:
            client.run(request("typescript-v1"))
        assert retired.value.error_code == "agent_runtime_kind_unsupported"
    assert len(python.requests) == 1


def test_guard_rejects_unknown_unconfigured_and_protocol_conflicts() -> None:
    client = GuardedAgentRuntimeClient(RecordingRuntimeClient("python"))

    expected = [
        (request("ruby-v1"), "agent_runtime_kind_unsupported"),
        (request("typescript-v1"), "agent_runtime_kind_unsupported"),
        (request("python-v1", "2.0"), "agent_runtime_protocol_unsupported"),
    ]
    for value, code in expected:
        with pytest.raises(NonRetryableExecutionError) as raised:
            client.run(value)
        assert raised.value.error_code == code

    with pytest.raises(NonRetryableExecutionError) as unconfigured:
        GuardedAgentRuntimeClient(None).run(request("python-v1"))
    assert unconfigured.value.error_code == "agent_runtime_unconfigured"


def test_guard_preserves_cancel_capability_error() -> None:
    client = GuardedAgentRuntimeClient(RunOnlyRuntimeClient())  # type: ignore[arg-type]

    with pytest.raises(NonRetryableExecutionError) as raised:
        client.cancel(request("python-v1"), "JOB_CANCELLED")

    assert raised.value.error_code == "agent_runtime_cancel_unavailable"
