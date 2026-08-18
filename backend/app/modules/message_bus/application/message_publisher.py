from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class AgentJobMessage:
    event_id: str
    job_id: str
    correlation_id: str
    redelivered: bool = False


@dataclass(frozen=True)
class AttachmentTaskMessage:
    attachment_id: str
    correlation_id: str


@dataclass(frozen=True)
class WebhookEventMessage:
    webhook_event_id: str
    correlation_id: str


@dataclass(frozen=True)
class ChannelEventMessage:
    channel_event_id: str
    correlation_id: str


@dataclass(frozen=True)
class FileProcessingTaskMessage:
    contract_version: str
    run_id: str
    source_version_id: str
    profile_hash: str
    attempt: int
    correlation_id: str
    redelivered: bool = False

    def safe_payload(self) -> dict[str, str | int]:
        return {
            "contract_version": self.contract_version,
            "run_id": self.run_id,
            "source_version_id": self.source_version_id,
            "profile_hash": self.profile_hash,
            "attempt": self.attempt,
            "correlation_id": self.correlation_id,
        }


class FileProcessingDisposition(StrEnum):
    ACK = "ACK"
    RETRY = "RETRY"
    DEAD = "DEAD"


@dataclass(frozen=True)
class FileProcessingTaskResult:
    disposition: FileProcessingDisposition
    error_code: str = ""
    delay_seconds: int = 0


class MessagePublisher(Protocol):
    def publish_agent_job(
        self,
        event_id: str,
        job_id: str,
        correlation_id: str,
    ) -> None: ...

    def publish_attachment(self, attachment_id: str, correlation_id: str) -> None: ...

    def publish_attachment_retry(
        self, attachment_id: str, correlation_id: str, delay_seconds: int
    ) -> None: ...

    def publish_attachment_dead_letter(
        self, attachment_id: str, correlation_id: str, reason: str
    ) -> None: ...

    def publish_webhook_event(self, webhook_event_id: str, correlation_id: str) -> None: ...

    def publish_webhook_dead_letter(
        self, webhook_event_id: str, correlation_id: str, reason: str
    ) -> None: ...

    def publish_channel_event(self, channel_event_id: str, correlation_id: str) -> None: ...

    def publish_channel_dead_letter(
        self, channel_event_id: str, correlation_id: str, reason: str
    ) -> None: ...


class MessageConsumer(Protocol):
    def consume_agent_jobs(self, handler: "AgentJobHandler") -> None: ...

    def consume_webhook_events(self, handler: "WebhookEventHandler") -> None: ...

    def consume_channel_events(self, handler: "ChannelEventHandler") -> None: ...


class AgentJobHandler(Protocol):
    def __call__(self, message: AgentJobMessage) -> None: ...


class AttachmentTaskHandler(Protocol):
    def __call__(self, message: AttachmentTaskMessage) -> None: ...


class WebhookEventHandler(Protocol):
    def __call__(self, message: WebhookEventMessage) -> None: ...


class ChannelEventHandler(Protocol):
    def __call__(self, message: ChannelEventMessage) -> None: ...


class FileProcessingTaskHandler(Protocol):
    def __call__(self, message: FileProcessingTaskMessage) -> FileProcessingTaskResult: ...
