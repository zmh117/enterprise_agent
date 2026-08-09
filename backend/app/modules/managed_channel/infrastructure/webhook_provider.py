from __future__ import annotations

from typing import Any

from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.webhook.application import WebhookTriggerService
from app.modules.webhook.domain.models import is_strong_bearer_token
from app.modules.webhook.infrastructure import WebhookTriggerRepository


class ManagedWebhookProviderAdapter:
    """Projects and mutates Webhooks through their existing services."""

    def __init__(
        self,
        *,
        repository: WebhookTriggerRepository,
        service: WebhookTriggerService,
        connector_registry: ConnectorRegistry,
    ) -> None:
        self.repository = repository
        self.service = service
        self.connector_registry = connector_registry

    def list_channels(self) -> list[dict[str, Any]]:
        return [self._with_runtime_status(item) for item in self.repository.list_definitions()]

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

    def _with_runtime_status(self, item: dict[str, Any]) -> dict[str, Any]:
        if str(item.get("status") or "") != "enabled":
            return {
                **item,
                "runtime_status": "STOPPED",
                "last_error_summary": "",
            }
        try:
            self.connector_registry.require_ingress(str(item["connector_id"]))
            publication = self.repository.current_publication(str(item["id"]))
            authentication = publication["snapshot"].get("authentication") or {}
            secret = self.connector_registry.resolve_reference(authentication.get("secret_ref"))
            if str(authentication.get("type") or "") != "bearer_v1" or not is_strong_bearer_token(
                secret
            ):
                raise ValueError("Webhook Bearer credential is unavailable")
        except Exception:
            return {
                **item,
                "runtime_status": "MISCONFIGURED",
                "last_error_summary": (
                    "Webhook 凭据缺失、已停用或无法解析，请重新绑定并重新发布后测试"
                ),
            }
        return {
            **item,
            "runtime_status": "READY",
            "last_error_summary": "",
        }
