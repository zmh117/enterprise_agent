from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.domain.job_dispatch import JobDispatchStatus
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import QueueSettings
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NotFound, NonRetryableExecutionError


MAX_LEGACY_MESSAGE_BYTES = 64 * 1024


@dataclass(frozen=True)
class CutoverMessageResult:
    source_queue: str
    message_digest: str
    classification: str
    disposition: str
    job_id: str = ""
    event_id: str = ""
    reason_code: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source_queue": self.source_queue,
            "message_digest": self.message_digest,
            "classification": self.classification,
            "disposition": self.disposition,
            "job_id": self.job_id,
            "event_id": self.event_id,
            "reason_code": self.reason_code,
        }


class JobDispatchCutoverService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
        queue_settings: QueueSettings,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.queue_settings = queue_settings
        self.allowed_source_queues = {
            queue_settings.job_queue,
            queue_settings.retry_queue,
            queue_settings.legacy_retry_queue,
            queue_settings.dead_queue,
        }

    def topology_plan(self) -> dict[str, object]:
        names = {
            "current_job_queue": self.queue_settings.job_queue,
            "old_retry_queues": sorted(
                {
                    self.queue_settings.retry_queue,
                    self.queue_settings.legacy_retry_queue,
                }
            ),
            "old_dead_queue": self.queue_settings.dead_queue,
        }
        canonical = json.dumps(
            names,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            **names,
            "topology_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    @operation_unit_of_work(lambda service: service.repository.database)
    def process_message(
        self,
        *,
        source_queue: str,
        body: bytes,
        apply: bool,
        actor_id: str,
    ) -> CutoverMessageResult:
        if source_queue not in self.allowed_source_queues:
            raise NonRetryableExecutionError(
                f"Queue is outside the exact cutover allowlist: {source_queue}",
                safe_message="队列不在本次切换的精确允许清单中",
                error_code="job_dispatch_cutover_queue_not_allowed",
            )
        digest = hashlib.sha256(body).hexdigest()
        if len(body) > MAX_LEGACY_MESSAGE_BYTES:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code="message_too_large",
                apply=apply,
                actor_id=actor_id,
            )
        payload = _safe_object(body)
        if payload is None:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code="invalid_json_object",
                apply=apply,
                actor_id=actor_id,
            )
        event_id = _identifier(payload.get("event_id"))
        job_id = _identifier(payload.get("job_id"))
        correlation_id = _identifier(payload.get("correlation_id"))
        if event_id:
            return self._classify_current_message(
                source_queue=source_queue,
                digest=digest,
                event_id=event_id,
                job_id=job_id,
                correlation_id=correlation_id,
                apply=apply,
                actor_id=actor_id,
            )
        if not job_id:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code="legacy_job_id_missing",
                apply=apply,
                actor_id=actor_id,
            )
        try:
            job = self.repository.get_job(job_id)
        except NotFound:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code="legacy_job_not_found",
                apply=apply,
                actor_id=actor_id,
                job_id=job_id,
            )
        if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.TIMEOUT}:
            return CutoverMessageResult(
                source_queue=source_queue,
                message_digest=digest,
                classification="terminal_duplicate",
                disposition="ack" if apply else "would_ack",
                job_id=job.id,
                reason_code="job_already_terminal",
            )
        if job.status not in {JobStatus.PENDING, JobStatus.RETRY_WAIT}:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code=f"job_status_{job.status.value.lower()}",
                apply=apply,
                actor_id=actor_id,
                job_id=job.id,
            )
        existing = self.repository.get_dispatch_event_for_job(job.id)
        if existing is not None and existing.status == JobDispatchStatus.DEAD:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code="dispatch_event_dead_requires_explicit_replay",
                apply=apply,
                actor_id=actor_id,
                job_id=job.id,
            )
        if not apply:
            return CutoverMessageResult(
                source_queue=source_queue,
                message_digest=digest,
                classification="legacy_convertible",
                disposition="would_ack_after_outbox",
                job_id=job.id,
                event_id=existing.id if existing else "",
            )
        event = existing or self.repository.create_dispatch_event(
            job_id=job.id,
            job_idempotency_key=job.idempotency_key,
            correlation_id=_cutover_correlation(job.id),
            max_attempts=self.queue_settings.dispatch_outbox_max_attempts,
            max_replay_count=self.queue_settings.dispatch_outbox_max_replays,
        )
        target = (
            JobDispatchStatus.RETRY_WAIT
            if job.status == JobStatus.RETRY_WAIT
            else JobDispatchStatus.PENDING
        )
        next_attempt_at = (
            job.next_retry_at
            if job.status == JobStatus.RETRY_WAIT and job.next_retry_at
            else datetime.now(UTC).isoformat()
        )
        event = self.repository.rearm_dispatch_for_cutover(
            job_id=job.id,
            target_status=target,
            next_attempt_at=next_attempt_at,
        )
        self.audit_service.record(
            "job.dispatch.cutover_backfilled",
            status="SUCCEEDED",
            summary="Legacy Agent queue message converted to Job Dispatch Outbox",
            job_id=job.id,
            actor_id=actor_id,
            payload={
                "event_id": event.id,
                "source_queue": source_queue,
                "message_digest": digest,
                "outbox_status": event.status.value,
            },
        )
        return CutoverMessageResult(
            source_queue=source_queue,
            message_digest=digest,
            classification="legacy_converted",
            disposition="ack",
            job_id=job.id,
            event_id=event.id,
        )

    def _classify_current_message(
        self,
        *,
        source_queue: str,
        digest: str,
        event_id: str,
        job_id: str,
        correlation_id: str,
        apply: bool,
        actor_id: str,
    ) -> CutoverMessageResult:
        try:
            event = self.repository.get_dispatch_event(event_id)
        except NotFound:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code="current_event_not_found",
                apply=apply,
                actor_id=actor_id,
                job_id=job_id,
            )
        if event.job_id != job_id or event.correlation_id != correlation_id:
            return self._quarantine(
                source_queue=source_queue,
                digest=digest,
                reason_code="current_identifiers_mismatch",
                apply=apply,
                actor_id=actor_id,
                job_id=event.job_id,
            )
        if source_queue != self.queue_settings.job_queue:
            job = self.repository.get_job(event.job_id)
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.TIMEOUT}:
                return CutoverMessageResult(
                    source_queue=source_queue,
                    message_digest=digest,
                    classification="terminal_duplicate",
                    disposition="ack" if apply else "would_ack",
                    job_id=job.id,
                    event_id=event.id,
                    reason_code="job_already_terminal",
                )
            if job.status != JobStatus.RETRY_WAIT:
                return self._quarantine(
                    source_queue=source_queue,
                    digest=digest,
                    reason_code=f"current_retry_job_status_{job.status.value.lower()}",
                    apply=apply,
                    actor_id=actor_id,
                    job_id=job.id,
                )
            if not apply:
                return CutoverMessageResult(
                    source_queue=source_queue,
                    message_digest=digest,
                    classification="current_retry_convertible",
                    disposition="would_ack_after_outbox",
                    job_id=job.id,
                    event_id=event.id,
                )
            rearmed = self.repository.rearm_dispatch_for_cutover(
                job_id=job.id,
                target_status=JobDispatchStatus.RETRY_WAIT,
                next_attempt_at=job.next_retry_at or datetime.now(UTC).isoformat(),
            )
            return CutoverMessageResult(
                source_queue=source_queue,
                message_digest=digest,
                classification="current_retry_converted",
                disposition="ack",
                job_id=job.id,
                event_id=rearmed.id,
            )
        return CutoverMessageResult(
            source_queue=source_queue,
            message_digest=digest,
            classification="current_contract",
            disposition="requeue",
            job_id=event.job_id,
            event_id=event.id,
        )

    def _quarantine(
        self,
        *,
        source_queue: str,
        digest: str,
        reason_code: str,
        apply: bool,
        actor_id: str,
        job_id: str = "",
    ) -> CutoverMessageResult:
        if apply:
            self.repository.record_dispatch_cutover_quarantine(
                source_queue=source_queue,
                message_digest=digest,
                reason_code=reason_code,
                actor_id=actor_id,
                job_id=job_id,
            )
        return CutoverMessageResult(
            source_queue=source_queue,
            message_digest=digest,
            classification="quarantine",
            disposition="ack" if apply else "would_quarantine",
            job_id=job_id,
            reason_code=reason_code,
        )


def _safe_object(body: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _identifier(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        return ""
    return normalized


def _cutover_correlation(job_id: str) -> str:
    digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:24]
    return f"job-dispatch-cutover:{digest}"
