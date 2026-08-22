from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.audit.application.audit_service import AuditService
from app.modules.file_workspace.repository import FileWorkspaceRepository


_EVENT_TYPES = {
    "file.attachment.imported",
    "file.version.committed",
    "file.version.conflict_created",
    "file.processing.requested",
    "file.processing.completed",
}
_PAYLOAD_KEYS = {
    "attachment_id",
    "file_id",
    "version_id",
    "job_id",
    "workspace_id",
    "status",
    "size_bytes",
    "content_sha256",
    "format_code",
    "contract_version",
    "run_id",
    "source_version_id",
    "profile_hash",
    "attempt",
    "correlation_id",
    "error_code",
}


@dataclass(frozen=True)
class FileDomainOutboxPublishResult:
    published: int = 0
    failed: int = 0


class FileDomainEventSink(Protocol):
    def publish(self, event: dict[str, Any]) -> None: ...


class AuditFileDomainEventSink:
    """Current bounded consumer for file domain events.

    No RabbitMQ queue is created until a real asynchronous consumer exists.
    """

    def __init__(self, audit_service: AuditService) -> None:
        self.audit_service = audit_service

    def publish(self, event: dict[str, Any]) -> None:
        payload = dict(event["payload"])
        self.audit_service.record(
            "file.domain_event.published",
            status="SUCCEEDED",
            summary="File domain event projected from durable Outbox",
            job_id=str(payload["job_id"]) if payload.get("job_id") else None,
            actor_id="file-worker",
            payload={
                "outbox_id": str(event["id"]),
                "event_type": str(event["event_type"]),
                "aggregate_type": str(event["aggregate_type"]),
                "aggregate_id": str(event["aggregate_id"]),
                **payload,
            },
        )


class CompositeFileDomainEventSink:
    def __init__(self, *sinks: FileDomainEventSink) -> None:
        self.sinks = tuple(sinks)

    def publish(self, event: dict[str, Any]) -> None:
        for sink in self.sinks:
            sink.publish(event)


class FileDomainOutboxPublisher:
    def __init__(
        self,
        repository: FileWorkspaceRepository,
        sink: FileDomainEventSink,
        *,
        worker_id: str = "file-worker-domain-outbox",
    ) -> None:
        self.repository = repository
        self.sink = sink
        self.worker_id = worker_id

    def publish_pending(self, *, limit: int = 100) -> FileDomainOutboxPublishResult:
        published = failed = 0
        for _ in range(min(max(1, int(limit)), 1000)):
            event: dict[str, Any] | None = None
            try:
                with self.repository.database.unit_of_work():
                    event = self.repository.claim_domain_outbox(worker_id=self.worker_id)
                    if event is None:
                        break
                    projected = self._safe_event(event)
                self.sink.publish(projected)
                with self.repository.database.unit_of_work():
                    self.repository.mark_domain_outbox_published(str(event["id"]))
            except Exception as exc:
                if event is not None:
                    self.repository.mark_domain_outbox_failed(
                        str(event["id"]),
                        failure_code=self._safe_error_code(exc),
                    )
                    failed += 1
                break
            published += 1
        return FileDomainOutboxPublishResult(published=published, failed=failed)

    @staticmethod
    def _safe_event(row: dict[str, Any]) -> dict[str, Any]:
        event_type = str(row.get("event_type") or "")
        if event_type not in _EVENT_TYPES:
            raise ValueError("Unsupported File Domain Outbox event type")
        payload = json.loads(str(row.get("payload_json") or "{}"))
        if not isinstance(payload, dict) or not set(payload).issubset(_PAYLOAD_KEYS):
            raise ValueError("Unsafe File Domain Outbox payload")
        required = {
            "version_id",
            "workspace_id",
            "size_bytes",
            "content_sha256",
        }
        if event_type in {"file.processing.requested", "file.processing.completed"}:
            required = {
                "contract_version",
                "run_id",
                "source_version_id",
                "profile_hash",
                "attempt",
                "correlation_id",
            }
            if event_type == "file.processing.completed":
                required.add("status")
        elif event_type == "file.attachment.imported":
            required.add("attachment_id")
        else:
            required.update({"job_id", "status"})
        if not required.issubset(payload):
            raise ValueError("Incomplete File Domain Outbox payload")
        return {
            "id": str(row["id"]),
            "event_type": event_type,
            "aggregate_type": str(row["aggregate_type"]),
            "aggregate_id": str(row["aggregate_id"]),
            "payload": {key: payload[key] for key in sorted(payload)},
        }

    @staticmethod
    def _safe_error_code(exc: Exception) -> str:
        return f"file_domain_outbox_{exc.__class__.__name__.lower()}"[:128]
