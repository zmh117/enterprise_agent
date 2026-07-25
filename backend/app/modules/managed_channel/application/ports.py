from __future__ import annotations

from typing import Any, Protocol


class ManagedWebhookProviderPort(Protocol):
    """Provider boundary for the existing Managed Webhook bounded context."""

    def list_channels(self) -> list[dict[str, Any]]: ...

    def create_channel(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        trigger_type: str,
        connector_id: str,
    ) -> dict[str, Any]: ...
