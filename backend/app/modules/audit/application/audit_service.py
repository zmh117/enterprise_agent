from __future__ import annotations

from typing import Any

from app.modules.audit.application.summaries import bounded_summary
from app.modules.job.infrastructure.repositories import AuditRepository


class AuditService:
    def __init__(self, repository: AuditRepository, max_chars: int = 4000) -> None:
        self.repository = repository
        self.max_chars = max_chars

    def record(
        self,
        event_type: str,
        *,
        status: str,
        summary: str,
        job_id: str | None = None,
        actor_id: str | None = None,
        payload: Any | None = None,
    ) -> str:
        return self.repository.record(
            event_type=event_type,
            status=status,
            summary=summary,
            job_id=job_id,
            actor_id=actor_id,
            payload_summary=bounded_summary(payload or {}, self.max_chars),
        )
