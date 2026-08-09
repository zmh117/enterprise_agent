from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.agent.domain.runtime import AgentRunResult
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.job_dispatch_service import JobDispatchOutboxDispatcher
from app.modules.job.domain.job_dispatch import JobDispatchStatus
from app.modules.job.domain.job_status import JobStatus
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import container


def _create_job(runtime: object, key: str):
    return runtime.create_agent_job_service.execute(  # type: ignore[attr-defined]
        CreateAgentJobCommand(
            idempotency_key=key,
            requester_id="local-user",
            external_conversation_id=f"debug-{key}",
            user_message="fault integration dispatch",
            project_code="default",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            reply_route={"type": "none"},
            correlation_id=f"correlation-{key}",
        )
    )


def test_database_commit_failure_rolls_back_job_message_and_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = container()
    original = runtime.agent_repository.create_dispatch_event

    def defer_invalid_foreign_key(**kwargs: object) -> object:
        event = original(**kwargs)  # type: ignore[arg-type]
        timestamp = datetime.now(UTC).isoformat()
        runtime.database.execute("pragma defer_foreign_keys = on")
        runtime.database.execute(
            """
            insert into job_dispatch_outbox
              (id, event_key, idempotency_key, job_id, correlation_id,
               next_attempt_at, created_at, updated_at)
            values ('job_dispatch_commit_failure',
                    'job.dispatch:commit-failure-invalid',
                    'job.dispatch:commit-failure-invalid',
                    'missing-job-for-deferred-fk',
                    'correlation-commit-failure',
                    ?, ?, ?)
            """,
            (timestamp, timestamp, timestamp),
        )
        return event

    monkeypatch.setattr(
        runtime.agent_repository,
        "create_dispatch_event",
        defer_invalid_foreign_key,
    )
    try:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            _create_job(runtime, "commit-failure")

        assert runtime.agent_repository.get_job_by_idempotency_key("commit-failure") is None
        assert runtime.agent_repository.count_rows("job_dispatch_outbox") == 0
        assert runtime.agent_repository.count_rows("agent_message") == 0
        assert runtime.message_bus is not None
        assert not runtime.message_bus.jobs
    finally:
        runtime.database.close()


class _BrokerInterruptedBeforeConfirm:
    def publish_agent_job(
        self,
        event_id: str,
        job_id: str,
        correlation_id: str,
    ) -> None:
        del event_id, job_id, correlation_id
        raise ConnectionError("connection closed before publisher confirm")


def test_broker_interruption_before_confirm_remains_finitely_retryable() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "confirm-interrupted")
        dispatcher = JobDispatchOutboxDispatcher(
            repository=runtime.agent_repository,
            publisher=_BrokerInterruptedBeforeConfirm(),
            audit_service=runtime.audit_service,
            settings=runtime.settings.queue,
            worker_id="confirm-interrupted-dispatcher",
        )

        result = dispatcher.publish_pending(limit=1)
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)

        assert event is not None
        assert result.failed == 1
        assert result.published == 0
        assert event.status == JobDispatchStatus.RETRY_WAIT
        assert event.attempt_count == 1
        assert event.claimed_at is None
        assert event.next_attempt_at > event.updated_at
        assert runtime.message_bus is not None
        assert not runtime.message_bus.jobs
    finally:
        runtime.database.close()


class _CountingAgentClient:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: object) -> AgentRunResult:
        del request
        self.calls += 1
        return AgentRunResult(final_answer="one durable execution")


def test_confirm_then_crash_before_outbox_commit_republishes_but_executes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "confirm-before-state")
        original_mark = runtime.agent_repository.mark_dispatch_published

        def crash_before_state_commit(**kwargs: object) -> bool:
            del kwargs
            raise RuntimeError("dispatcher crashed before published state commit")

        monkeypatch.setattr(
            runtime.agent_repository,
            "mark_dispatch_published",
            crash_before_state_commit,
        )
        with pytest.raises(RuntimeError, match="before published state"):
            runtime.job_dispatcher.publish_pending(limit=1)

        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        assert event.status == JobDispatchStatus.RUNNING
        assert runtime.message_bus is not None
        assert len(runtime.message_bus.jobs) == 1

        monkeypatch.setattr(
            runtime.agent_repository,
            "mark_dispatch_published",
            original_mark,
        )
        runtime.database.execute(
            "update job_dispatch_outbox set claimed_at = ? where id = ?",
            ((datetime.now(UTC) - timedelta(hours=1)).isoformat(), event.id),
        )
        recovered = runtime.job_dispatcher.publish_pending(limit=1)

        assert recovered.recovered == 1
        assert recovered.published == 1
        assert len(runtime.message_bus.jobs) == 2
        client = _CountingAgentClient()
        runtime.agent_executor.claude_client = client  # type: ignore[assignment]
        worker = AgentJobWorker(runtime.settings, container=runtime)
        runtime.message_bus.consume_agent_jobs(worker.handle)

        assert client.calls == 1
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
    finally:
        runtime.database.close()


def test_sqlite_lock_after_broker_confirm_retries_state_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "confirm-state-lock")
        original_mark = runtime.agent_repository.mark_dispatch_published
        attempts = 0

        def transient_lock(**kwargs: object) -> bool:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise sqlite3.OperationalError("database table is locked")
            return original_mark(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            runtime.agent_repository,
            "mark_dispatch_published",
            transient_lock,
        )
        result = runtime.job_dispatcher.publish_pending(limit=1)

        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert result.published == 1
        assert attempts == 2
        assert event is not None
        assert event.status == JobDispatchStatus.PUBLISHED
        assert runtime.message_bus is not None
        assert len(runtime.message_bus.jobs) == 1
    finally:
        runtime.database.close()


class _CrashAfterPublishedAudit:
    def record(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        raise RuntimeError("dispatcher crashed after published state commit")


def test_crash_after_published_state_does_not_republish() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "state-before-crash")
        crashing = JobDispatchOutboxDispatcher(
            repository=runtime.agent_repository,
            publisher=runtime.publisher,
            audit_service=_CrashAfterPublishedAudit(),  # type: ignore[arg-type]
            settings=runtime.settings.queue,
            worker_id="post-state-crash-dispatcher",
        )
        with pytest.raises(RuntimeError, match="after published state"):
            crashing.publish_pending(limit=1)

        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        assert event.status == JobDispatchStatus.PUBLISHED
        assert runtime.message_bus is not None
        assert len(runtime.message_bus.jobs) == 1
        restarted = runtime.job_dispatcher.publish_pending(limit=10)
        assert restarted.published == 0
        assert len(runtime.message_bus.jobs) == 1
    finally:
        runtime.database.close()


def test_multiple_dispatchers_claim_each_event_once() -> None:
    runtime = container()
    try:
        jobs = [_create_job(runtime, f"multi-dispatch-{index}") for index in range(20)]
        first = JobDispatchOutboxDispatcher(
            repository=runtime.agent_repository,
            publisher=runtime.publisher,
            audit_service=runtime.audit_service,
            settings=runtime.settings.queue,
            worker_id="dispatcher-a",
        )
        second = JobDispatchOutboxDispatcher(
            repository=runtime.agent_repository,
            publisher=runtime.publisher,
            audit_service=runtime.audit_service,
            settings=runtime.settings.queue,
            worker_id="dispatcher-b",
        )

        def publish_with_sqlite_lock_retry(
            dispatcher: JobDispatchOutboxDispatcher,
        ) -> None:
            for _ in range(50):
                try:
                    dispatcher.publish_pending(limit=20)
                    return
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        raise
                    time.sleep(0.01)
            raise AssertionError("SQLite dispatcher lock did not clear")

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(
                executor.map(
                    publish_with_sqlite_lock_retry,
                    (first, second),
                )
            )

        assert runtime.message_bus is not None
        assert len(runtime.message_bus.jobs) == len(jobs)
        assert len({message.event_id for message in runtime.message_bus.jobs}) == len(jobs)
        assert all(
            runtime.agent_repository.get_dispatch_event_for_job(job.id).status
            == JobDispatchStatus.PUBLISHED
            for job in jobs
        )
    finally:
        runtime.database.close()
