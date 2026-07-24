from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
from typing import Any


class RuntimeStatus(StrEnum):
    NOT_WIRED = "not_wired"
    PARTIALLY_WIRED = "partially_wired"
    WIRED = "wired"
    BLOCKED = "blocked"


class RuntimeComponentState(StrEnum):
    WIRED = "wired"
    PARTIALLY_WIRED = "partially_wired"
    STORED_ONLY = "stored_only"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class RuntimeComponentImpact(StrEnum):
    RUNTIME = "runtime"
    GOVERNANCE = "governance"


class RouteResolutionOutcome(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    BLOCKED = "blocked"


class RuntimeReason(StrEnum):
    READY = "ready"
    DATA_PLANE_DISABLED = "data_plane_disabled"
    NO_ACTIVE_DEPLOYMENT = "no_active_deployment"
    NOT_CURRENT_RUNTIME_ENVIRONMENT = "not_current_runtime_environment"
    NO_SUPPORTED_ROUTE = "no_supported_route"
    ROUTE_NOT_MATCHED = "route_not_matched"
    LEGACY_ROUTING_KEY = "legacy_routing_key"
    UNSUPPORTED_TRIGGER = "unsupported_trigger"
    UNSUPPORTED_ACTOR_POLICY = "unsupported_actor_policy"
    MISSING_AGENT_PUBLICATION = "missing_agent_publication"
    MISSING_DELIVERY_BINDING = "missing_delivery_binding"
    DUPLICATE_DELIVERY_BINDING = "duplicate_delivery_binding"
    DELIVERY_CONNECTOR_MISMATCH = "delivery_connector_mismatch"
    UNSUPPORTED_DELIVERY = "unsupported_delivery"
    PUBLICATION_INTEGRITY_ERROR = "publication_integrity_error"
    AGENT_OVERRIDE_CONFLICT = "agent_override_conflict"
    WORKFLOW_STORED_ONLY = "workflow_stored_only"
    EXECUTION_POLICY_STORED_ONLY = "execution_policy_stored_only"
    RETENTION_POLICY_STORED_ONLY = "retention_policy_stored_only"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"


@dataclass(frozen=True)
class RuntimeComponentStatus:
    status: RuntimeComponentState
    reason_code: str
    message: str
    fields: dict[str, str] = field(default_factory=dict)
    impact: RuntimeComponentImpact = RuntimeComponentImpact.RUNTIME

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "message": self.message,
            "fields": dict(self.fields),
            "impact": self.impact.value,
        }


@dataclass(frozen=True)
class RuntimeReadiness:
    runtime_wired: bool
    runtime_status: RuntimeStatus
    runtime_environment: str
    deployment_environment: str
    reason_code: str
    message: str
    components: dict[str, RuntimeComponentStatus] = field(default_factory=dict)
    affected_routes: tuple[dict[str, str], ...] = ()
    legacy_fallback_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_wired": self.runtime_wired,
            "runtime_status": self.runtime_status.value,
            "runtime_environment": self.runtime_environment,
            "deployment_environment": self.deployment_environment,
            "reason_code": self.reason_code,
            "message": self.message,
            "runtime_components": {key: value.to_dict() for key, value in self.components.items()},
            "affected_routes": [dict(value) for value in self.affected_routes],
            "legacy_fallback_enabled": self.legacy_fallback_enabled,
        }


@dataclass(frozen=True)
class RuntimeRouteResolution:
    outcome: RouteResolutionOutcome
    reason_code: str
    message: str
    readiness: RuntimeReadiness
    application: dict[str, Any] | None = None
    deployment: dict[str, Any] | None = None
    publication: dict[str, Any] | None = None
    route: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "message": self.message,
            "readiness": self.readiness.to_dict(),
            "application": self.application,
            "deployment": self.deployment,
            "publication": self.publication,
            "route": self.route,
            **self.readiness.to_dict(),
        }


class RuntimeReadinessEvaluator:
    """Pure policy evaluator shared by management and data-plane routing."""

    def __init__(
        self,
        *,
        data_plane_enabled: bool,
        runtime_environment: str,
    ) -> None:
        self.data_plane_enabled = data_plane_enabled
        self.runtime_environment = normalize_deployment_environment(runtime_environment)

    def evaluate(
        self,
        *,
        snapshot: dict[str, Any] | None,
        deployment: dict[str, Any] | None,
    ) -> RuntimeReadiness:
        snapshot = snapshot or {}
        deployment_environment = normalize_deployment_environment(
            str((deployment or {}).get("environment") or "")
        )
        components, blockers, affected_routes = self._components(snapshot)

        if not self.data_plane_enabled:
            return self._not_wired(
                deployment_environment,
                components,
                affected_routes,
                RuntimeReason.DATA_PLANE_DISABLED,
                "Business Application data plane is disabled",
            )
        if deployment is None or not bool(deployment.get("active")):
            return self._not_wired(
                deployment_environment,
                components,
                affected_routes,
                RuntimeReason.NO_ACTIVE_DEPLOYMENT,
                "Business Application has no active deployment",
            )
        if deployment_environment != self.runtime_environment:
            return self._not_wired(
                deployment_environment,
                components,
                affected_routes,
                RuntimeReason.NOT_CURRENT_RUNTIME_ENVIRONMENT,
                "Deployment is not active in this runtime environment",
            )
        if blockers:
            reason, message = blockers[0]
            return RuntimeReadiness(
                runtime_wired=False,
                runtime_status=RuntimeStatus.BLOCKED,
                runtime_environment=self.runtime_environment,
                deployment_environment=deployment_environment,
                reason_code=reason,
                message=message,
                components=components,
                affected_routes=affected_routes,
            )
        supported_routes = [
            route
            for route in affected_routes
            if route["trigger_type"] in {"dingtalk_private", "dingtalk_group"}
        ]
        if not supported_routes:
            return self._not_wired(
                deployment_environment,
                components,
                affected_routes,
                RuntimeReason.NO_SUPPORTED_ROUTE,
                "No supported active DingTalk route is configured",
            )
        partial = any(
            component.status
            in {
                RuntimeComponentState.PARTIALLY_WIRED,
                RuntimeComponentState.STORED_ONLY,
            }
            for component in components.values()
            if component.impact == RuntimeComponentImpact.RUNTIME
        )
        return RuntimeReadiness(
            runtime_wired=True,
            runtime_status=(RuntimeStatus.PARTIALLY_WIRED if partial else RuntimeStatus.WIRED),
            runtime_environment=self.runtime_environment,
            deployment_environment=deployment_environment,
            reason_code=RuntimeReason.READY.value,
            message=(
                "Business Application routing is active; some policies are stored only"
                if partial
                else "Business Application routing is active"
            ),
            components=components,
            affected_routes=affected_routes,
        )

    def empty(
        self,
        *,
        reason: RuntimeReason = RuntimeReason.NO_ACTIVE_DEPLOYMENT,
    ) -> RuntimeReadiness:
        effective_reason = (
            RuntimeReason.DATA_PLANE_DISABLED
            if reason == RuntimeReason.NO_ACTIVE_DEPLOYMENT and not self.data_plane_enabled
            else reason
        )
        message = {
            RuntimeReason.DATA_PLANE_DISABLED: "Business Application data plane is disabled",
            RuntimeReason.ROUTE_NOT_MATCHED: "No active Business Application route matched",
        }.get(effective_reason, "Business Application has no active deployment")
        return self._not_wired(
            "",
            self._default_components(),
            (),
            effective_reason,
            message,
        )

    def activation_errors(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        components, _blockers, _routes = self._components(snapshot)
        return [
            {
                "field": _component_field(name),
                "message": component.message,
                "reason_code": component.reason_code,
            }
            for name, component in components.items()
            if component.status
            in {RuntimeComponentState.BLOCKED, RuntimeComponentState.UNSUPPORTED}
        ]

    def blocked_integrity(
        self,
        *,
        deployment_environment: str,
        reason: RuntimeReason = RuntimeReason.PUBLICATION_INTEGRITY_ERROR,
    ) -> RuntimeReadiness:
        components = self._default_components()
        components["agent_publication"] = RuntimeComponentStatus(
            RuntimeComponentState.BLOCKED,
            reason.value,
            "Business Application publication integrity check failed",
        )
        return RuntimeReadiness(
            runtime_wired=False,
            runtime_status=RuntimeStatus.BLOCKED,
            runtime_environment=self.runtime_environment,
            deployment_environment=deployment_environment,
            reason_code=reason.value,
            message="Business Application runtime configuration is unavailable",
            components=components,
        )

    def _components(
        self, snapshot: dict[str, Any]
    ) -> tuple[
        dict[str, RuntimeComponentStatus],
        list[tuple[str, str]],
        tuple[dict[str, str], ...],
    ]:
        components = self._default_components()
        blockers: list[tuple[str, str]] = []
        agent = snapshot.get("agent") or {}
        if not agent.get("id") or not agent.get("config_hash"):
            components["agent_publication"] = RuntimeComponentStatus(
                RuntimeComponentState.BLOCKED,
                RuntimeReason.MISSING_AGENT_PUBLICATION.value,
                "A valid Agent Publication is required",
            )
            blockers.append(
                (
                    RuntimeReason.MISSING_AGENT_PUBLICATION.value,
                    "Business Application Agent Publication is unavailable",
                )
            )

        triggers = [
            dict(value)
            for value in snapshot.get("triggers") or []
            if bool(value.get("enabled", True))
        ]
        affected_routes: list[dict[str, str]] = []
        trigger_blocked = False
        for trigger in triggers:
            trigger_type = str(trigger.get("trigger_type") or "")
            connector_id = str(trigger.get("connector_id") or "")
            routing_key = (
                str(trigger.get("normalized_routing_key") or trigger.get("routing_key") or "")
                .strip()
                .lower()
            )
            affected_routes.append(
                {
                    "trigger_type": trigger_type,
                    "connector_id": connector_id,
                    "routing_key_summary": summarize_routing_key(routing_key),
                }
            )
            if trigger_type not in {"dingtalk_private", "dingtalk_group"}:
                continue
            expected_prefix = "bot:" if trigger_type == "dingtalk_private" else "conversation:"
            if (
                not routing_key.startswith(expected_prefix)
                or not routing_key[len(expected_prefix) :]
            ):
                trigger_blocked = True
                blockers.append(
                    (
                        RuntimeReason.LEGACY_ROUTING_KEY.value,
                        "DingTalk route uses an unsupported legacy routing key",
                    )
                )
            if str(trigger.get("actor_policy") or "") != "CURRENT_SENDER":
                trigger_blocked = True
                blockers.append(
                    (
                        RuntimeReason.UNSUPPORTED_ACTOR_POLICY.value,
                        "DingTalk routes require CURRENT_SENDER actor policy",
                    )
                )
        if trigger_blocked:
            components["trigger_routing"] = RuntimeComponentStatus(
                RuntimeComponentState.BLOCKED,
                blockers[0][0],
                blockers[0][1],
            )
        elif any(
            str(value.get("trigger_type") or "") in {"dingtalk_private", "dingtalk_group"}
            for value in triggers
        ):
            components["trigger_routing"] = RuntimeComponentStatus(
                RuntimeComponentState.WIRED,
                RuntimeReason.READY.value,
                "Supported DingTalk routes are configured",
            )
        else:
            components["trigger_routing"] = RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.UNSUPPORTED_TRIGGER.value,
                "No supported DingTalk route is configured",
            )

        deliveries = [
            dict(value)
            for value in snapshot.get("deliveries") or []
            if bool(value.get("enabled", True))
        ]
        reply_deliveries = [
            value
            for value in deliveries
            if str(value.get("delivery_type") or "") == "reply_original"
        ]
        supported_triggers = [
            value
            for value in triggers
            if str(value.get("trigger_type") or "") in {"dingtalk_private", "dingtalk_group"}
        ]
        if supported_triggers:
            if not reply_deliveries:
                components["delivery"] = RuntimeComponentStatus(
                    RuntimeComponentState.BLOCKED,
                    RuntimeReason.MISSING_DELIVERY_BINDING.value,
                    "DingTalk routes require reply_original delivery",
                )
                blockers.append(
                    (
                        RuntimeReason.MISSING_DELIVERY_BINDING.value,
                        "Business Application reply-original delivery is missing",
                    )
                )
            elif len(reply_deliveries) != 1:
                components["delivery"] = RuntimeComponentStatus(
                    RuntimeComponentState.BLOCKED,
                    RuntimeReason.DUPLICATE_DELIVERY_BINDING.value,
                    "Exactly one reply_original delivery is required",
                )
                blockers.append(
                    (
                        RuntimeReason.DUPLICATE_DELIVERY_BINDING.value,
                        "Business Application has duplicate reply-original deliveries",
                    )
                )
            else:
                delivery_connector = str(reply_deliveries[0].get("connector_id") or "")
                mismatched = any(
                    str(trigger.get("connector_id") or "") != delivery_connector
                    for trigger in supported_triggers
                )
                if mismatched:
                    components["delivery"] = RuntimeComponentStatus(
                        RuntimeComponentState.BLOCKED,
                        RuntimeReason.DELIVERY_CONNECTOR_MISMATCH.value,
                        "Reply-original connector must match the ingress connector",
                    )
                    blockers.append(
                        (
                            RuntimeReason.DELIVERY_CONNECTOR_MISMATCH.value,
                            "Business Application delivery connector does not match ingress",
                        )
                    )
                else:
                    components["delivery"] = RuntimeComponentStatus(
                        RuntimeComponentState.WIRED,
                        RuntimeReason.READY.value,
                        "Reply-original delivery is configured",
                    )
        elif deliveries:
            components["delivery"] = RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.UNSUPPORTED_DELIVERY.value,
                "Delivery is stored but not connected by this runtime phase",
            )

        session_policy = dict(snapshot.get("session_policy") or {})
        if session_policy:
            components["session_policy"] = RuntimeComponentStatus(
                RuntimeComponentState.WIRED,
                RuntimeReason.READY.value,
                "Conversation loading policy is enforced by the runtime",
                fields={
                    "conversation_mode": "wired",
                    "recent_message_limit": "wired",
                    "continuous_conversation_enabled": "wired",
                    "attachments_enabled": "wired",
                },
            )
            components["retention_policy"] = RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.RETENTION_POLICY_STORED_ONLY.value,
                "Retention is recorded for governance but no automatic cleanup runs",
                fields={"retention_days": "stored_only"},
                impact=RuntimeComponentImpact.GOVERNANCE,
            )

        components["execution_policy"] = RuntimeComponentStatus(
            RuntimeComponentState.WIRED,
            RuntimeReason.READY.value,
            "Execution limits are fixed on each Job and enforced by the worker",
            fields={
                "max_turns": "wired",
                "timeout_seconds": "wired",
                "max_tool_calls": "wired",
            },
        )
        if snapshot.get("workflow"):
            components["workflow"] = RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.WORKFLOW_STORED_ONLY.value,
                "Workflow Publication is stored but not executed",
            )
        capabilities = [
            value
            for value in snapshot.get("capabilities") or []
            if bool(value.get("enabled", True))
        ]
        if capabilities:
            components["capabilities"] = RuntimeComponentStatus(
                RuntimeComponentState.UNSUPPORTED,
                RuntimeReason.CAPABILITY_UNSUPPORTED.value,
                "API Capability runtime is not connected",
            )
            blockers.append(
                (
                    RuntimeReason.CAPABILITY_UNSUPPORTED.value,
                    "API Capability runtime is unavailable",
                )
            )
        return components, blockers, tuple(affected_routes)

    def _default_components(self) -> dict[str, RuntimeComponentStatus]:
        ready = RuntimeComponentStatus(
            RuntimeComponentState.WIRED,
            RuntimeReason.READY.value,
            "Component is ready",
        )
        return {
            "trigger_routing": RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.NO_SUPPORTED_ROUTE.value,
                "No active supported route",
            ),
            "agent_publication": ready,
            "session_policy": ready,
            "retention_policy": RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.RETENTION_POLICY_STORED_ONLY.value,
                "Retention is stored only",
                fields={"retention_days": "stored_only"},
                impact=RuntimeComponentImpact.GOVERNANCE,
            ),
            "delivery": ready,
            "execution_policy": ready,
            "workflow": ready,
            "capabilities": ready,
        }

    def _not_wired(
        self,
        deployment_environment: str,
        components: dict[str, RuntimeComponentStatus],
        affected_routes: tuple[dict[str, str], ...],
        reason: RuntimeReason,
        message: str,
    ) -> RuntimeReadiness:
        return RuntimeReadiness(
            runtime_wired=False,
            runtime_status=RuntimeStatus.NOT_WIRED,
            runtime_environment=self.runtime_environment,
            deployment_environment=deployment_environment,
            reason_code=reason.value,
            message=message,
            components=components,
            affected_routes=affected_routes,
        )


def normalize_deployment_environment(value: str) -> str:
    normalized = value.strip().lower()
    return {
        "prod": "production",
        "stage": "staging",
        "qa": "test",
        "testing": "test",
        "dev": "local",
        "development": "local",
    }.get(normalized, normalized or "local")


def summarize_routing_key(value: str) -> str:
    prefix, separator, identity = value.partition(":")
    if not separator:
        return "legacy"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:10]
    return f"{prefix}:sha256:{digest}"


def _component_field(name: str) -> str:
    return {
        "trigger_routing": "triggers",
        "agent_publication": "agent_publication_id",
        "session_policy": "session_policy",
        "retention_policy": "session_policy.retention_days",
        "delivery": "deliveries",
        "execution_policy": "execution_policy",
        "workflow": "workflow_publication_id",
        "capabilities": "capabilities",
    }.get(name, name)
