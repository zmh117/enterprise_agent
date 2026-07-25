from __future__ import annotations

from typing import Any

from app.modules.webhook.application import WebhookTriggerService
from app.modules.webhook.infrastructure import WebhookTriggerRepository


class ManagedWebhookProviderAdapter:
    """Projects and mutates Webhooks through their existing services."""

    def __init__(
        self,
        *,
        repository: WebhookTriggerRepository,
        service: WebhookTriggerService,
    ) -> None:
        self.repository = repository
        self.service = service

    def list_channels(self) -> list[dict[str, Any]]:
        return self.repository.list_definitions()

    def create_channel(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        trigger_type: str,
        connector_id: str,
    ) -> dict[str, Any]:
        return self.service.create(
            actor_id=actor_id,
            code=code,
            name=name,
            trigger_type=trigger_type,
            connector_id=connector_id,
            config=None,
        )
