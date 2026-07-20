from __future__ import annotations

from dataclasses import dataclass
from app.modules.agent_config.application.service import AgentConfigService
from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.application.channel_ingress_service import ChannelIngressService
from app.modules.channel.domain.channel_event import (
    ChannelEvent,
    ChannelSource,
    ReplyRoute,
    RoutingContext,
)
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.message_bus.application.message_publisher import (
    MessagePublisher,
    WebhookEventMessage,
)
from app.modules.webhook.infrastructure import WebhookEventRepository, WebhookTriggerRepository
from app.shared.config import WebhookSettings
from app.shared.exceptions import AppError, NonRetryableExecutionError


@dataclass(frozen=True)
class OutboxPublishResult:
    published: int
    failed: int


class WebhookOutboxPublisher:
    def __init__(
        self,
        *,
        repository: WebhookEventRepository,
        publisher: MessagePublisher,
        audit_service: AuditService,
        settings: WebhookSettings,
        worker_id: str = "webhook-outbox",
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.audit_service = audit_service
        self.settings = settings
        self.worker_id = worker_id

    def publish_pending(self, *, limit: int = 100) -> OutboxPublishResult:
        from datetime import UTC, datetime, timedelta

        self.repository.recover_stale_outbox_claims(
            stale_before=(datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        )
        published = 0
        failed = 0
        for _ in range(min(max(limit, 1), 1000)):
            from app.modules.job.infrastructure.repositories import now_iso

            outbox = self.repository.claim_outbox(worker_id=self.worker_id, now=now_iso())
            if not outbox:
                break
            try:
                self.publisher.publish_webhook_event(
                    str(outbox["webhook_event_id"]), str(outbox["correlation_id"])
                )
            except Exception as exc:
                failed += 1
                safe_error = getattr(exc, "safe_message", type(exc).__name__)
                state = self.repository.mark_outbox_failed(
                    outbox_id=str(outbox["id"]),
                    error_summary=str(safe_error),
                    max_attempts=self.settings.outbox_max_attempts,
                    base_delay_seconds=self.settings.outbox_retry_base_seconds,
                )
                self.audit_service.record(
                    "webhook.outbox.publish_failed",
                    status="FAILED",
                    summary="Webhook dispatcher message publication failed",
                    payload={
                        "event_id": outbox["webhook_event_id"],
                        "attempt_count": state.get("attempt_count"),
                        "outbox_status": state.get("status"),
                    },
                )
                continue
            self.repository.mark_outbox_published(str(outbox["id"]))
            published += 1
            self.audit_service.record(
                "webhook.outbox.published",
                status="SUCCEEDED",
                summary="Webhook dispatcher message published",
                payload={"event_id": outbox["webhook_event_id"]},
            )
        return OutboxPublishResult(published=published, failed=failed)


class WebhookDispatcher:
    def __init__(
        self,
        *,
        event_repository: WebhookEventRepository,
        trigger_repository: WebhookTriggerRepository,
        identity_repository: IdentityRepository,
        agent_config_service: AgentConfigService,
        channel_ingress_service: ChannelIngressService,
        audit_service: AuditService,
    ) -> None:
        self.event_repository = event_repository
        self.trigger_repository = trigger_repository
        self.identity_repository = identity_repository
        self.agent_config_service = agent_config_service
        self.channel_ingress_service = channel_ingress_service
        self.audit_service = audit_service

    def handle(self, message: WebhookEventMessage) -> None:
        event = self.event_repository.get(message.webhook_event_id)
        if event.get("job_id"):
            return
        if str(event["status"]) not in {"ACCEPTED", "DISPATCH_PENDING"}:
            return
        try:
            definition = self.trigger_repository.get_definition(str(event["trigger_code"]))
            if str(definition["status"]) != "enabled":
                raise NonRetryableExecutionError(
                    "Webhook Trigger is disabled before dispatch",
                    safe_message="Webhook Trigger is disabled",
                )
            service_account = self.identity_repository.get_user(
                str(event["service_account_id"])
            )
            if (
                str(service_account["status"]) != "enabled"
                or str(service_account["account_type"]) != "service"
            ):
                raise NonRetryableExecutionError(
                    "Webhook service account is disabled before dispatch",
                    safe_message="Webhook service account is disabled",
                )
            publication = self.trigger_repository.get_publication(
                str(event["trigger_publication_id"])
            )
            if str(publication["trigger_id"]) != str(event["trigger_id"]):
                raise NonRetryableExecutionError(
                    "Webhook event Trigger publication mismatch",
                    safe_message="Webhook event integrity check failed",
                )
            snapshot = publication["snapshot"]
            agent_publication = self.agent_config_service.publication(
                str(event["agent_publication_id"])
            )
            agent = snapshot.get("agent") or {}
            if (
                str(agent_publication["id"]) != str(agent.get("publication_id") or "")
                or int(agent_publication["revision"]) != int(agent.get("revision") or 0)
                or str(agent_publication["config_hash"]) != str(agent.get("config_hash") or "")
            ):
                raise NonRetryableExecutionError(
                    "Webhook event pinned Agent publication mismatch",
                    safe_message="Webhook Agent configuration integrity check failed",
                )
            normalized = event["normalized_event"]
            channel_event = ChannelEvent(
                source=ChannelSource(
                    type=(
                        "grafana_alert"
                        if str(definition.get("trigger_type") or "") == "grafana"
                        else "managed_webhook"
                    ),
                    connector_id=str(snapshot["source_connector_id"]),
                    event_id=str(event["external_event_id"]),
                    actor_id=str(service_account["id"]),
                    conversation_id=f"webhook:{event['trigger_id']}",
                    metadata={
                        "display_name": service_account["display_name"],
                        "trigger_code": definition["code"],
                    },
                ),
                delivery=ReplyRoute.from_dict(snapshot["delivery"]),
                routing=RoutingContext.from_dict(normalized["routing"]),
                message=str(normalized["message"]),
                raw_payload_summary=event["safe_summary"],
                idempotency_key=f"webhook:{event['trigger_id']}:{event['dedup_key']}",
                correlation_id=str(event["correlation_id"]),
                agent_code=str(agent["code"]),
                agent_publication_id=str(agent_publication["id"]),
                agent_revision=int(agent_publication["revision"]),
                agent_config_hash=str(agent_publication["config_hash"]),
                webhook_event_id=str(event["id"]),
                webhook_trigger_id=str(event["trigger_id"]),
                webhook_trigger_publication_id=str(event["trigger_publication_id"]),
            )
            job = self.channel_ingress_service.accept(channel_event)
            self.event_repository.attach_job(event_id=str(event["id"]), job_id=job.id)
            self.audit_service.record(
                "webhook.event.job_created",
                status="SUCCEEDED",
                summary="Webhook event dispatched to Agent job",
                job_id=job.id,
                actor_id=str(service_account["id"]),
                payload={
                    "event_id": event["id"],
                    "trigger_publication_id": event["trigger_publication_id"],
                    "agent_publication_id": event["agent_publication_id"],
                    "correlation_id": event["correlation_id"],
                },
            )
        except AppError as exc:
            self.event_repository.mark_dispatch_failed(
                event_id=str(event["id"]), error_summary=exc.safe_message
            )
            self.audit_service.record(
                "webhook.event.dispatch_failed",
                status="FAILED",
                summary=exc.safe_message,
                actor_id=str(event["service_account_id"]),
                payload={"event_id": event["id"], "error_code": exc.error_code},
            )
