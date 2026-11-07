from __future__ import annotations

import hmac
from typing import Any, Mapping

from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.webhook.domain.models import is_valid_bearer_token
from app.shared.exceptions import PermissionDenied


class WebhookAuthenticator:
    def __init__(self, *, connector_registry: ConnectorRegistry) -> None:
        self.connector_registry = connector_registry

    def authenticate(
        self,
        *,
        config: dict[str, Any],
        headers: Mapping[str, str],
    ) -> str:
        secret = self.resolve_bearer_credential(config=config)
        if secret is None:
            return "none"
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        provided = lowered.get("authorization", "")
        prefix = "Bearer "
        token = provided[len(prefix) :] if provided.startswith(prefix) else ""
        if not token or not hmac.compare_digest(secret.encode(), token.encode()):
            raise PermissionDenied(
                "Webhook bearer credential is invalid",
                safe_message="Webhook 身份验证失败",
                error_code="webhook_auth_failed",
            )
        return "bearer_v1"

    def resolve_bearer_credential(self, *, config: dict[str, Any]) -> str | None:
        """Return None only for explicitly published unauthenticated ingress."""
        auth = config.get("authentication") or {}
        if auth.get("type") == "none" and auth.get("secret_ref") == "":
            return None
        if str(auth.get("type") or "") != "bearer_v1":
            raise PermissionDenied(
                "Webhook authentication scheme is unsupported",
                safe_message="Webhook 身份验证失败",
                error_code="webhook_auth_failed",
            )
        try:
            secret = self.connector_registry.resolve_reference(auth.get("secret_ref"))
        except Exception as exc:
            raise PermissionDenied(
                "Webhook secret reference could not be resolved",
                safe_message="Webhook 身份验证失败",
                error_code="webhook_auth_failed",
            ) from exc
        if not is_valid_bearer_token(secret):
            raise PermissionDenied(
                "Webhook bearer credential is missing or malformed",
                safe_message="Webhook 身份验证失败",
                error_code="webhook_auth_failed",
            )
        return secret
