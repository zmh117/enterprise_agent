from __future__ import annotations

from dataclasses import replace
import threading

import pytest

from app.modules.agent.domain.runtime import AgentRunRequest, AgentRunResult
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import RetryableExecutionError
from app.workers.agent_job_worker import AgentJobWorker
from app.bootstrap import _acceptance_after_runtime_result_hook
from backend.tests.helpers import container, persisted_agent_job_message


class RecordingRuntimeClient:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(final_answer=request.context.runtime_kind)

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]:
        return {"status": "cancelled", "reason": reason}


class BlockingRuntimeClient:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.released = threading.Event()
        self.cancelled: list[tuple[str, str]] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.started.set()
        self.released.wait(timeout=2)
        raise RetryableExecutionError(
            "Runtime cancelled",
            safe_message="Agent 执行已取消",
            error_code="runtime_cancelled",
        )

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]:
        self.cancelled.append((request.invocation_id, reason))
        self.released.set()
        return {"status": "cancelled", "reason": reason}


def test_after_runtime_pause_hook_is_bounded_and_test_only(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_ACCEPTANCE_AFTER_RESULT_PAUSE_SECONDS", "3")
    with pytest.raises(RuntimeError, match="test-only"):
        _acceptance_after_runtime_result_hook("production")

    pauses: list[float] = []
    monkeypatch.setattr("app.bootstrap.time.sleep", pauses.append)
    hook = _acceptance_after_runtime_result_hook("testing")
    assert hook is not None
    hook()
    assert pauses == [3.0]

    monkeypatch.setenv("AGENT_RUNTIME_ACCEPTANCE_AFTER_RESULT_PAUSE_SECONDS", "61")
    with pytest.raises(RuntimeError, match="between 1 and 60"):
        _acceptance_after_runtime_result_hook("testing")


def _runtime_with_project_permission():
    runtime = container(allow_direct_jobs=True)
    runtime.create_agent_job_service.published_agent_runtime_enabled = True
    runtime.create_agent_job_service.runtime_readiness_guard = None
    return runtime


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
        "payload": {"runtime_kind": "python-v1"},
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
            {**event, "payload": {"runtime_kind": "typescript-v1"}},
        )
    assert getattr(conflict.value, "error_code", "") == "runtime_event_digest_conflict"


def test_redelivered_running_job_reuses_same_runtime_and_invocation() -> None:
    runtime = _runtime_with_project_permission()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="runtime-redelivery-recovery",
            requester_id="user_local_admin",
            user_message="diagnose",
            source_channel="debug_api",
        )
    )
    assert runtime.agent_repository.claim_job(job.id, "worker-before-crash") is not None
    client = RecordingRuntimeClient()
    runtime.agent_executor.runtime_client = client  # type: ignore[assignment]
    message = replace(persisted_agent_job_message(runtime, job.id), redelivered=True)

    AgentJobWorker(runtime.settings, container=runtime).handle(message)

    persisted = runtime.agent_repository.get_job(job.id)
    assert persisted.status == JobStatus.SUCCEEDED
    assert persisted.result == "python-v1"
    assert [request.context.runtime_kind for request in client.requests] == ["python-v1"]
    assert [request.invocation_id for request in client.requests] == [f"{job.id}.attempt-0"]


def test_job_cancel_and_worker_shutdown_target_the_same_frozen_invocation() -> None:
    runtime = _runtime_with_project_permission()
    first = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="runtime-job-cancel",
            requester_id="user_local_admin",
            user_message="cancel this job",
            source_channel="debug_api",
        )
    )
    client = BlockingRuntimeClient()
    runtime.agent_executor.runtime_client = client  # type: ignore[assignment]
    errors: list[BaseException] = []

    def execute_first() -> None:
        try:
            runtime.agent_executor.execute(first.id, fail_on_error=False)
        except BaseException as exc:  # noqa: BLE001 - thread assertion capture
            errors.append(exc)

    thread = threading.Thread(target=execute_first)
    thread.start()
    assert client.started.wait(timeout=1)
    assert runtime.agent_executor.cancel_active(first.id, "JOB_CANCELLED") is True
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert isinstance(errors[0], RetryableExecutionError)
    assert client.cancelled == [(f"{first.id}.attempt-0", "JOB_CANCELLED")]

    second = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="runtime-worker-shutdown",
            requester_id="user_local_admin",
            user_message="shutdown while running",
            source_channel="debug_api",
        )
    )
    shutdown_client = BlockingRuntimeClient()
    runtime.agent_executor.runtime_client = shutdown_client  # type: ignore[assignment]
    worker = AgentJobWorker(runtime.settings, container=runtime)
    worker_thread = threading.Thread(
        target=worker.handle,
        args=(persisted_agent_job_message(runtime, second.id),),
    )
    worker_thread.start()
    assert shutdown_client.started.wait(timeout=1)
    assert worker.request_shutdown() is True
    worker_thread.join(timeout=2)
    assert not worker_thread.is_alive()
    assert shutdown_client.cancelled == [(f"{second.id}.attempt-0", "WORKER_SHUTDOWN")]
