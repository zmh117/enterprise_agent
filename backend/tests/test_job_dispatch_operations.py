from __future__ import annotations

import json

import pytest

from app.cli.job_dispatch import build_parser
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.job_dispatch_operations import (
    JobDispatchOperationsService,
)
from app.modules.job.application.job_dispatch_service import JobDispatchOutboxDispatcher
from app.modules.job.domain.job_dispatch import JobDispatchStatus
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


def _create_job(runtime: object, key: str):
    return runtime.create_agent_job_service.execute(  # type: ignore[attr-defined]
        CreateAgentJobCommand(
            idempotency_key=key,
            requester_id="local-user",
            external_conversation_id=f"debug-{key}",
            user_message="bounded dispatch replay",
            project_code="default",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            reply_route={"type": "none"},
            correlation_id=f"correlation-{key}",
        )
    )


class _UnavailablePublisher:
    def publish_agent_job(
        self,
        event_id: str,
        job_id: str,
        correlation_id: str,
    ) -> None:
        del event_id, job_id, correlation_id
        raise ConnectionError("broker unavailable token=must-not-persist")


def _operations(runtime: object) -> JobDispatchOperationsService:
    return JobDispatchOperationsService(
        repository=runtime.agent_repository,  # type: ignore[attr-defined]
        audit_service=runtime.audit_service,  # type: ignore[attr-defined]
    )


def test_exact_status_and_aggregate_metrics_are_read_only_and_safe() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-status")
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        operations = _operations(runtime)

        by_event = operations.status(event_id=event.id)
        by_job = operations.status(job_id=job.id)
        metrics = operations.metrics()

        assert by_event == by_job
        assert by_event["status"] == JobDispatchStatus.PENDING.value
        assert by_event["event_id"] == event.id
        assert metrics["counts"][JobDispatchStatus.PENDING.value] == 1
        assert event.id not in json.dumps(metrics)
        assert job.id not in json.dumps(metrics)
        with pytest.raises(
            NonRetryableExecutionError,
            match="Exactly one",
        ):
            operations.status()
        with pytest.raises(
            NonRetryableExecutionError,
            match="Exactly one",
        ):
            operations.status(event_id=event.id, job_id=job.id)
    finally:
        runtime.database.close()


def test_dead_replay_is_bounded_rearms_same_event_and_digests_reason() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-bounded-replay")
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        runtime.database.execute(
            """
            update job_dispatch_outbox
               set max_attempts = 1, max_replay_count = 1
             where id = ?
            """,
            (event.id,),
        )
        failing = JobDispatchOutboxDispatcher(
            repository=runtime.agent_repository,
            publisher=_UnavailablePublisher(),
            audit_service=runtime.audit_service,
            settings=runtime.settings.queue,
            worker_id="bounded-replay-test",
        )
        assert failing.publish_pending(limit=1).dead == 1
        operations = _operations(runtime)

        replayed = operations.replay(
            job_id=job.id,
            actor_id="operator-1",
            reason="incident ticket secret-should-be-digested",
        )

        assert replayed["event_id"] == event.id
        assert replayed["status"] == JobDispatchStatus.PENDING.value
        assert replayed["attempt_count"] == 0
        assert replayed["replay_count"] == 1
        assert replayed["max_replay_count"] == 1
        assert failing.publish_pending(limit=1).dead == 1
        with pytest.raises(
            NonRetryableExecutionError,
            match="replay limit is exhausted",
        ):
            operations.replay(
                event_id=event.id,
                actor_id="operator-1",
                reason="second replay is forbidden",
            )
        persisted = str(runtime.audit_repository.list_for_job(job.id))
        assert "secret-should-be-digested" not in persisted
        assert "job.dispatch.replayed" in persisted
    finally:
        runtime.database.close()


def test_replay_rejects_non_dead_event_and_cli_has_no_payload_override() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "dispatch-replay-state")
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        with pytest.raises(
            NonRetryableExecutionError,
            match="Only DEAD",
        ):
            _operations(runtime).replay(
                event_id=event.id,
                actor_id="operator-1",
                reason="not dead",
            )
        with pytest.raises(SystemExit):
            build_parser().parse_args(
                [
                    "replay",
                    "--event-id",
                    event.id,
                    "--reason",
                    "attempt payload override",
                    "--payload",
                    '{"job_id":"other"}',
                ]
            )
    finally:
        runtime.database.close()
