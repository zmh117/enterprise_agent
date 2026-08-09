from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center.application import BusinessAuthorizationService
from app.modules.channel.domain.channel_event import ReplyRoute, safe_payload_summary
from app.modules.channel.infrastructure.connector_registry import Connector, ConnectorRegistry
from app.modules.delivery.application.report_chunker import ReportChunker
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import DeliverySettings


class ResultDeliveryService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
        connector_registry: ConnectorRegistry,
        adapters: dict[str, DeliveryAdapter],
        chunker: ReportChunker,
        settings: DeliverySettings,
        business_authorization_service: BusinessAuthorizationService | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.connector_registry = connector_registry
        self.adapters = adapters
        self.chunker = chunker
        self.settings = settings
        self.business_authorization_service = business_authorization_service
        self.sent_messages: list[dict[str, str]] = []

    def enqueue_job_result(
        self,
        *,
        job_id: str,
        artifact_id: str,
        correlation_id: str,
    ) -> str:
        return self._enqueue(
            job_id=job_id,
            artifact_id=artifact_id,
            correlation_id=correlation_id,
            delivery_kind="result",
            title="Agent 诊断报告",
        )

    def enqueue_job_failure(
        self,
        *,
        job_id: str,
        reason: str,
        error_code: str,
        correlation_id: str,
    ) -> str:
        artifact = self.repository.get_artifact_for_job(
            job_id=job_id,
            artifact_type="failure_notification",
            name="delivery-failure.json",
        )
        if artifact is None:
            content = json.dumps(
                {
                    "status": "failed",
                    "error_code": _safe_error_code(error_code),
                    "message": _safe_failure_message(reason),
                    "job_id": job_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            artifact_id = self.repository.add_artifact(
                job_id=job_id,
                artifact_type="failure_notification",
                name="delivery-failure.json",
                content=content,
            )
        else:
            artifact_id = str(artifact["id"])
        return self._enqueue(
            job_id=job_id,
            artifact_id=artifact_id,
            correlation_id=correlation_id,
            delivery_kind="failure",
            title="Agent 诊断失败",
        )

    def _enqueue(
        self,
        *,
        job_id: str,
        artifact_id: str,
        correlation_id: str,
        delivery_kind: str,
        title: str,
    ) -> str:
        job = self.repository.get_job(job_id)
        route = ReplyRoute.from_dict(job.reply_route)
        canonical_route = json.dumps(
            job.reply_route or {"type": "none"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        event = self.repository.create_delivery_event(
            job_id=job.id,
            result_artifact_id=artifact_id,
            application_publication_id=(
                job.business_application_publication_id or job.agent_publication_id
            ),
            delivery_binding={
                "delivery_kind": delivery_kind,
                "title": title,
                "route_type": route.type,
                "connector_id": route.connector_id,
                "route_hash": hashlib.sha256(canonical_route.encode("utf-8")).hexdigest(),
                "route_source": "agent_job.reply_route_json",
            },
            target_summary=_target_summary(route, None),
            correlation_id=correlation_id,
            max_attempts=self.settings.outbox_max_attempts,
            max_replay_count=self.settings.outbox_max_replays,
        )
        self.audit_service.record(
            "delivery.outbox.created",
            status="PENDING",
            summary="Delivery intent persisted for independent dispatch",
            job_id=job.id,
            payload={
                "delivery_id": event.id,
                "delivery_kind": delivery_kind,
                "route_type": route.type,
                "connector_id": route.connector_id,
                **_runtime_context(job),
            },
        )
        return event.id


def _target_summary(route: ReplyRoute, connector: Connector | None) -> dict[str, Any]:
    summary = {
        "route_type": route.type,
        "connector_id": route.connector_id,
        "connector_type": connector.connector_type if connector else "",
        "target": _safe_target(route.target),
    }
    return safe_payload_summary(summary)


def _safe_target(target: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in target.items():
        lowered = key.lower()
        if any(
            token in lowered
            for token in (
                "authorization",
                "callback",
                "credential",
                "endpoint",
                "mobile",
                "secret",
                "sign",
                "token",
                "url",
                "webhook",
            )
        ):
            if isinstance(value, list):
                safe[f"{key}_count"] = len(value)
            elif value:
                safe[key] = "***"
            else:
                safe[key] = ""
        elif isinstance(value, list):
            safe[f"{key}_count"] = len(value)
        else:
            safe[key] = value
    return safe


def _safe_error_code(value: str) -> str:
    normalized = "".join(char for char in value if char.isalnum() or char in {"_", "-"})
    return normalized[:80] or "agent_runtime_error"


def _safe_failure_message(reason: str) -> str:
    lowered = reason.lower()
    if any(token in lowered for token in ("token", "secret", "api_key", "authorization", "http")):
        return "Agent 运行失败，系统已记录脱敏诊断信息，请联系管理员并提供 Job 标识。"
    return reason[:500] or "Agent 运行失败，请联系管理员并提供 Job 标识。"


def _runtime_context(job: Any) -> dict[str, str]:
    decision = (
        job.business_application_route_decision
        if isinstance(job.business_application_route_decision, dict)
        else {}
    )
    return {
        "correlation_id": str(decision.get("correlation_id") or ""),
        "external_event_id": job.external_event_id,
        "business_application_code": job.business_application_code,
        "business_application_publication_id": (job.business_application_publication_id),
        "business_application_deployment_id": (job.business_application_deployment_id),
        "business_application_route_id": job.business_application_route_id,
    }
