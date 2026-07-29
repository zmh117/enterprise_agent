from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.modules.agent.domain.runtime import AgentRunResult
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.job_dispatch_service import JobDispatchOutboxDispatcher
from app.modules.job.domain.job_dispatch import JobDispatchStatus
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import container


def _create_job(runtime: object, key: str):
    return runtime.create_agent_job_service.execute(  # type: ignore[attr-defined]
        CreateAgentJobCommand(
            idempotency_key=key,
            requester_id="local-user",
            external_conversation_id=f"debug-{key}",
            user_message="dispatch this durable job",
            project_code="default",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            reply_route={"type": "none"},
            correlation_id=f"correlation-{key}",
        )
    )


def test_dispatcher_publishes_only_before_recording_confirmed_state() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-success")
        assert runtime.message_bus is not None
        assert not runtime.message_bus.jobs

        result = runtime.job_dispatcher.publish_pending(limit=10)

        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        assert result.published == 1
        assert result.failed == 0
        assert event.status == JobDispatchStatus.PUBLISHED
        assert event.attempt_count == 1
        assert event.published_at
        assert [message.job_id for message in runtime.message_bus.jobs] == [job.id]
        assert set(vars(runtime.message_bus.jobs[0])) == {
            "event_id",
            "job_id",
            "correlation_id",
        }
        assert runtime.message_bus.jobs[0].event_id == event.id
        assert "queue.dispatched" in {
            row["event_type"]
            for row in runtime.audit_repository.list_for_job(job.id)
        }
    finally:
        runtime.database.close()


def test_worker_rejects_tampered_identifiers_and_loads_persisted_dispatch_facts() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-facts")
        runtime.job_dispatcher.publish_pending(limit=1)
        assert runtime.message_bus is not None
        message = runtime.message_bus.jobs.popleft()
        worker = AgentJobWorker(runtime.settings, container=runtime)

        worker.handle(
            AgentJobMessage(
                event_id=message.event_id,
                job_id="job_attacker_selected",
                correlation_id=message.correlation_id,
            )
        )

        assert runtime.agent_repository.get_job(job.id).status == JobStatus.PENDING
        rejected = [
            row
            for row in runtime.audit_repository.list_for_job(job.id)
            if row["event_type"] == "job.dispatch.message_rejected"
        ]
        assert len(rejected) == 1
        assert "job_attacker_selected" not in str(rejected)

        worker.handle(message)
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
    finally:
        runtime.database.close()


class _BlockingAgentClient:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()
        self.calls = 0

    def run(self, request: object) -> AgentRunResult:
        del request
        with self._lock:
            self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release blocking Agent client")
        return AgentRunResult(final_answer="single durable result")


def test_duplicate_messages_concurrently_claim_and_execute_job_only_once() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-concurrent-duplicate")
        runtime.job_dispatcher.publish_pending(limit=1)
        assert runtime.message_bus is not None
        message = runtime.message_bus.jobs.popleft()
        client = _BlockingAgentClient()
        runtime.agent_executor.claude_client = client  # type: ignore[assignment]
        worker = AgentJobWorker(runtime.settings, container=runtime)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(worker.handle, message)
            assert client.started.wait(timeout=5)
            duplicate = executor.submit(worker.handle, message)
            duplicate.result(timeout=5)
            client.release.set()
            first.result(timeout=5)

        worker.handle(message)
        persisted = runtime.agent_repository.get_job(job.id)
        claimed_audits = [
            row
            for row in runtime.audit_repository.list_for_job(job.id)
            if row["event_type"] == "worker.claimed"
        ]

        assert persisted.status == JobStatus.SUCCEEDED
        assert persisted.result == "single durable result"
        assert client.calls == 1
        assert len(claimed_audits) == 1
    finally:
        runtime.database.close()


class _SecretLeakingFailurePublisher:
    def publish_agent_job(
        self,
        event_id: str,
        job_id: str,
        correlation_id: str,
    ) -> None:
        del event_id, job_id, correlation_id
        raise RuntimeError(
            "amqp://admin:plain-secret@broker/vhost?access_token=should-not-persist"
        )


def test_dispatcher_uses_finite_backoff_and_safe_dead_state() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-dead")
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        runtime.database.execute(
            "update job_dispatch_outbox set max_attempts = 2 where id = ?",
            (event.id,),
        )
        dispatcher = JobDispatchOutboxDispatcher(
            repository=runtime.agent_repository,
            publisher=_SecretLeakingFailurePublisher(),
            audit_service=runtime.audit_service,
            settings=runtime.settings.queue,
            worker_id="failure-test-dispatcher",
        )

        first = dispatcher.publish_pending(limit=1)
        retrying = runtime.agent_repository.get_dispatch_event(event.id)
        assert first.failed == 1
        assert first.dead == 0
        assert retrying.status == JobDispatchStatus.RETRY_WAIT
        assert retrying.attempt_count == 1
        assert retrying.last_error_code == "publisher_runtimeerror"
        assert retrying.last_error_summary == "Message bus publish failed (RuntimeError)"

        runtime.database.execute(
            "update job_dispatch_outbox set next_attempt_at = ? where id = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), event.id),
        )
        second = dispatcher.publish_pending(limit=1)
        dead = runtime.agent_repository.get_dispatch_event(event.id)

        assert second.failed == 1
        assert second.dead == 1
        assert dead.status == JobDispatchStatus.DEAD
        assert dead.attempt_count == 2
        assert dead.dead_at
        persisted = str(
            {
                "event": dead,
                "audits": runtime.audit_repository.list_for_job(job.id),
                "metrics": dispatcher.metrics(),
            }
        )
        assert "plain-secret" not in persisted
        assert "access_token" not in persisted
        assert dispatcher.publish_pending(limit=10).published == 0
    finally:
        runtime.database.close()


def test_dispatch_claim_has_single_owner_and_recovers_stale_owner() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-owner")
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None

        claimed = runtime.agent_repository.claim_dispatch_event(worker_id="worker-a")
        duplicate = runtime.agent_repository.claim_dispatch_event(worker_id="worker-b")

        assert claimed is not None
        assert claimed.id == event.id
        assert claimed.status == JobDispatchStatus.RUNNING
        assert claimed.attempt_count == 1
        assert duplicate is None
        assert not runtime.agent_repository.mark_dispatch_published(
            event_id=event.id,
            worker_id="worker-b",
        )

        stale_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        runtime.database.execute(
            "update job_dispatch_outbox set claimed_at = ? where id = ?",
            (stale_at, event.id),
        )
        recovered, dead = runtime.agent_repository.recover_stale_dispatch_claims(
            stale_before=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        )
        state = runtime.agent_repository.get_dispatch_event(event.id)

        assert (recovered, dead) == (1, 0)
        assert state.status == JobDispatchStatus.RETRY_WAIT
        assert state.claimed_by == ""
        assert state.last_error_code == "job_dispatch_claim_expired"
    finally:
        runtime.database.close()
