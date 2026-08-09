from __future__ import annotations

import json

import pytest

from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


def _create_job(
    runtime: object,
    key: str,
    *,
    reply_route: dict[str, object] | None = None,
) -> object:
    return runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=key,
            requester_id="local-user",
            external_conversation_id=f"conversation-{key}",
            user_message="diagnose",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            project_code="default",
            correlation_id=f"correlation-{key}",
            reply_route=reply_route or {"type": "none"},
        )
    )


def test_success_persists_artifact_job_and_delivery_without_adapter_call() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "delivery-success-atomic")

        result = runtime.agent_executor.execute(
            job.id,
            worker_id="atomic-success-worker",
            correlation_id="correlation-success",
        )

        persisted = runtime.agent_repository.get_job(job.id)
        delivery = runtime.agent_repository.get_delivery_event_for_job(job.id)
        assert result
        assert persisted.status == JobStatus.SUCCEEDED
        assert delivery is not None
        assert delivery.status.value == "PENDING"
        assert delivery.correlation_id == "correlation-success"
        assert (
            runtime.agent_repository.get_artifact(delivery.result_artifact_id)["content"] == result
        )
        assert runtime.agent_repository.list_delivery_attempts(job.id) == []
        assert runtime.result_delivery_service.sent_messages == []
    finally:
        runtime.database.close()


def test_success_delivery_outbox_failure_rolls_back_result_and_job_terminal() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "delivery-success-rollback")
        original = runtime.agent_repository.create_delivery_event

        def fail_after_insert(**kwargs: object) -> object:
            original(**kwargs)  # type: ignore[arg-type]
            raise RuntimeError("synthetic delivery outbox persistence failure")

        runtime.agent_repository.create_delivery_event = fail_after_insert  # type: ignore[method-assign]

        with pytest.raises(
            RuntimeError,
            match="delivery outbox persistence",
        ):
            runtime.agent_executor.execute(
                job.id,
                worker_id="atomic-rollback-worker",
                correlation_id="correlation-rollback",
                fail_on_error=False,
            )

        persisted = runtime.agent_repository.get_job(job.id)
        assert persisted.status == JobStatus.RUNNING
        assert persisted.result is None
        assert runtime.database.execute_one(
            "select count(*) as count from agent_artifact where job_id = ?",
            (job.id,),
        ) == {"count": 0}
        assert runtime.database.execute_one(
            "select count(*) as count from delivery_outbox where job_id = ?",
            (job.id,),
        ) == {"count": 0}
    finally:
        runtime.database.close()


def test_terminal_failure_persists_safe_artifact_and_delivery_in_same_uow() -> None:
    runtime = container()
    try:
        job = _create_job(
            runtime,
            "delivery-failure-atomic",
            reply_route={
                "type": "dingtalk_stream_session_webhook",
                "target": {
                    "session_webhook": ("https://example.invalid/send?access_token=must-not-leak")
                },
            },
        )
        claimed = runtime.agent_repository.claim_job(job.id, "failure-worker")
        assert claimed is not None
        error = NonRetryableExecutionError(
            "provider token leaked internally",
            safe_message="provider https://example.invalid?token=secret failed",
            error_code="provider_failure",
        )

        action = runtime.retry_service.handle_failure(
            claimed,
            error,
            "correlation-failure",
        )

        persisted = runtime.agent_repository.get_job(job.id)
        delivery = runtime.agent_repository.get_delivery_event_for_job(job.id)
        assert action == "dead"
        assert persisted.status == JobStatus.FAILED
        assert delivery is not None
        assert delivery.status.value == "PENDING"
        artifact = runtime.agent_repository.get_artifact(delivery.result_artifact_id)
        payload = json.loads(str(artifact["content"]))
        assert payload["error_code"] == "provider_failure"
        assert "secret" not in payload["message"].lower()
        assert "http" not in payload["message"].lower()
        assert delivery.delivery_binding["route_hash"]
        assert "must-not-leak" not in json.dumps(
            delivery.delivery_binding,
            ensure_ascii=False,
        )
        assert delivery.target_summary["target"]["session_webhook"] == "***"
        assert runtime.result_delivery_service.sent_messages == []
    finally:
        runtime.database.close()


def test_terminal_failure_outbox_failure_rolls_back_job_and_artifact() -> None:
    runtime = container()
    try:
        job = _create_job(runtime, "delivery-failure-rollback")
        claimed = runtime.agent_repository.claim_job(job.id, "failure-worker")
        assert claimed is not None
        original = runtime.agent_repository.create_delivery_event

        def fail_after_insert(**kwargs: object) -> object:
            original(**kwargs)  # type: ignore[arg-type]
            raise RuntimeError("synthetic terminal delivery outbox failure")

        runtime.agent_repository.create_delivery_event = fail_after_insert  # type: ignore[method-assign]

        with pytest.raises(
            RuntimeError,
            match="terminal delivery outbox",
        ):
            runtime.retry_service.handle_failure(
                claimed,
                NonRetryableExecutionError(
                    "terminal failure",
                    safe_message="安全终态失败",
                    error_code="terminal_failure",
                ),
                "correlation-terminal-rollback",
            )

        persisted = runtime.agent_repository.get_job(job.id)
        assert persisted.status == JobStatus.RUNNING
        assert runtime.database.execute_one(
            "select count(*) as count from agent_artifact where job_id = ?",
            (job.id,),
        ) == {"count": 0}
        assert runtime.database.execute_one(
            "select count(*) as count from delivery_outbox where job_id = ?",
            (job.id,),
        ) == {"count": 0}
        assert "job.dead.persisted" not in {
            row["event_type"]
            for row in runtime.database.execute(
                "select event_type from audit_event where job_id = ?",
                (job.id,),
            )
        }
    finally:
        runtime.database.close()
