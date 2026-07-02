from __future__ import annotations

import json
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.domain.channel_event import ReplyRoute, safe_payload_summary
from app.modules.channel.infrastructure.connector_registry import Connector, ConnectorRegistry
from app.modules.delivery.application.report_chunker import ReportChunker
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter, NoneDeliveryAdapter
from app.modules.job.infrastructure.repositories import AgentRepository


class ResultDeliveryService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
        connector_registry: ConnectorRegistry,
        adapters: dict[str, DeliveryAdapter],
        chunker: ReportChunker,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.connector_registry = connector_registry
        self.adapters = adapters
        self.chunker = chunker
        self.sent_messages: list[dict[str, str]] = []

    def deliver_job_result(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if not job.result:
            return
        self._deliver(
            job_id=job.id,
            route=ReplyRoute.from_dict(job.reply_route),
            title="Agent diagnostic report",
            text=job.result,
        )

    def deliver_job_failure(self, job_id: str, reason: str) -> None:
        job = self.repository.get_job(job_id)
        text = json.dumps({"status": "failed", "reason": reason}, ensure_ascii=False)
        self._deliver(
            job_id=job.id,
            route=ReplyRoute.from_dict(job.reply_route),
            title="Agent diagnostic failed",
            text=text,
        )

    def has_completed_delivery(self, job_id: str) -> bool:
        attempts = self.repository.list_delivery_attempts(job_id)
        return any(str(attempt["status"]) in {"SUCCEEDED", "SKIPPED"} for attempt in attempts)

    def _deliver(self, *, job_id: str, route: ReplyRoute, title: str, text: str) -> None:
        if self.has_completed_delivery(job_id):
            return
        connector: Connector | None = None
        if route.type != "none" and route.connector_id:
            try:
                connector = self.connector_registry.require_delivery(route.connector_id)
                self.audit_service.record(
                    "delivery.connector_authorized",
                    status="SUCCEEDED",
                    summary="Delivery connector authorized",
                    job_id=job_id,
                    payload={"route_type": route.type, "connector_id": route.connector_id},
                )
                endpoint = self.connector_registry.endpoint_url(connector)
                self.connector_registry.assert_host_allowed(connector, endpoint)
            except Exception as exc:
                self._record_config_failure(job_id, route, exc)
                return
        target_summary = _target_summary(route, connector)
        attempt_id = self.repository.add_delivery_attempt(
            job_id=job_id,
            route_type=route.type,
            connector_id=route.connector_id,
            target_summary=target_summary,
            status="STARTED",
        )
        self.audit_service.record(
            "delivery.started",
            status="STARTED",
            summary="Result delivery started",
            job_id=job_id,
            payload={"route_type": route.type, "connector_id": route.connector_id},
        )
        if route.type == "none":
            self.repository.update_delivery_attempt(attempt_id, status="SKIPPED")
            self.audit_service.record(
                "delivery.skipped",
                status="SKIPPED",
                summary="Delivery route is none",
                job_id=job_id,
                payload={"attempt_id": attempt_id},
            )
            return
        adapter = self.adapters.get(route.type, self.adapters.get("webhook", NoneDeliveryAdapter()))
        chunks = self.chunker.titled_chunks(title=title, text=text)
        for index, (chunk_title, chunk_text) in enumerate(chunks, start=1):
            try:
                adapter.send(connector=connector, route=route, title=chunk_title, text=chunk_text)
                self.sent_messages.append(
                    {"title": chunk_title, "text": chunk_text, "route_type": route.type}
                )
                self.repository.add_delivery_chunk(
                    attempt_id=attempt_id,
                    chunk_index=index,
                    chunk_count=len(chunks),
                    status="SUCCEEDED",
                    payload_summary={"title": chunk_title, "chars": len(chunk_text)},
                )
                self.audit_service.record(
                    "delivery.chunk_sent",
                    status="SUCCEEDED",
                    summary="Delivery chunk sent",
                    job_id=job_id,
                    payload={
                        "attempt_id": attempt_id,
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                    },
                )
            except Exception as exc:
                safe_message = getattr(exc, "safe_message", str(exc))
                self.repository.add_delivery_chunk(
                    attempt_id=attempt_id,
                    chunk_index=index,
                    chunk_count=len(chunks),
                    status="FAILED",
                    payload_summary={"title": chunk_title, "chars": len(chunk_text)},
                    error_message=safe_message,
                )
                self.repository.update_delivery_attempt(
                    attempt_id, status="FAILED", error_message=safe_message
                )
                self.audit_service.record(
                    "delivery.failed",
                    status="FAILED",
                    summary=safe_message,
                    job_id=job_id,
                    payload={"attempt_id": attempt_id, "chunk_index": index},
                )
                return
        self.repository.update_delivery_attempt(attempt_id, status="SUCCEEDED")
        self.audit_service.record(
            "delivery.completed",
            status="SUCCEEDED",
            summary="Result delivery completed",
            job_id=job_id,
            payload={"attempt_id": attempt_id, "chunk_count": len(chunks)},
        )

    def _record_config_failure(self, job_id: str, route: ReplyRoute, exc: Exception) -> None:
        safe_message = getattr(exc, "safe_message", str(exc))
        attempt_id = self.repository.add_delivery_attempt(
            job_id=job_id,
            route_type=route.type,
            connector_id=route.connector_id,
            target_summary=_target_summary(route, None),
            status="FAILED",
            error_message=safe_message,
        )
        self.audit_service.record(
            "delivery.failed",
            status="FAILED",
            summary=safe_message,
            job_id=job_id,
            payload={
                "attempt_id": attempt_id,
                "route_type": route.type,
                "connector_id": route.connector_id,
            },
        )


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
        if any(token in lowered for token in ("token", "secret", "sign", "url", "mobile")):
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
