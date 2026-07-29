from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD = "DEAD"
    SKIPPED = "SKIPPED"

    @property
    def terminal(self) -> bool:
        return self in {
            DeliveryStatus.SUCCEEDED,
            DeliveryStatus.FAILED,
            DeliveryStatus.DEAD,
            DeliveryStatus.SKIPPED,
        }


@dataclass(frozen=True)
class DeliveryEvent:
    id: str
    event_key: str
    job_id: str
    result_artifact_id: str
    application_publication_id: str
    delivery_binding: dict[str, Any]
    target_summary: dict[str, Any]
    correlation_id: str
    status: DeliveryStatus
    attempt_count: int
    max_attempts: int
    replay_count: int
    max_replay_count: int
    next_attempt_at: str
    claimed_by: str = ""
    claim_token: str = ""
    claimed_at: str | None = None
    claim_expires_at: str | None = None
    last_error_code: str = ""
    last_error_summary: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    dead_at: str | None = None
    last_replayed_at: str | None = None
    last_replayed_by: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class DeliveryAttempt:
    id: str
    delivery_outbox_id: str
    job_id: str
    replay_no: int
    attempt_no: int
    idempotency_key: str
    correlation_id: str
    status: str
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class DeliveryChunk:
    id: str
    delivery_outbox_id: str
    attempt_id: str
    replay_no: int
    attempt_no: int
    chunk_index: int
    chunk_count: int
    idempotency_key: str
    payload_hash: str
    status: str
    sent_at: str | None = None
    error_message: str = ""
