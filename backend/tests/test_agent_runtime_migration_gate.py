from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.agent.application.runtime_migration_gate import (
    PYTHON_RUNTIME,
    TYPESCRIPT_RUNTIME,
    RuntimeMigrationGate,
)
from app.modules.agent.domain.runtime import AgentExecutionContext, AgentRunRequest, AgentRunResult
from app.modules.agent.infrastructure.routed_runtime_client import RoutedAgentRuntimeClient
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.workers.agent_job_worker import AgentJobWorker
from app.shared.config import AgentRuntimeSettings
from app.shared.exceptions import RetryableExecutionError
from backend.tests.helpers import container, persisted_agent_job_message


class _RecordingClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.requests: list[AgentRunRequest] = []
        self.failure = failure

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return AgentRunResult(final_answer=request.context.runtime_kind)


class _CancellableRecordingClient(_RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled: list[tuple[AgentRunRequest, str]] = []

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, str]:
        self.cancelled.append((request, reason))
        return {"status": "cancelled"}


def _request(runtime_kind: str, *, invocation_id: str) -> AgentRunRequest:
    return AgentRunRequest(
        job_id="job-1",
        user_id="user-1",
        project_code="default",
        invocation_id=invocation_id,
        context=AgentExecutionContext(
            system_role="readonly",
            safety_rules=[],
            user_question="question",
            project_code="default",
            allowed_tools=[],
            tool_restrictions=[],
            skills={},
            retrieved_context={},
            conversation_summary="",
            runtime_kind=runtime_kind,
        ),
    )


def test_gate_selects_typescript_only_for_explicit_environment_or_publication() -> None:
    gate = RuntimeMigrationGate(
        AgentRuntimeSettings(
            typescript_environments=("test",),
            typescript_application_publication_ids=("app-pub-canary",),
        )
    )

    assert (
        gate.select(environment="production", application_publication_id="app-pub-1").runtime_kind
        == PYTHON_RUNTIME
    )
    assert (
        gate.select(environment="test", application_publication_id="app-pub-1").runtime_kind
        == TYPESCRIPT_RUNTIME
    )
    assert (
        gate.select(
            environment="production", application_publication_id="app-pub-canary"
        ).runtime_kind
        == TYPESCRIPT_RUNTIME
    )
    assert (
        gate.select(environment="test", application_publication_id="").runtime_kind
        == PYTHON_RUNTIME
    )


def test_router_never_falls_back_and_retry_keeps_the_frozen_runtime() -> None:
    python_client = _RecordingClient()
    typescript_client = _RecordingClient(
        failure=RetryableExecutionError(
            "runtime transport failed",
            safe_message="Runtime 通信失败",
            error_code="runtime_transport_error",
        )
    )
    router = RoutedAgentRuntimeClient(
        python_client=python_client,
        typescript_client=typescript_client,
    )

    with pytest.raises(RetryableExecutionError):
        router.run(_request(TYPESCRIPT_RUNTIME, invocation_id="job-1.attempt-0"))
    with pytest.raises(RetryableExecutionError):
        router.run(_request(TYPESCRIPT_RUNTIME, invocation_id="job-1.attempt-1"))

    assert len(typescript_client.requests) == 2
    assert python_client.requests == []


def test_router_cancel_targets_only_the_frozen_typescript_runtime() -> None:
    python_client = _CancellableRecordingClient()
    typescript_client = _CancellableRecordingClient()
    router = RoutedAgentRuntimeClient(
        python_client=python_client,
        typescript_client=typescript_client,
    )
    value = _request(TYPESCRIPT_RUNTIME, invocation_id="job-1.attempt-0")

    assert router.cancel(value, "JOB_CANCELLED") == {"status": "cancelled"}
    assert typescript_client.cancelled == [(value, "JOB_CANCELLED")]
    assert python_client.cancelled == []


def test_job_creation_freezes_runtime_kind_and_protocol() -> None:
    runtime = container()
    command = CreateAgentJobCommand(
        idempotency_key="runtime-freeze-job",
        requester_id="user_local_admin",
        user_message="diagnose",
        source_channel="debug_api",
        agent_runtime_kind=TYPESCRIPT_RUNTIME,
        agent_runtime_protocol_version="1.0",
    )

    created = runtime.create_agent_job_service.execute(command)
    persisted = runtime.agent_repository.get_job(created.id)

    assert persisted.agent_runtime_kind == TYPESCRIPT_RUNTIME
    assert persisted.agent_runtime_protocol_version == "1.0"
    assert runtime.create_agent_job_service.execute(replace(command)).id == created.id


def test_runtime_event_repository_is_idempotent_and_rejects_gap_or_conflict() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="runtime-event-job",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
        )
    )
    event = {
        "invocation_id": f"{job.id}.attempt-0",
        "request_digest": "a" * 64,
        "sequence": 1,
        "event_type": "execution_started",
        "payload": {"runtime_kind": TYPESCRIPT_RUNTIME},
    }

    runtime.agent_repository.record_runtime_event(job.id, event)
    runtime.agent_repository.record_runtime_event(job.id, event)
    assert len(runtime.agent_repository.list_runtime_events(job.id)) == 1

    with pytest.raises(Exception) as gap:
        runtime.agent_repository.record_runtime_event(
            job.id,
            {**event, "sequence": 3, "event_type": "terminal"},
        )
    assert getattr(gap.value, "error_code", "") == "runtime_event_sequence_gap"

    with pytest.raises(Exception) as conflict:
        runtime.agent_repository.record_runtime_event(
            job.id,
            {**event, "payload": {"runtime_kind": PYTHON_RUNTIME}},
        )
    assert getattr(conflict.value, "error_code", "") == "runtime_event_digest_conflict"


def test_redelivered_typescript_job_reclaims_running_attempt_with_same_invocation() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="runtime-redelivery-recovery",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
            agent_runtime_kind=TYPESCRIPT_RUNTIME,
            agent_runtime_protocol_version="1.0",
        )
    )
    claimed = runtime.agent_repository.claim_job(job.id, "worker-before-crash")
    assert claimed is not None
    client = _RecordingClient()
    runtime.agent_executor.claude_client = client  # type: ignore[assignment]
    message = replace(persisted_agent_job_message(runtime, job.id), redelivered=True)

    AgentJobWorker(runtime.settings, container=runtime).handle(message)

    persisted = runtime.agent_repository.get_job(job.id)
    assert persisted.status == JobStatus.SUCCEEDED
    assert persisted.result == TYPESCRIPT_RUNTIME
    assert [request.invocation_id for request in client.requests] == [f"{job.id}.attempt-0"]


def test_redelivered_python_running_job_is_not_replayed() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="python-runtime-redelivery-no-replay",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
            agent_runtime_kind=PYTHON_RUNTIME,
            agent_runtime_protocol_version="1.0",
        )
    )
    assert runtime.agent_repository.claim_job(job.id, "active-python-worker") is not None
    client = _RecordingClient()
    runtime.agent_executor.claude_client = client  # type: ignore[assignment]
    message = replace(persisted_agent_job_message(runtime, job.id), redelivered=True)

    AgentJobWorker(runtime.settings, container=runtime).handle(message)

    assert runtime.agent_repository.get_job(job.id).status == JobStatus.RUNNING
    assert client.requests == []


def test_running_typescript_job_is_terminal_only_after_runtime_cancel_ack() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="typescript-runtime-job-cancel",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
            agent_runtime_kind=TYPESCRIPT_RUNTIME,
            agent_runtime_protocol_version="1.0",
        )
    )
    assert runtime.agent_repository.claim_job(job.id, "active-worker") is not None
    client = _CancellableRecordingClient()
    runtime.agent_executor.claude_client = client  # type: ignore[assignment]

    cancelled = runtime.agent_executor.cancel(
        job.id,
        actor_id="operations-user",
        reason="JOB_CANCELLED",
    )

    assert cancelled.status == JobStatus.CANCELLED
    assert len(client.cancelled) == 1
    request, reason = client.cancelled[0]
    assert request.invocation_id == f"{job.id}.attempt-0"
    assert request.context.runtime_kind == TYPESCRIPT_RUNTIME
    assert reason == "JOB_CANCELLED"


def test_pending_job_cancel_does_not_contact_runtime() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="pending-job-cancel",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
            agent_runtime_kind=TYPESCRIPT_RUNTIME,
            agent_runtime_protocol_version="1.0",
        )
    )
    client = _CancellableRecordingClient()
    runtime.agent_executor.claude_client = client  # type: ignore[assignment]

    cancelled = runtime.agent_executor.cancel(job.id, actor_id="operations-user")

    assert cancelled.status == JobStatus.CANCELLED
    assert client.cancelled == []
