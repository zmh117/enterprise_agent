from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.bootstrap import Container
from app.cli.job_dispatch_cutover import build_parser
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.job_dispatch_cutover import JobDispatchCutoverService
from app.modules.job.domain.job_dispatch import JobDispatchStatus
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


def _create_job(runtime: Container, key: str):
    return runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=key,
            requester_id="local-user",
            external_conversation_id=f"debug-{key}",
            user_message="cut over this legacy message",
            project_code="default",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            reply_route={"type": "none"},
            correlation_id=f"correlation-{key}",
        )
    )


def _service(runtime: Container) -> JobDispatchCutoverService:
    return JobDispatchCutoverService(
        repository=runtime.agent_repository,
        audit_service=runtime.audit_service,
        queue_settings=runtime.settings.queue,
    )


def test_cutover_dry_run_then_backfills_one_legacy_message_idempotently() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "legacy-cutover")
        runtime.database.execute(
            "delete from job_dispatch_outbox where job_id = ?",
            (job.id,),
        )
        body = json.dumps({"job_id": job.id, "correlation_id": "legacy-correlation"}).encode()
        service = _service(runtime)

        preview = service.process_message(
            source_queue=runtime.settings.queue.job_queue,
            body=body,
            apply=False,
            actor_id="cutover-test",
        )

        assert preview.classification == "legacy_convertible"
        assert preview.disposition == "would_ack_after_outbox"
        assert runtime.agent_repository.get_dispatch_event_for_job(job.id) is None

        applied = service.process_message(
            source_queue=runtime.settings.queue.job_queue,
            body=body,
            apply=True,
            actor_id="cutover-test",
        )
        repeated = service.process_message(
            source_queue=runtime.settings.queue.job_queue,
            body=body,
            apply=True,
            actor_id="cutover-test",
        )
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)

        assert applied.classification == "legacy_converted"
        assert applied.disposition == "ack"
        assert repeated.event_id == applied.event_id
        assert event is not None
        assert event.status == JobDispatchStatus.PENDING
        assert runtime.agent_repository.count_rows("job_dispatch_outbox") == 1
    finally:
        runtime.database.close()


def test_cutover_quarantines_only_digest_without_raw_payload() -> None:
    runtime = container()
    try:
        secret_body = b'{"token":"plain-secret","payload":"arbitrary"}'
        service = _service(runtime)

        first = service.process_message(
            source_queue=runtime.settings.queue.legacy_retry_queue,
            body=secret_body,
            apply=True,
            actor_id="cutover-test",
        )
        repeated = service.process_message(
            source_queue=runtime.settings.queue.legacy_retry_queue,
            body=secret_body,
            apply=True,
            actor_id="cutover-test",
        )
        rows = runtime.database.execute("select * from job_dispatch_cutover_quarantine")

        assert first.classification == "quarantine"
        assert first.disposition == "ack"
        assert repeated.message_digest == first.message_digest
        assert len(rows) == 1
        assert rows[0]["message_digest"] == first.message_digest
        assert "plain-secret" not in json.dumps(rows)
        assert "arbitrary" not in json.dumps(rows)
    finally:
        runtime.database.close()


def test_current_main_message_is_left_for_worker_but_old_retry_is_rearmed() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "current-cutover")
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert event is not None
        body = json.dumps(
            {
                "event_id": event.id,
                "job_id": event.job_id,
                "correlation_id": event.correlation_id,
            }
        ).encode()
        service = _service(runtime)

        current = service.process_message(
            source_queue=runtime.settings.queue.job_queue,
            body=body,
            apply=True,
            actor_id="cutover-test",
        )
        assert current.classification == "current_contract"
        assert current.disposition == "requeue"

        claimed = runtime.agent_repository.claim_job(job.id, "cutover-worker")
        assert claimed is not None
        retry_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        runtime.agent_repository.schedule_retry(
            job.id,
            error_message="safe retry",
            error_code="test_retry",
            next_retry_at=retry_at,
        )
        runtime.database.execute(
            "update job_dispatch_outbox set status = 'PUBLISHED' where id = ?",
            (event.id,),
        )
        retry = service.process_message(
            source_queue=runtime.settings.queue.retry_queue,
            body=body,
            apply=True,
            actor_id="cutover-test",
        )
        rearmed = runtime.agent_repository.get_dispatch_event(event.id)

        assert retry.classification == "current_retry_converted"
        assert retry.disposition == "ack"
        assert rearmed.status == JobDispatchStatus.RETRY_WAIT
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.RETRY_WAIT
    finally:
        runtime.database.close()


def test_cutover_uses_exact_topology_and_rejects_wildcard_scope() -> None:
    runtime = container()
    try:
        service = _service(runtime)
        first = service.topology_plan()
        second = service.topology_plan()

        assert first == second
        assert first["current_job_queue"] == runtime.settings.queue.job_queue
        assert set(first["old_retry_queues"]) == {
            runtime.settings.queue.retry_queue,
            runtime.settings.queue.legacy_retry_queue,
        }
        assert len(str(first["topology_digest"])) == 64
        with pytest.raises(NonRetryableExecutionError):
            service.process_message(
                source_queue="agent.*",
                body=b"{}",
                apply=False,
                actor_id="cutover-test",
            )
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--queue", "agent.*"])
    finally:
        runtime.database.close()
