from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentJobMessage:
    job_id: str
    correlation_id: str


@dataclass(frozen=True)
class AttachmentTaskMessage:
    attachment_id: str
    correlation_id: str


class MessagePublisher(Protocol):
    def publish_agent_job(self, job_id: str, correlation_id: str) -> None: ...

    def publish_retry(self, job_id: str, correlation_id: str, delay_seconds: int) -> None: ...

    def publish_dead_letter(self, job_id: str, correlation_id: str, reason: str) -> None: ...

    def publish_attachment(self, attachment_id: str, correlation_id: str) -> None: ...

    def publish_attachment_retry(
        self, attachment_id: str, correlation_id: str, delay_seconds: int
    ) -> None: ...

    def publish_attachment_dead_letter(
        self, attachment_id: str, correlation_id: str, reason: str
    ) -> None: ...


class MessageConsumer(Protocol):
    def consume_agent_jobs(self, handler: "AgentJobHandler") -> None: ...


class AgentJobHandler(Protocol):
    def __call__(self, message: AgentJobMessage) -> None: ...


class AttachmentTaskHandler(Protocol):
    def __call__(self, message: AttachmentTaskMessage) -> None: ...
