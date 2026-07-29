from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.modules.admin.domain.channel_providers import CHANNEL_PROVIDERS
from app.modules.platform_config.application.validation import validate_secret_ref
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
            if value:
                try:
                    validate_secret_ref(value)
                except NonRetryableExecutionError as exc:
                    raise _invalid(field, exc.safe_message) from None
        self._validate_metadata_references(payload.get("metadata") or {})
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

    @staticmethod
    def _validate_metadata_references(value: Any, *, path: str = "metadata") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if str(key).endswith("_ref") and child:
                    try:
                        validate_secret_ref(str(child))
                    except NonRetryableExecutionError as exc:
                        raise _invalid(child_path, exc.safe_message) from None
                ChannelProviderService._validate_metadata_references(
                    child,
                    path=child_path,
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                ChannelProviderService._validate_metadata_references(
                    child,
                    path=f"{path}[{index}]",
                )


def _invalid(field: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Invalid Channel connector",
        safe_message="渠道连接器配置无效",
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )
