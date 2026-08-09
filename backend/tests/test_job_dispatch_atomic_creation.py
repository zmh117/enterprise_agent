from __future__ import annotations

import pytest

from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.domain.job_dispatch import JobDispatchStatus
from backend.tests.helpers import container


def _command(idempotency_key: str) -> CreateAgentJobCommand:
    return CreateAgentJobCommand(
        idempotency_key=idempotency_key,
        requester_id="local-user",
        external_conversation_id=f"debug-{idempotency_key}",
        user_message="diagnose through durable dispatch",
        project_code="default",
        source_channel="debug_api",
        source_connector_id="connector-debug-api",
        reply_route={"type": "none"},
        correlation_id=f"correlation-{idempotency_key}",
    )


def test_job_message_authorization_snapshot_and_dispatch_event_commit_together() -> None:
    runtime = container()
    try:
        job = runtime.create_agent_job_service.execute(_command("atomic-dispatch"))

        detail = runtime.agent_repository.get_job_detail(job.id)
        messages = runtime.agent_repository.list_messages(job.session_id)
        event = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        audit_types = {row["event_type"] for row in runtime.audit_repository.list_for_job(job.id)}

        assert detail["id"] == job.id
        assert detail["business_application_route_decision"] == {
            "authorization_snapshot": {},
            "runtime_authorization": {},
        }
        assert [message["job_id"] for message in messages] == [job.id]
        assert event is not None
        assert event.status == JobDispatchStatus.PENDING
        assert event.event_key == f"job.dispatch:{job.id}"
        assert event.idempotency_key == "job.dispatch:atomic-dispatch"
        assert event.correlation_id == "correlation-atomic-dispatch"
        assert {"job.created", "job.dispatch.enqueued"}.issubset(audit_types)
        assert runtime.message_bus is not None
        assert not runtime.message_bus.jobs
    finally:
        runtime.database.close()


def test_dispatch_event_failure_rolls_back_job_message_and_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = container()
    original = runtime.agent_repository.create_dispatch_event
    before_messages = runtime.agent_repository.count_rows("agent_message")
    before_outbox = runtime.agent_repository.count_rows("job_dispatch_outbox")

    def fail_after_insert(**kwargs: object) -> object:
        original(**kwargs)  # type: ignore[arg-type]
        raise RuntimeError("fail after dispatch insert")

    monkeypatch.setattr(
        runtime.agent_repository,
        "create_dispatch_event",
        fail_after_insert,
    )
    try:
        with pytest.raises(RuntimeError, match="fail after dispatch insert"):
            runtime.create_agent_job_service.execute(_command("atomic-rollback"))

        assert runtime.agent_repository.get_job_by_idempotency_key("atomic-rollback") is None
        assert runtime.agent_repository.count_rows("agent_message") == before_messages
        assert runtime.agent_repository.count_rows("job_dispatch_outbox") == before_outbox
        assert runtime.message_bus is not None
        assert not runtime.message_bus.jobs
    finally:
        runtime.database.close()
