from __future__ import annotations

from app.bootstrap import Container
from app.modules.message_bus.application.message_publisher import AgentJobMessage


def publish_pending_agent_jobs(runtime: Container) -> None:
    result = runtime.job_dispatcher.publish_pending(limit=100)
    assert result.failed == 0
    assert result.dead == 0


def enqueue_job_result_for_delivery(
    runtime: Container,
    job_id: str,
    *,
    correlation_id: str = "test-delivery",
) -> str:
    job = runtime.agent_repository.get_job(job_id)
    if not job.result:
        raise AssertionError("Job result must be persisted before Delivery enqueue")
    artifact = runtime.agent_repository.get_artifact_for_job(
        job_id=job_id,
        artifact_type="report",
        name="diagnostic-report.md",
    )
    artifact_id = (
        str(artifact["id"])
        if artifact is not None
        else runtime.agent_repository.add_artifact(
            job_id=job_id,
            artifact_type="report",
            name="diagnostic-report.md",
            content=job.result,
        )
    )
    return runtime.result_delivery_service.enqueue_job_result(
        job_id=job_id,
        artifact_id=artifact_id,
        correlation_id=correlation_id,
    )


def dispatch_pending_deliveries(runtime: Container) -> None:
    result = runtime.delivery_dispatcher.dispatch_pending(limit=100)
    assert result.retrying == 0
    assert result.failed == 0
    assert result.dead == 0


def persisted_agent_job_message(
    runtime: Container,
    job_id: str,
) -> AgentJobMessage:
    event = runtime.agent_repository.get_dispatch_event_for_job(job_id)
    assert event is not None
    return AgentJobMessage(
        event_id=event.id,
        job_id=event.job_id,
        correlation_id=event.correlation_id,
    )
