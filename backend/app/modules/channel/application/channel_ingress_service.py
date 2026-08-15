from __future__ import annotations

import hashlib

from app.modules.audit.application.audit_service import AuditService
from app.modules.business_application.application import BusinessApplicationResolver
from app.modules.business_application.domain import (
    RouteResolutionOutcome,
    RuntimeReason,
    RuntimeRouteResolution,
)
from app.modules.channel.domain.channel_event import ChannelEvent
from app.modules.identity.application import IdentityService
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    CreateAgentJobService,
)
from app.modules.job.domain.agent_job import AgentJob
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


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
                safe_message="无法验证钉钉身份",
            )
        resolution = self._resolve_business_application(event)
        runtime = (
            resolution.to_dict()
            if resolution is not None and resolution.outcome == RouteResolutionOutcome.MATCHED
            else {}
        )
        snapshot = (runtime.get("publication") or {}).get("snapshot") or {}
        session_policy = snapshot.get("session_policy") or {}
        execution_policy = snapshot.get("execution_policy") or {}
        agent = snapshot.get("agent") or {}
        self._assert_application_agent_precedence(event, resolution, agent)
        reply_route = self._application_reply_route(
            event,
            resolution,
            snapshot,
        )
        application = runtime.get("application") or {}
        publication = runtime.get("publication") or {}
        deployment = runtime.get("deployment") or {}
        route = runtime.get("route") or {}
        external_identity = event.source.external_identity
        enterprise_id = (
            str(external_identity.dingtalk_enterprise_id or external_identity.tenant_code)
            if external_identity is not None
            else ""
        )
        command = CreateAgentJobCommand(
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
            reply_route=reply_route,
            correlation_id=event.correlation_id,
            external_message_id=str(event.source.metadata.get("message_id") or ""),
            conversation_type=str(event.source.metadata.get("conversation_type") or "direct"),
            bot_identity=str(event.source.metadata.get("bot_identity") or ""),
            attachments=event.attachments,
            external_identity_id=external_identity_id,
            agent_code=(
                str(agent.get("code") or "")
                if resolution is not None and resolution.outcome == RouteResolutionOutcome.MATCHED
                else event.agent_code
            ),
            fixed_agent_publication_id=(
                str(agent.get("id") or "")
                if resolution is not None and resolution.outcome == RouteResolutionOutcome.MATCHED
                else event.agent_publication_id
            ),
            fixed_agent_revision=(
                int(agent["revision"])
                if resolution is not None
                and resolution.outcome == RouteResolutionOutcome.MATCHED
                and agent.get("revision") is not None
                else event.agent_revision
            ),
            fixed_agent_config_hash=(
                str(agent.get("config_hash") or "")
                if resolution is not None and resolution.outcome == RouteResolutionOutcome.MATCHED
                else event.agent_config_hash
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
            business_application_id=str(application.get("id") or ""),
            business_application_code=str(application.get("code") or ""),
            business_application_publication_id=str(publication.get("id") or ""),
            business_application_deployment_id=str(deployment.get("id") or ""),
            business_application_route_id=str(route.get("id") or ""),
            business_application_config_hash=str(publication.get("config_hash") or ""),
            business_application_runtime_status=str(runtime.get("runtime_status") or ""),
            business_application_route_decision=self._safe_route_decision(event, resolution),
            conversation_mode=str(session_policy.get("conversation_mode") or "legacy"),
            recent_message_limit=(
                int(session_policy["recent_message_limit"])
                if session_policy.get("recent_message_limit") is not None
                else None
            ),
            session_policy=dict(session_policy),
            application_execution_policy=dict(execution_policy),
            tenant_id=enterprise_id,
            enterprise_id=enterprise_id,
            sender_staff_id=str(event.source.metadata.get("sender_staff_id") or ""),
            task_workspace_retention_period=str(
                snapshot.get("task_workspace_retention_period") or "WEEK"
            ),
            task_file_features={
                str(key): bool(value)
                for key, value in dict(snapshot.get("task_file_features") or {}).items()
            },
            file_references=event.file_references,
            requests_file_output=event.requests_file_output,
        )
        job = self.create_job_service.execute(command)
        if resolution is not None and resolution.outcome == RouteResolutionOutcome.MATCHED:
            self.audit_service.record(
                "business_application.route.job_created",
                status="SUCCEEDED",
                summary="Business Application route created an Agent job",
                job_id=job.id,
                actor_id=requester_id,
                payload={
                    **self._safe_route_decision(event, resolution),
                    "job_id": job.id,
                },
            )
        return job

    def _resolve_business_application(self, event: ChannelEvent) -> RuntimeRouteResolution | None:
        if event.source.type not in {
            "dingding_stream",
            "grafana_alert",
            "managed_webhook",
            "webhook",
        }:
            return None
        if self.business_application_resolver is None:
            self.audit_service.record(
                "business_application.route.blocked",
                status="FAILED",
                summary="Business Application runtime is unavailable",
                actor_id=event.source.actor_id,
                payload={
                    "correlation_id": event.correlation_id or "",
                    "external_event_id": event.source.event_id,
                    "source_connector_id": event.source.connector_id,
                    "reason_code": RuntimeReason.DATA_PLANE_DISABLED.value,
                    "legacy_fallback": False,
                },
            )
            raise NonRetryableExecutionError(
                "Business Application runtime is unavailable",
                safe_message="当前机器人未配置可用的业务应用，请联系管理员",
                error_code=RuntimeReason.DATA_PLANE_DISABLED.value,
            )
        trigger_type = _trigger_type(event)
        routing_key = _business_application_routing_key(event, trigger_type)
        if not routing_key:
            self.audit_service.record(
                "business_application.route.not_matched",
                status="FAILED",
                summary="No trusted Business Application routing identity is available",
                actor_id=event.source.actor_id,
                payload={
                    "correlation_id": event.correlation_id or "",
                    "external_event_id": event.source.event_id,
                    "source_connector_id": event.source.connector_id,
                    "trigger_type": trigger_type,
                    "reason_code": RuntimeReason.ROUTE_NOT_MATCHED.value,
                    "legacy_fallback": False,
                },
            )
            raise NonRetryableExecutionError(
                "No trusted Business Application routing identity is available",
                safe_message="当前机器人未配置可用的业务应用，请联系管理员",
                error_code=RuntimeReason.ROUTE_NOT_MATCHED.value,
            )
        environment = "local"
        resolution = self.business_application_resolver.resolve_route(
            environment,
            trigger_type,
            event.source.connector_id,
            routing_key,
        )
        event_type = f"business_application.route.{resolution.outcome.value}"
        status = (
            "SUCCEEDED"
            if resolution.outcome == RouteResolutionOutcome.MATCHED
            else (
                "SKIPPED" if resolution.outcome == RouteResolutionOutcome.NOT_MATCHED else "FAILED"
            )
        )
        self.audit_service.record(
            event_type,
            status=status,
            summary=resolution.message,
            actor_id=event.source.actor_id,
            payload=self._safe_route_decision(event, resolution),
        )
        if resolution.outcome == RouteResolutionOutcome.BLOCKED:
            raise NonRetryableExecutionError(
                resolution.message,
                safe_message="业务应用配置暂时不可用",
                error_code=resolution.reason_code,
            )
        if resolution.outcome == RouteResolutionOutcome.NOT_MATCHED:
            raise NonRetryableExecutionError(
                resolution.message,
                safe_message="当前机器人未配置可用的业务应用，请联系管理员",
                error_code=RuntimeReason.ROUTE_NOT_MATCHED.value,
            )
        return resolution

    @staticmethod
    def _assert_application_agent_precedence(
        event: ChannelEvent,
        resolution: RuntimeRouteResolution | None,
        agent: dict[str, object],
    ) -> None:
        if resolution is None or resolution.outcome != RouteResolutionOutcome.MATCHED:
            return
        conflicts = (
            (bool(event.agent_code) and event.agent_code != str(agent.get("code") or ""))
            or (
                bool(event.agent_publication_id)
                and event.agent_publication_id != str(agent.get("id") or "")
            )
            or (
                event.agent_revision is not None
                and event.agent_revision != int(str(agent.get("revision") or 0))
            )
            or (
                bool(event.agent_config_hash)
                and event.agent_config_hash != str(agent.get("config_hash") or "")
            )
        )
        if conflicts:
            raise NonRetryableExecutionError(
                "Channel Agent configuration conflicts with Business Application",
                safe_message="业务应用的 Agent 配置不一致",
                error_code=RuntimeReason.AGENT_OVERRIDE_CONFLICT.value,
            )

    @staticmethod
    def _application_reply_route(
        event: ChannelEvent,
        resolution: RuntimeRouteResolution | None,
        snapshot: dict[str, object],
    ) -> dict[str, object]:
        if resolution is None or resolution.outcome != RouteResolutionOutcome.MATCHED:
            return event.delivery.to_dict()
        raw_deliveries = snapshot.get("deliveries")
        deliveries = raw_deliveries if isinstance(raw_deliveries, list) else []
        trigger_type = _trigger_type(event)
        if trigger_type == "webhook":
            supported = [
                value
                for value in deliveries
                if isinstance(value, dict)
                and bool(value.get("enabled", True))
                and str(value.get("delivery_type") or "") in {"dingtalk_group", "webhook_callback"}
            ]
            if len(supported) != 1:
                raise NonRetryableExecutionError(
                    "Business Application Webhook delivery is invalid",
                    safe_message="业务应用结果投递不可用",
                    error_code=RuntimeReason.MISSING_DELIVERY_BINDING.value,
                )
            binding = supported[0]
            config = binding.get("config") or {}
            if not isinstance(config, dict):
                config = {}
            delivery_type = str(binding.get("delivery_type") or "")
            target_reference = str(config.get("target_reference") or "")
            if not target_reference:
                raise NonRetryableExecutionError(
                    "Business Application Webhook delivery target is missing",
                    safe_message="业务应用结果投递目标未配置",
                    error_code=RuntimeReason.MISSING_DELIVERY_BINDING.value,
                )
            if delivery_type == "dingtalk_group":
                route_type = "dingtalk_enterprise_robot"
                target = {
                    "open_conversation_id": target_reference,
                }
            else:
                route_type = "webhook"
                target = {"target_reference": target_reference}
            return {
                "type": route_type,
                "connector_id": str(binding.get("connector_id") or ""),
                "target": target,
                "options": {
                    "business_application_delivery_type": delivery_type,
                },
            }
        bindings = [
            value
            for value in deliveries
            if isinstance(value, dict)
            and bool(value.get("enabled", True))
            and str(value.get("delivery_type") or "") == "reply_original"
        ]
        if len(bindings) != 1:
            raise NonRetryableExecutionError(
                "Business Application reply-original delivery is invalid",
                safe_message="业务应用结果投递不可用",
                error_code=RuntimeReason.MISSING_DELIVERY_BINDING.value,
            )
        if str(bindings[0].get("connector_id") or "") != event.source.connector_id:
            raise NonRetryableExecutionError(
                "Business Application delivery connector does not match ingress",
                safe_message="业务应用结果投递不可用",
                error_code=RuntimeReason.DELIVERY_CONNECTOR_MISMATCH.value,
            )
        if event.delivery.type != "dingtalk_stream_session_webhook":
            raise NonRetryableExecutionError(
                "Business Application requires DingTalk reply-original delivery",
                safe_message="原钉钉会话无法接收结果",
                error_code=RuntimeReason.UNSUPPORTED_DELIVERY.value,
            )
        return event.delivery.to_dict()

    @staticmethod
    def _safe_route_decision(
        event: ChannelEvent,
        resolution: RuntimeRouteResolution | None,
    ) -> dict[str, object]:
        route = resolution.route if resolution is not None else None
        application = resolution.application if resolution is not None else None
        deployment = resolution.deployment if resolution is not None else None
        publication = resolution.publication if resolution is not None else None
        trigger_type = _trigger_type(event)
        routing_key = _business_application_routing_key(event, trigger_type)
        return {
            "correlation_id": event.correlation_id or "",
            "external_event_id": event.source.event_id,
            "deployment_environment": _normalize_environment(
                str((deployment or {}).get("environment") or "")
            ),
            "trigger_type": trigger_type,
            "source_connector_id": event.source.connector_id,
            "routing_key_hash": (
                hashlib.sha256(routing_key.encode()).hexdigest() if routing_key else ""
            ),
            "resolution_outcome": (
                resolution.outcome.value
                if resolution is not None
                else RouteResolutionOutcome.NOT_MATCHED.value
            ),
            "reason_code": (
                resolution.reason_code
                if resolution is not None
                else RuntimeReason.ROUTE_NOT_MATCHED.value
            ),
            "business_application_code": str((application or {}).get("code") or ""),
            "business_application_publication_id": str((publication or {}).get("id") or ""),
            "business_application_deployment_id": str((deployment or {}).get("id") or ""),
            "business_application_route_id": str((route or {}).get("id") or ""),
            "runtime_status": (
                resolution.readiness.runtime_status.value if resolution is not None else "not_wired"
            ),
            "runtime_components": (
                resolution.readiness.to_dict().get("runtime_components", {})
                if resolution is not None
                else {}
            ),
            "legacy_fallback": False,
        }


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


def _business_application_routing_key(event: ChannelEvent, trigger_type: str) -> str:
    if trigger_type == "dingtalk_private":
        identity = str(event.source.metadata.get("bot_identity") or "").strip().lower()
        return f"bot:{identity}" if identity else ""
    if trigger_type == "dingtalk_group":
        identity = event.source.conversation_id.strip().lower()
        return f"conversation:{identity}" if identity else ""
    if trigger_type == "webhook":
        identity = event.webhook_trigger_id.strip().lower()
        return f"webhook:{identity}" if identity else ""
    return ""


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
