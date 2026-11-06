from __future__ import annotations

from typing import Any

from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.webhook.application import WebhookTriggerService
from app.modules.webhook.application.authentication import WebhookAuthenticator
from app.modules.webhook.infrastructure import WebhookTriggerRepository
from app.shared.exceptions import AppError, PermissionDenied


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
        self.authenticator = WebhookAuthenticator(connector_registry=connector_registry)

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
            if (
                item.get("execution_user_status") != "enabled"
                or item.get("execution_user_type") != "human"
            ):
                raise PermissionDenied(
                    "Webhook execution user is disabled",
                    safe_message="Webhook 执行用户已停用",
                    error_code="webhook_disabled",
                )
            self.connector_registry.require_ingress(str(item["connector_id"]))
            publication = self.repository.current_publication(str(item["id"]))
            self.authenticator.resolve_bearer_credential(config=publication["snapshot"])
        except Exception as exc:
            if isinstance(exc, AppError) and exc.error_code == "webhook_auth_failed":
                message = "Webhook 凭据缺失、已停用或无法解析，请重新绑定并重新发布后测试"
            elif isinstance(exc, AppError):
                message = exc.safe_message
            else:
                message = "Webhook 入口配置不可用，请检查发布版本、连接器和执行用户"
            return {
                **item,
                "runtime_status": "MISCONFIGURED",
                "last_error_summary": message,
            }
        return {
            **item,
            "runtime_status": "READY",
            "last_error_summary": "",
        }
