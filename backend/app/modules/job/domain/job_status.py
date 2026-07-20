from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    WAITING_INPUT = "WAITING_INPUT"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.WAITING_INPUT: {JobStatus.PENDING, JobStatus.FAILED},
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.FAILED},
    JobStatus.RUNNING: {
        JobStatus.RETRY_WAIT,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.TIMEOUT,
    },
    JobStatus.RETRY_WAIT: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.TIMEOUT},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.TIMEOUT: set(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
