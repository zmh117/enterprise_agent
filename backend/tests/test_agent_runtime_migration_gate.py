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
from app.shared.config import AgentRuntimeSettings
from app.shared.exceptions import RetryableExecutionError
from app.workers.agent_job_worker import AgentJobWorker
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


def _runtime_with_project_permission():
    runtime = container()
    runtime.create_agent_job_service.capability_publication_repository = None
    runtime.database.execute(
        """
        insert into permission_policy
          (id, subject_type, subject_code, resource_type, resource_code,
           effect, action, status, priority, revision, created_at, updated_at)
        values ('test-runtime-user-project', 'user', 'user_local_admin',
                'project', 'default', 'allow', 'use', 'enabled', 1, 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """
    )
    return runtime


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


def test_dual_runtimes_are_retained_and_python_is_the_default() -> None:
    gate = RuntimeMigrationGate(AgentRuntimeSettings())
    selection = gate.select(
        environment="production",
        application_publication_id="app-pub-without-typescript-gate",
    )
    assert selection.runtime_kind == PYTHON_RUNTIME

    python_client = _RecordingClient()
    typescript_client = _RecordingClient()
    router = RoutedAgentRuntimeClient(
        python_client=python_client,
        typescript_client=typescript_client,
    )

    assert router.run(_request(PYTHON_RUNTIME, invocation_id="job-python.attempt-0")).final_answer == (
        PYTHON_RUNTIME
    )
    assert router.run(
        _request(TYPESCRIPT_RUNTIME, invocation_id="job-typescript.attempt-0")
    ).final_answer == TYPESCRIPT_RUNTIME
    assert len(python_client.requests) == 1
    assert len(typescript_client.requests) == 1


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


def test_job_creation_freezes_gate_selection_and_protocol() -> None:
    runtime = _runtime_with_project_permission()
    runtime.create_agent_job_service.runtime_migration_gate = RuntimeMigrationGate(
        AgentRuntimeSettings(typescript_environments=("test",))
    )
    runtime.create_agent_job_service.runtime_environment = "test"
    command = CreateAgentJobCommand(
        idempotency_key="runtime-freeze-job",
        requester_id="user_local_admin",
        user_message="diagnose",
        source_channel="debug_api",
        business_application_publication_id="app-pub-canary",
    )

    created = runtime.create_agent_job_service.execute(command)
    runtime.create_agent_job_service.runtime_migration_gate = RuntimeMigrationGate(
        AgentRuntimeSettings()
    )
    persisted = runtime.create_agent_job_service.execute(command)

    assert created.id == persisted.id
    assert persisted.agent_runtime_kind == TYPESCRIPT_RUNTIME
    assert persisted.agent_runtime_protocol_version == "1.0"


def test_runtime_event_repository_is_idempotent_and_rejects_gap_or_conflict() -> None:
    runtime = _runtime_with_project_permission()
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


def test_redelivered_typescript_job_reclaims_same_attempt_without_python_fallback() -> None:
    runtime = _runtime_with_project_permission()
    runtime.create_agent_job_service.runtime_migration_gate = RuntimeMigrationGate(
        AgentRuntimeSettings(typescript_environments=("test",))
    )
    runtime.create_agent_job_service.runtime_environment = "test"
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="runtime-redelivery-recovery",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
            business_application_publication_id="app-pub-canary",
        )
    )
    assert runtime.agent_repository.claim_job(job.id, "worker-before-crash") is not None
    client = _RecordingClient()
    runtime.agent_executor.claude_client = client  # type: ignore[assignment]
    message = replace(persisted_agent_job_message(runtime, job.id), redelivered=True)

    AgentJobWorker(runtime.settings, container=runtime).handle(message)

    persisted = runtime.agent_repository.get_job(job.id)
    assert persisted.status == JobStatus.SUCCEEDED
    assert persisted.result == TYPESCRIPT_RUNTIME
    assert [request.invocation_id for request in client.requests] == [f"{job.id}.attempt-0"]


def test_redelivered_python_running_job_is_not_replayed() -> None:
    runtime = _runtime_with_project_permission()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="python-runtime-redelivery-no-replay",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
        )
    )
    assert runtime.agent_repository.claim_job(job.id, "active-python-worker") is not None
    client = _RecordingClient()
    runtime.agent_executor.claude_client = client  # type: ignore[assignment]
    message = replace(persisted_agent_job_message(runtime, job.id), redelivered=True)

    AgentJobWorker(runtime.settings, container=runtime).handle(message)

    assert runtime.agent_repository.get_job(job.id).status == JobStatus.RUNNING
    assert client.requests == []
