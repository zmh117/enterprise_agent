from __future__ import annotations

import json

import pytest

from app.cli.delivery import build_parser
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.delivery.application.delivery_operations import (
    DeliveryOperationsService,
)
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from backend.tests.helpers import container


class _ControllableAdapter(DeliveryAdapter):
    def __init__(self, *, failing: bool) -> None:
        self.failing = failing
        self.sent: list[str] = []

    def send(
        self,
        *,
        connector: object,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        del connector, route, title
        if self.failing:
            raise RetryableExecutionError(
                "synthetic delivery outage secret=must-not-persist",
                safe_message="投递服务暂时不可用",
                error_code="delivery_synthetic_outage",
            )
        self.sent.append(text)


def _completed_job(runtime: object, key: str) -> object:
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=key,
            requester_id="local-user",
            external_conversation_id=f"conversation-{key}",
            user_message="diagnose",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            project_code="default",
            correlation_id=f"correlation-{key}",
            reply_route={
                "type": "test_replay",
                "target": {
                    "webhook_url": "https://frozen.example.test/secret",
                    "conversation_id": "conversation-frozen",
                },
            },
        )
    )
    runtime.agent_executor.execute(
        job.id,
        worker_id="delivery-operations-agent",
        correlation_id=f"correlation-{key}",
    )
    return job


def _operations(runtime: object) -> DeliveryOperationsService:
    return DeliveryOperationsService(
        repository=runtime.agent_repository,
        audit_service=runtime.audit_service,
    )


def _make_dead(runtime: object, key: str) -> tuple[object, object, _ControllableAdapter]:
    adapter = _ControllableAdapter(failing=True)
    runtime.result_delivery_service.adapters["test_replay"] = adapter
    job = _completed_job(runtime, key)
    event = runtime.agent_repository.get_delivery_event_for_job(job.id)
    assert event is not None
    runtime.database.execute(
        """
        update delivery_outbox
           set max_attempts = 1, max_replay_count = 1
         where id = ?
        """,
        (event.id,),
    )
    assert runtime.delivery_dispatcher.dispatch_pending(limit=1).dead == 1
    return job, runtime.agent_repository.get_delivery_event(event.id), adapter


def test_delivery_status_and_metrics_are_read_only_and_safe() -> None:
    runtime = container()
    try:
        job, event, _adapter = _make_dead(runtime, "delivery-operation-status")
        operations = _operations(runtime)

        status = operations.status(delivery_id=event.id)
        metrics = operations.metrics()

        assert status["delivery_id"] == event.id
        assert status["job_id"] == job.id
        assert status["status"] == "DEAD"
        assert status["target_summary"]["target"]["webhook_url"] == "***"
        serialized_status = json.dumps(status)
        assert "delivery_binding_json" not in serialized_status
        assert "route_hash" not in serialized_status
        assert "https://frozen.example.test/secret" not in serialized_status
        assert metrics["counts"]["DEAD"] == 1
        assert metrics["terminal_failure_count"] == 1
        assert event.id not in json.dumps(metrics)
        assert job.id not in json.dumps(metrics)
    finally:
        runtime.database.close()


def test_dead_replay_reuses_frozen_intent_and_does_not_rerun_agent() -> None:
    runtime = container()
    try:
        job, event, adapter = _make_dead(runtime, "delivery-operation-replay")
        operations = _operations(runtime)
        before = runtime.database.execute_one(
            """
            select delivery_binding_json, target_summary, result_artifact_id
              from delivery_outbox
             where id = ?
            """,
            (event.id,),
        )
        before_artifact = runtime.agent_repository.get_artifact(str(before["result_artifact_id"]))
        before_steps = runtime.database.execute_one(
            "select count(*) as count from agent_step where job_id = ?",
            (job.id,),
        )

        replayed = operations.replay(
            delivery_id=event.id,
            actor_id="operator-1",
            reason="incident ticket 123",
        )

        assert replayed["delivery_id"] == event.id
        assert replayed["status"] == "PENDING"
        assert replayed["attempt_count"] == 0
        assert replayed["replay_count"] == 1
        after_rearm = runtime.database.execute_one(
            """
            select delivery_binding_json, target_summary, result_artifact_id
              from delivery_outbox
             where id = ?
            """,
            (event.id,),
        )
        assert after_rearm == before

        adapter.failing = False
        assert runtime.delivery_dispatcher.dispatch_pending(limit=1).succeeded == 1
        completed = runtime.agent_repository.get_delivery_event(event.id)
        assert completed.status.value == "SUCCEEDED"
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
        assert (
            runtime.agent_repository.get_artifact(completed.result_artifact_id) == before_artifact
        )
        assert (
            runtime.database.execute_one(
                "select count(*) as count from agent_step where job_id = ?",
                (job.id,),
            )
            == before_steps
        )
        assert len(adapter.sent) == 1
        attempts = runtime.agent_repository.list_delivery_attempts(job.id)
        assert [(item["replay_no"], item["attempt_no"]) for item in attempts] == [(0, 1), (1, 1)]

        runtime.database.execute(
            """
            update delivery_outbox
               set status = 'DEAD', dead_at = updated_at
             where id = ?
            """,
            (event.id,),
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="replay limit is exhausted",
        ):
            operations.replay(
                delivery_id=event.id,
                actor_id="operator-1",
                reason="second replay",
            )
    finally:
        runtime.database.close()


def test_replay_override_is_rejected_audited_and_not_persisted() -> None:
    runtime = container()
    try:
        job, event, _adapter = _make_dead(runtime, "delivery-operation-reject")
        operations = _operations(runtime)
        with pytest.raises(
            NonRetryableExecutionError,
            match="cannot override persisted intent",
        ):
            operations.replay(
                delivery_id=event.id,
                actor_id="operator-2",
                reason="secret-reason-must-be-digested",
                connector_id="connector-override-secret",
                target="https://override-secret.example.test",
                payload="override-payload-secret",
            )

        unchanged = runtime.agent_repository.get_delivery_event(event.id)
        assert unchanged.status.value == "DEAD"
        assert unchanged.replay_count == 0
        audit = json.dumps(runtime.audit_repository.list_for_job(job.id))
        assert "delivery.replay.rejected" in audit
        assert "secret-reason-must-be-digested" not in audit
        assert "connector-override-secret" not in audit
        assert "https://override-secret.example.test" not in audit
        assert "override-payload-secret" not in audit

        help_text = build_parser().format_help()
        replay_help = build_parser()._subparsers._group_actions[0].choices["replay"].format_help()
        assert "--payload" not in help_text + replay_help
        parsed = build_parser().parse_args(
            [
                "replay",
                "--delivery-id",
                event.id,
                "--reason",
                "override attempt",
                "--payload",
                "forbidden",
            ]
        )
        assert parsed.delivery_id == event.id
        assert parsed.payload == "forbidden"
    finally:
        runtime.database.close()
