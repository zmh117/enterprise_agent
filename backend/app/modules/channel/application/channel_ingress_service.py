from __future__ import annotations

from app.modules.audit.application.audit_service import AuditService
from app.modules.business_application.application import BusinessApplicationResolver
from app.modules.channel.domain.channel_event import ChannelEvent
from app.modules.identity.application import IdentityService
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    CreateAgentJobService,
)
from app.modules.job.domain.agent_job import AgentJob
from app.shared.exceptions import PermissionDenied


class ChannelIngressService:
    def __init__(
        self,
        *,
        create_job_service: CreateAgentJobService,
        audit_service: AuditService,
        identity_service: IdentityService | None = None,
        unified_identity_enabled: bool = False,
        business_application_resolver: BusinessApplicationResolver | None = None,
        runtime_environment: str = "local",
    ) -> None:
        self.create_job_service = create_job_service
        self.audit_service = audit_service
        self.identity_service = identity_service
        self.unified_identity_enabled = unified_identity_enabled
        self.business_application_resolver = business_application_resolver
        self.runtime_environment = runtime_environment

    def accept(self, event: ChannelEvent) -> AgentJob:
        self.audit_service.record(
            "channel.received",
            status="SUCCEEDED",
            summary="Channel event received",
            actor_id=event.source.actor_id,
            payload={
                "source_type": event.source.type,
                "source_connector_id": event.source.connector_id,
                "external_event_id": event.source.event_id,
                "delivery_type": event.delivery.type,
                "delivery_connector_id": event.delivery.connector_id,
            },
        )
        self.audit_service.record(
            "channel.normalized",
            status="SUCCEEDED",
            summary="Channel event normalized",
            actor_id=event.source.actor_id,
            payload=event.raw_payload_summary,
        )
        requester_id = event.source.actor_id
        external_identity_id = ""
        if event.source.external_identity is not None and self.identity_service is not None:
            principal = self.identity_service.resolve_external(event.source.external_identity)
            requester_id = principal.user_id
            external_identity_id = principal.external_identity_id
            self.audit_service.record(
                "channel.identity.resolved",
                status="SUCCEEDED",
                summary="Channel external identity resolved to internal user",
                actor_id=requester_id,
                payload={
                    "external_identity_id": external_identity_id,
                    "provider": event.source.external_identity.provider,
                    "tenant_code": event.source.external_identity.tenant_code,
                    "connector_id": event.source.connector_id,
                },
            )
        elif self.unified_identity_enabled and event.source.type in {
            "dingding",
            "dingding_stream",
        }:
            raise PermissionDenied(
                "DingTalk external identity descriptor is required",
                safe_message="DingTalk identity could not be verified",
            )
        runtime = self._resolve_business_application(event)
        snapshot = ((runtime or {}).get("publication") or {}).get("snapshot") or {}
        session_policy = snapshot.get("session_policy") or {}
        agent = snapshot.get("agent") or {}
        return self.create_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key=event.effective_idempotency_key,
                requester_id=requester_id,
                requester_display_name=str(event.source.metadata.get("display_name") or ""),
                external_conversation_id=event.source.conversation_id,
                user_message=event.message,
                project_code=event.routing.project_code,
                source_channel=event.source.type,
                source_connector_id=event.source.connector_id,
                external_event_id=event.source.event_id,
                routing_context=event.routing.to_dict(),
                reply_route=event.delivery.to_dict(),
                correlation_id=event.correlation_id,
                external_message_id=str(event.source.metadata.get("message_id") or ""),
                conversation_type=str(
                    event.source.metadata.get("conversation_type") or "direct"
                ),
                bot_identity=str(event.source.metadata.get("bot_identity") or ""),
                attachments=event.attachments,
                external_identity_id=external_identity_id,
                agent_code=event.agent_code or str(agent.get("code") or ""),
                fixed_agent_publication_id=(
                    event.agent_publication_id
                    or str(agent.get("id") or "")
                ),
                fixed_agent_revision=(
                    event.agent_revision
                    if event.agent_revision is not None
                    else (
                        int(agent["revision"])
                        if agent.get("revision") is not None
                        else None
                    )
                ),
                fixed_agent_config_hash=(
                    event.agent_config_hash
                    or str(agent.get("config_hash") or "")
                ),
                continuous_conversation_enabled=(
                    bool(session_policy["continuous_conversation_enabled"])
                    if "continuous_conversation_enabled" in session_policy
                    else None
                ),
                attachments_enabled=(
                    bool(session_policy["attachments_enabled"])
                    if "attachments_enabled" in session_policy
                    else None
                ),
                webhook_event_id=event.webhook_event_id,
                webhook_trigger_id=event.webhook_trigger_id,
                webhook_trigger_publication_id=event.webhook_trigger_publication_id,
            )
        )

    def _resolve_business_application(
        self, event: ChannelEvent
    ) -> dict[str, object] | None:
        if self.business_application_resolver is None:
            return None
        trigger_type = _trigger_type(event)
        routing_key = (
            event.webhook_trigger_id
            if trigger_type == "webhook"
            else event.source.conversation_id
        )
        if not routing_key:
            return None
        environment = _normalize_environment(
            event.routing.environment
            or self.runtime_environment
            or "local"
        )
        return self.business_application_resolver.resolve_trigger_optional(
            environment,
            trigger_type,
            event.source.connector_id,
            routing_key,
        )


def _trigger_type(event: ChannelEvent) -> str:
    if event.webhook_trigger_id or event.source.type in {
        "managed_webhook",
        "grafana_alert",
        "webhook",
    }:
        return "webhook"
    if str(event.source.metadata.get("conversation_type") or "").lower() == "group":
        return "dingtalk_group"
    return "dingtalk_private"


def _normalize_environment(value: str) -> str:
    normalized = value.strip().lower()
    return {
        "prod": "production",
        "production": "production",
        "stage": "staging",
        "staging": "staging",
        "qa": "test",
        "testing": "test",
        "test": "test",
        "dev": "local",
        "development": "local",
        "local": "local",
    }.get(normalized, normalized)
