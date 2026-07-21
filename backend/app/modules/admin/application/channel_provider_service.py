from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.modules.admin.domain.channel_providers import CHANNEL_PROVIDERS
from app.shared.exceptions import NonRetryableExecutionError


class ChannelProviderService:
    def catalog(self) -> list[dict[str, Any]]:
        return [dict(item) for item in CHANNEL_PROVIDERS]

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        connector_type = str(payload.get("connector_type") or "")
        provider = next(
            (item for item in CHANNEL_PROVIDERS if item["code"] == connector_type), None
        )
        if provider is None or not provider["available"]:
            raise _invalid("connector_type", "Channel provider is not available")
        ingress = bool(payload.get("allow_ingress"))
        delivery = bool(payload.get("allow_delivery"))
        directions = ({"ingress"} if ingress else set()) | ({"delivery"} if delivery else set())
        if not directions or not directions.issubset(set(provider["directions"])):
            raise _invalid("direction", "Connector direction is not supported by this provider")
        for field in provider["required"]:
            value: Any = payload
            for part in field.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if not value:
                raise _invalid(field, "Field is required")
        for field in ("secret_ref", "endpoint_ref"):
            value = str(payload.get(field) or "")
            if value and not value.startswith(("env:", "secret://", "vault:", "kms:")):
                raise _invalid(field, "Only managed references are allowed")
        base_url = str(payload.get("base_url") or "")
        if base_url:
            parsed = urlparse(base_url)
            allowlist = {str(value) for value in payload.get("host_allowlist") or []}
            if parsed.scheme != "https" or not parsed.hostname or parsed.hostname not in allowlist:
                raise _invalid("base_url", "Endpoint must use HTTPS and an allowlisted host")
        text = str(payload.get("metadata") or {}).lower()
        if any(key in text for key in ("password", "access_token", "client_secret", "api_key")):
            raise _invalid("metadata", "Plaintext credentials are forbidden")
        return {"status": "valid", "summary": "Configuration is valid; no message was sent"}


def _invalid(field: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Invalid Channel connector",
        safe_message="Channel connector configuration is invalid",
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )
