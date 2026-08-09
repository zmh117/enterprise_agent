from __future__ import annotations

import hashlib
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.delivery.domain.delivery_outbox import DeliveryEvent
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.exceptions import NonRetryableExecutionError


class DeliveryOperationsService:
    """Safe, exact operational controls for persisted Delivery events."""

    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service

    def status(self, *, delivery_id: str) -> dict[str, object]:
        return _safe_event_status(self._resolve(delivery_id))

    def metrics(self) -> dict[str, object]:
        return self.repository.delivery_metrics()

    def replay(
        self,
        *,
        delivery_id: str,
        actor_id: str,
        reason: str,
        connector_id: str = "",
        target: str = "",
        payload: str = "",
    ) -> dict[str, object]:
        normalized_actor = actor_id.strip()
        normalized_reason = reason.strip()
        if not normalized_actor:
            raise NonRetryableExecutionError(
                "Replay actor is required",
                safe_message="重放操作必须提供操作者标识",
                error_code="delivery_replay_actor_required",
            )
        if not normalized_reason:
            raise NonRetryableExecutionError(
                "Replay reason is required",
                safe_message="重放操作必须提供原因",
                error_code="delivery_replay_reason_required",
            )
        current = self._resolve(delivery_id)
        reason_digest = hashlib.sha256(normalized_reason.encode("utf-8")).hexdigest()
        overrides = {
            "connector": bool(connector_id.strip()),
            "target": bool(target.strip()),
            "payload": bool(payload.strip()),
        }
        if any(overrides.values()):
            with self.repository.database.unit_of_work():
                self.audit_service.record(
                    "delivery.replay.rejected",
                    status="DENIED",
                    summary=(
                        "Delivery replay rejected because persisted intent override was requested"
                    ),
                    job_id=current.job_id,
                    actor_id=normalized_actor,
                    payload={
                        "delivery_id": current.id,
                        "reason_digest": reason_digest,
                        "override_requested": overrides,
                    },
                )
            raise NonRetryableExecutionError(
                "Delivery replay cannot override persisted intent",
                safe_message="投递重放不允许改写 Connector、目标或消息正文",
                error_code="delivery_replay_override_forbidden",
            )

        with self.repository.database.unit_of_work():
            replayed = self.repository.replay_dead_delivery(
                delivery_id=current.id,
                actor_id=normalized_actor,
            )
            self.audit_service.record(
                "delivery.replayed",
                status="SUCCEEDED",
                summary=(
                    "DEAD Delivery was rearmed using its frozen binding and persisted artifact"
                ),
                job_id=replayed.job_id,
                actor_id=normalized_actor,
                payload={
                    "delivery_id": replayed.id,
                    "result_artifact_id": replayed.result_artifact_id,
                    "replay_count": replayed.replay_count,
                    "max_replay_count": replayed.max_replay_count,
                    "reason_digest": reason_digest,
                },
            )
        return _safe_event_status(replayed)

    def _resolve(self, delivery_id: str) -> DeliveryEvent:
        normalized = delivery_id.strip()
        if not normalized:
            raise NonRetryableExecutionError(
                "Delivery ID is required",
                safe_message="必须指定 delivery_id",
                error_code="delivery_exact_identifier_required",
            )
        return self.repository.get_delivery_event(normalized)


def _safe_event_status(event: DeliveryEvent) -> dict[str, object]:
    binding: dict[str, Any] = event.delivery_binding
    return {
        "delivery_id": event.id,
        "job_id": event.job_id,
        "result_artifact_id": event.result_artifact_id,
        "application_publication_id": event.application_publication_id,
        "route_type": str(binding.get("route_type") or "none"),
        "connector_id": str(binding.get("connector_id") or ""),
        "target_summary": event.target_summary,
        "correlation_id": event.correlation_id,
        "status": event.status.value,
        "attempt_count": event.attempt_count,
        "max_attempts": event.max_attempts,
        "replay_count": event.replay_count,
        "max_replay_count": event.max_replay_count,
        "next_attempt_at": event.next_attempt_at,
        "claimed_at": event.claimed_at,
        "started_at": event.started_at,
        "finished_at": event.finished_at,
        "dead_at": event.dead_at,
        "last_replayed_at": event.last_replayed_at,
        "last_replayed_by": event.last_replayed_by,
        "last_error_code": event.last_error_code,
        "last_error_summary": event.last_error_summary,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }
