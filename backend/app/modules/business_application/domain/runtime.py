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
                "业务应用数据面已停用",
            )
        if deployment is None or not bool(deployment.get("active")):
            return self._not_wired(
                deployment_environment,
                components,
                affected_routes,
                RuntimeReason.NO_ACTIVE_DEPLOYMENT,
                "业务应用没有活动部署",
            )
        if deployment_environment != self.runtime_environment:
            return self._not_wired(
                deployment_environment,
                components,
                affected_routes,
                RuntimeReason.NOT_CURRENT_RUNTIME_ENVIRONMENT,
                "部署未在当前运行环境中激活",
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
                "尚未配置受支持的活动钉钉路由",
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
                "业务应用路由已生效；部分策略仅保存但尚未执行"
                if partial
                else "业务应用路由已生效"
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
            RuntimeReason.DATA_PLANE_DISABLED: "业务应用数据面已停用",
            RuntimeReason.ROUTE_NOT_MATCHED: "没有匹配的活动业务应用路由",
        }.get(effective_reason, "业务应用没有活动部署")
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
            "业务应用发布版本完整性校验失败",
        )
        return RuntimeReadiness(
            runtime_wired=False,
            runtime_status=RuntimeStatus.BLOCKED,
            runtime_environment=self.runtime_environment,
            deployment_environment=deployment_environment,
            reason_code=reason.value,
            message="业务应用运行配置不可用",
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
                "必须选择有效的 Agent 发布版本",
            )
            blockers.append(
                (
                    RuntimeReason.MISSING_AGENT_PUBLICATION.value,
                    "业务应用的 Agent 发布版本不可用",
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
            expected_prefix = {
                "dingtalk_private": "bot:",
                "dingtalk_group": "conversation:",
                "webhook": "webhook:",
            }.get(trigger_type, "")
            if (
                not expected_prefix
                or
                not routing_key.startswith(expected_prefix)
                or not routing_key[len(expected_prefix) :]
            ):
                trigger_blocked = True
                blockers.append(
                    (
                        RuntimeReason.LEGACY_ROUTING_KEY.value,
                        "接入路由使用了不受支持的路由键",
                    )
                )
            expected_actor = (
                "SERVICE_ACCOUNT"
                if trigger_type == "webhook"
                else "CURRENT_SENDER"
            )
            if str(trigger.get("actor_policy") or "") != expected_actor:
                trigger_blocked = True
                blockers.append(
                    (
                        RuntimeReason.UNSUPPORTED_ACTOR_POLICY.value,
                        "接入路由使用了不受支持的主体策略",
                    )
                )
        if trigger_blocked:
            components["trigger_routing"] = RuntimeComponentStatus(
                RuntimeComponentState.BLOCKED,
                blockers[0][0],
                blockers[0][1],
            )
        elif triggers:
            components["trigger_routing"] = RuntimeComponentStatus(
                RuntimeComponentState.WIRED,
                RuntimeReason.READY.value,
                "已配置受支持的接入路由",
            )
        else:
            components["trigger_routing"] = RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.UNSUPPORTED_TRIGGER.value,
                "尚未配置受支持的接入路由",
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
        webhook_triggers = [
            value
            for value in triggers
            if str(value.get("trigger_type") or "") == "webhook"
        ]
        webhook_deliveries = [
            value
            for value in deliveries
            if str(value.get("delivery_type") or "")
            in {"dingtalk_group", "webhook_callback"}
        ]
        delivery_blocked = False
        if supported_triggers:
            if not reply_deliveries:
                delivery_blocked = True
                components["delivery"] = RuntimeComponentStatus(
                    RuntimeComponentState.BLOCKED,
                    RuntimeReason.MISSING_DELIVERY_BINDING.value,
                    "钉钉路由必须配置 reply_original 投递",
                )
                blockers.append(
                    (
                        RuntimeReason.MISSING_DELIVERY_BINDING.value,
                        "业务应用缺少原会话回复投递",
                    )
                )
            elif len(reply_deliveries) != 1:
                delivery_blocked = True
                components["delivery"] = RuntimeComponentStatus(
                    RuntimeComponentState.BLOCKED,
                    RuntimeReason.DUPLICATE_DELIVERY_BINDING.value,
                    "必须且只能配置一个 reply_original 投递",
                )
                blockers.append(
                    (
                        RuntimeReason.DUPLICATE_DELIVERY_BINDING.value,
                        "业务应用配置了重复的原会话回复投递",
                    )
                )
            else:
                delivery_connector = str(reply_deliveries[0].get("connector_id") or "")
                mismatched = any(
                    str(trigger.get("connector_id") or "") != delivery_connector
                    for trigger in supported_triggers
                )
                if mismatched:
                    delivery_blocked = True
                    components["delivery"] = RuntimeComponentStatus(
                        RuntimeComponentState.BLOCKED,
                        RuntimeReason.DELIVERY_CONNECTOR_MISMATCH.value,
                        "原会话回复连接器必须与接入连接器一致",
                    )
                    blockers.append(
                        (
                            RuntimeReason.DELIVERY_CONNECTOR_MISMATCH.value,
                            "业务应用投递连接器与接入连接器不匹配",
                        )
                    )
        if webhook_triggers:
            if len(webhook_deliveries) != 1:
                delivery_blocked = True
                reason = (
                    RuntimeReason.MISSING_DELIVERY_BINDING
                    if not webhook_deliveries
                    else RuntimeReason.DUPLICATE_DELIVERY_BINDING
                )
                components["delivery"] = RuntimeComponentStatus(
                    RuntimeComponentState.BLOCKED,
                    reason.value,
                    "Webhook 必须且只能配置一个受支持的结果投递",
                )
                blockers.append(
                    (
                        reason.value,
                        "Webhook 业务应用结果投递配置无效",
                    )
                )
            else:
                config = webhook_deliveries[0].get("config") or {}
                target_reference = (
                    str(config.get("target_reference") or "")
                    if isinstance(config, dict)
                    else ""
                )
                if not target_reference:
                    delivery_blocked = True
                    components["delivery"] = RuntimeComponentStatus(
                        RuntimeComponentState.BLOCKED,
                        RuntimeReason.MISSING_DELIVERY_BINDING.value,
                        "Webhook 结果投递目标未配置",
                    )
                    blockers.append(
                        (
                            RuntimeReason.MISSING_DELIVERY_BINDING.value,
                            "Webhook 业务应用缺少结果投递目标",
                        )
                    )
        if (supported_triggers or webhook_triggers) and not delivery_blocked:
            components["delivery"] = RuntimeComponentStatus(
                RuntimeComponentState.WIRED,
                RuntimeReason.READY.value,
                "已配置受支持的结果投递",
            )
        elif not (supported_triggers or webhook_triggers) and deliveries:
            components["delivery"] = RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.UNSUPPORTED_DELIVERY.value,
                "投递配置已保存，但当前运行阶段尚未接入",
            )

        session_policy = dict(snapshot.get("session_policy") or {})
        if session_policy:
            components["session_policy"] = RuntimeComponentStatus(
                RuntimeComponentState.WIRED,
                RuntimeReason.READY.value,
                "运行时已执行会话加载策略",
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
                "数据保留策略已用于治理记录，但尚未执行自动清理",
                fields={"retention_days": "stored_only"},
                impact=RuntimeComponentImpact.GOVERNANCE,
            )

        components["execution_policy"] = RuntimeComponentStatus(
            RuntimeComponentState.WIRED,
            RuntimeReason.READY.value,
            "执行限制已固定到每个任务，并由工作进程强制执行",
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
                "工作流发布版本已保存，但尚未执行",
            )
        capabilities = [
            value
            for value in snapshot.get("capabilities") or []
            if bool(value.get("enabled", True))
        ]
        if capabilities:
            components["capabilities"] = RuntimeComponentStatus(
                RuntimeComponentState.WIRED,
                RuntimeReason.READY.value,
                "已装配的只读业务能力将在角色、Agent 和数据范围交集中执行",
                fields={
                    str(value.get("capability_code") or ""): "wired"
                    for value in capabilities
                },
            )
        return components, blockers, tuple(affected_routes)

    def _default_components(self) -> dict[str, RuntimeComponentStatus]:
        ready = RuntimeComponentStatus(
            RuntimeComponentState.WIRED,
            RuntimeReason.READY.value,
            "组件已就绪",
        )
        return {
            "trigger_routing": RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.NO_SUPPORTED_ROUTE.value,
                "没有活动的受支持路由",
            ),
            "agent_publication": ready,
            "session_policy": ready,
            "retention_policy": RuntimeComponentStatus(
                RuntimeComponentState.STORED_ONLY,
                RuntimeReason.RETENTION_POLICY_STORED_ONLY.value,
                "数据保留策略仅保存但尚未执行",
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
