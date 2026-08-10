from __future__ import annotations

from dataclasses import dataclass
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

    def publish_webhook_event(
        self, webhook_event_id: str, correlation_id: str
    ) -> None: ...

    def publish_webhook_dead_letter(
        self, webhook_event_id: str, correlation_id: str, reason: str
    ) -> None: ...

    def publish_channel_event(
        self, channel_event_id: str, correlation_id: str
    ) -> None: ...

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
