from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JobDispatchStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    PUBLISHED = "PUBLISHED"
    DEAD = "DEAD"

    @property
    def terminal(self) -> bool:
        return self in {JobDispatchStatus.PUBLISHED, JobDispatchStatus.DEAD}


@dataclass(frozen=True)
class JobDispatchEvent:
    id: str
    event_key: str
    idempotency_key: str
    job_id: str
    correlation_id: str
    status: JobDispatchStatus
    attempt_count: int
    max_attempts: int
    replay_count: int
    max_replay_count: int
    next_attempt_at: str
    claimed_by: str = ""
    claimed_at: str | None = None
    published_at: str | None = None
    dead_at: str | None = None
    last_replayed_at: str | None = None
    last_replayed_by: str = ""
    last_error_code: str = ""
    last_error_summary: str = ""
    created_at: str = ""
    updated_at: str = ""


def can_transition_dispatch(
    current: JobDispatchStatus,
    target: JobDispatchStatus,
) -> bool:
    return target in {
        JobDispatchStatus.PENDING: {
            JobDispatchStatus.RUNNING,
            JobDispatchStatus.DEAD,
        },
        JobDispatchStatus.RUNNING: {
            JobDispatchStatus.PUBLISHED,
            JobDispatchStatus.RETRY_WAIT,
            JobDispatchStatus.DEAD,
        },
        JobDispatchStatus.RETRY_WAIT: {
            JobDispatchStatus.RUNNING,
            JobDispatchStatus.DEAD,
        },
        JobDispatchStatus.PUBLISHED: set(),
        JobDispatchStatus.DEAD: set(),
    }[current]
