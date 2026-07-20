from __future__ import annotations

from dataclasses import replace

from app.modules.job.infrastructure.repositories import now_iso
from app.modules.webhook.application.dispatch_service import WebhookOutboxPublisher
from app.modules.webhook.domain.models import WebhookEventStatus
from app.modules.webhook.infrastructure import WebhookEventRepository
from backend.tests.helpers import container


class FailingWebhookPublisher:
    def publish_webhook_event(self, webhook_event_id: str, correlation_id: str) -> None:
        del webhook_event_id, correlation_id
        raise ConnectionError("amqp://user:password@rabbitmq/internal")


def _accepted_event(c: object, suffix: str) -> dict[str, object]:
    repository: WebhookEventRepository = c.webhook_event_repository
    event, created = repository.receive(
        trigger_id="webhook_trigger_grafana_default",
        trigger_publication_id="webhook_trigger_publication_grafana_v1",
        agent_publication_id="agent_publication_default_v1",
        service_account_id="user_webhook_grafana_default",
        external_event_id=f"outbox-{suffix}",
        dedup_key=f"outbox:{suffix}",
        payload_hash="0" * 64,
        request_bytes=2,
        safe_summary={"status": "firing"},
        normalized_event={"message": "test", "routing": {}, "delivery": {}},
        correlation_id=f"correlation-{suffix}",
        status=WebhookEventStatus.ACCEPTED,
        auth_result="bearer_v1",
        filter_result="matched",
        enqueue=True,
    )
    assert created is True
    return event


def test_outbox_failure_retries_then_becomes_dead_without_leaking_error() -> None:
    c = container()
    event = _accepted_event(c, "dead")
    settings = replace(
        c.settings.webhooks,
        outbox_max_attempts=2,
        outbox_retry_base_seconds=1,
    )
    publisher = WebhookOutboxPublisher(
        repository=c.webhook_event_repository,
        publisher=FailingWebhookPublisher(),
        audit_service=c.audit_service,
        settings=settings,
        worker_id="test-failing-outbox",
    )

    first = publisher.publish_pending()
    assert first.failed == 1
    pending = c.database.execute_one(
        "select * from webhook_outbox where webhook_event_id = ?", (event["id"],)
    )
    assert pending
    assert pending["status"] == "pending"
    assert pending["attempt_count"] == 1
    assert "password" not in pending["last_error_summary"]
    assert pending["last_error_summary"] == "ConnectionError"

    c.database.execute(
        "update webhook_outbox set next_attempt_at = '2000-01-01T00:00:00+00:00' where id = ?",
        (pending["id"],),
    )
    second = publisher.publish_pending()
    assert second.failed == 1
    dead = c.database.execute_one(
        "select * from webhook_outbox where webhook_event_id = ?", (event["id"],)
    )
    assert dead
    assert dead["status"] == "dead"
    assert dead["attempt_count"] == 2
    assert c.webhook_event_repository.get(str(event["id"]))["status"] == "DISPATCH_FAILED"
    assert c.agent_repository.count_rows("agent_job") == 0


def test_stale_claim_is_recovered_and_only_one_minimal_message_is_published() -> None:
    c = container()
    event = _accepted_event(c, "recover")
    claimed = c.webhook_event_repository.claim_outbox(
        worker_id="crashed-worker", now=now_iso()
    )
    assert claimed
    c.database.execute(
        "update webhook_outbox set claimed_at = '2000-01-01T00:00:00+00:00' where id = ?",
        (claimed["id"],),
    )
    assert c.webhook_event_repository.claim_outbox(
        worker_id="other-worker", now=now_iso()
    ) is None

    result = c.webhook_outbox_publisher.publish_pending()
    assert result.published == 1
    assert result.failed == 0
    assert len(c.message_bus.webhook_events) == 1
    message = c.message_bus.webhook_events[0]
    assert vars(message) == {
        "webhook_event_id": event["id"],
        "correlation_id": "correlation-recover",
    }
    outbox = c.database.execute_one(
        "select * from webhook_outbox where webhook_event_id = ?", (event["id"],)
    )
    assert outbox
    assert outbox["status"] == "published"
    assert outbox["attempt_count"] == 2
