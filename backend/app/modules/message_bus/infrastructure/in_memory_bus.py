from __future__ import annotations

from collections import deque

from app.modules.message_bus.application.message_publisher import (
    AgentJobHandler,
    AgentJobMessage,
    AttachmentTaskHandler,
    AttachmentTaskMessage,
    WebhookEventHandler,
    WebhookEventMessage,
)


class InMemoryMessageBus:
    def __init__(self) -> None:
        self.jobs: deque[AgentJobMessage] = deque()
        self.retries: deque[tuple[AgentJobMessage, int]] = deque()
        self.dead_letters: deque[tuple[AgentJobMessage, str]] = deque()
        self.attachments: deque[AttachmentTaskMessage] = deque()
        self.attachment_retries: deque[tuple[AttachmentTaskMessage, int]] = deque()
        self.attachment_dead_letters: deque[tuple[AttachmentTaskMessage, str]] = deque()
        self.webhook_events: deque[WebhookEventMessage] = deque()
        self.webhook_dead_letters: deque[tuple[WebhookEventMessage, str]] = deque()

    def publish_agent_job(self, job_id: str, correlation_id: str) -> None:
        self.jobs.append(AgentJobMessage(job_id=job_id, correlation_id=correlation_id))

    def publish_retry(self, job_id: str, correlation_id: str, delay_seconds: int) -> None:
        self.retries.append(
            (AgentJobMessage(job_id=job_id, correlation_id=correlation_id), delay_seconds)
        )

    def publish_dead_letter(self, job_id: str, correlation_id: str, reason: str) -> None:
        self.dead_letters.append(
            (AgentJobMessage(job_id=job_id, correlation_id=correlation_id), reason)
        )

    def consume_agent_jobs(self, handler: AgentJobHandler) -> None:
        while self.jobs:
            handler(self.jobs.popleft())

    def publish_attachment(self, attachment_id: str, correlation_id: str) -> None:
        self.attachments.append(AttachmentTaskMessage(attachment_id, correlation_id))

    def publish_attachment_retry(
        self, attachment_id: str, correlation_id: str, delay_seconds: int
    ) -> None:
        self.attachment_retries.append(
            (AttachmentTaskMessage(attachment_id, correlation_id), delay_seconds)
        )

    def publish_attachment_dead_letter(
        self, attachment_id: str, correlation_id: str, reason: str
    ) -> None:
        self.attachment_dead_letters.append(
            (AttachmentTaskMessage(attachment_id, correlation_id), reason)
        )

    def consume_attachments(self, handler: AttachmentTaskHandler) -> None:
        while self.attachments:
            handler(self.attachments.popleft())

    def publish_webhook_event(self, webhook_event_id: str, correlation_id: str) -> None:
        self.webhook_events.append(WebhookEventMessage(webhook_event_id, correlation_id))

    def publish_webhook_dead_letter(
        self, webhook_event_id: str, correlation_id: str, reason: str
    ) -> None:
        self.webhook_dead_letters.append(
            (WebhookEventMessage(webhook_event_id, correlation_id), reason)
        )

    def consume_webhook_events(self, handler: WebhookEventHandler) -> None:
        while self.webhook_events:
            handler(self.webhook_events.popleft())

    def drain_retry_to_jobs(self) -> None:
        while self.retries:
            message, _delay = self.retries.popleft()
            self.jobs.append(message)
