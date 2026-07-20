from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied

DINGTALK_STREAM_CONNECTOR_TYPE = "dingtalk_enterprise_stream"
DELIVERY_ONLY_CONNECTOR_TYPES = {
    "dingtalk_enterprise_robot",
    "dingtalk_webhook_robot",
    "email",
    "webhook",
    "none",
}
INGRESS_ONLY_CONNECTOR_TYPES = {
    "debug_api",
    "grafana_alert",
    DINGTALK_STREAM_CONNECTOR_TYPE,
}


@dataclass(frozen=True)
class Connector:
    id: str
    connector_type: str
    name: str
    base_url: str
    enabled: bool
    allow_ingress: bool
    allow_delivery: bool
    secret_ref: str
    endpoint_ref: str
    host_allowlist: tuple[str, ...]
    metadata: dict[str, object]


class ConnectorRegistry:
    def __init__(self, repository: ConfigurationRepository) -> None:
        self.repository = repository

    def get(self, connector_id: str) -> Connector | None:
        row = self.repository.get_connector(connector_id)
        return _connector_from_row(row) if row else None

    def require_ingress(self, connector_id: str) -> Connector:
        connector = self._require(connector_id)
        if (
            not connector.enabled
            or not connector.allow_ingress
            or connector.connector_type in DELIVERY_ONLY_CONNECTOR_TYPES
        ):
            raise PermissionDenied(
                f"Connector {connector_id} is not allowed for ingress",
                safe_message="Connector is not allowed for ingress",
            )
        return connector

    def require_delivery(self, connector_id: str) -> Connector:
        connector = self._require(connector_id)
        if (
            not connector.enabled
            or not connector.allow_delivery
            or connector.connector_type in INGRESS_ONLY_CONNECTOR_TYPES
        ):
            raise NonRetryableExecutionError(
                f"Connector {connector_id} is not allowed for delivery",
                safe_message="Connector is not allowed for delivery",
            )
        return connector

    def require_dingtalk_stream_ingress(self, connector_id: str) -> Connector:
        connector = self.require_ingress(connector_id)
        if connector.connector_type != DINGTALK_STREAM_CONNECTOR_TYPE:
            raise PermissionDenied(
                f"Connector {connector_id} is not a DingTalk Stream ingress connector",
                safe_message="Connector is not a DingTalk Stream ingress connector",
            )
        return connector

    def resolve_secret(self, connector: Connector) -> str:
        return self.resolve_reference(connector.secret_ref)

    def resolve_reference(self, value: object) -> str:
        text = str(value or "")
        if not text:
            return ""
        if text.startswith("env:"):
            return os.getenv(text.removeprefix("env:"), "")
        connector_prefix = "secret://connector/"
        if text.startswith(connector_prefix):
            connector = self.get(text.removeprefix(connector_prefix))
            if connector is None or connector.secret_ref == text:
                return ""
            return self.resolve_reference(connector.secret_ref)
        if text.startswith(("secret://", "vault:", "kms:")):
            return ""
        return text

    def resolve_metadata_reference(self, connector: Connector, key: str) -> str:
        value = connector.metadata.get(key)
        if value is None:
            return ""
        return self.resolve_reference(value)

    def metadata_value(self, connector: Connector, key: str) -> str:
        value = connector.metadata.get(key)
        if value is None:
            return ""
        return str(value)

    def metadata_list(self, connector: Connector, key: str) -> list[str]:
        value = connector.metadata.get(key)
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str) and value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    def resolved_endpoint_url(self, connector: Connector) -> str:
        return self.resolve_reference(connector.endpoint_ref) or connector.base_url

    def resolve_secret_legacy(self, connector: Connector) -> str:
        if not connector.secret_ref:
            return ""
        if connector.secret_ref.startswith("env:"):
            return os.getenv(connector.secret_ref.removeprefix("env:"), "")
        return connector.secret_ref

    def endpoint_url(self, connector: Connector) -> str:
        return self.resolved_endpoint_url(connector)

    def assert_host_allowed(self, connector: Connector, url: str) -> None:
        if not url:
            return
        parsed = urlparse(url)
        if connector.host_allowlist and parsed.hostname not in connector.host_allowlist:
            raise NonRetryableExecutionError(
                f"Delivery host {parsed.hostname} is not allowed",
                safe_message="Delivery host is not allowed",
            )

    def _require(self, connector_id: str) -> Connector:
        connector = self.get(connector_id)
        if connector is None:
            raise NonRetryableExecutionError(
                f"Unknown connector: {connector_id}",
                safe_message="Connector is not configured",
            )
        return connector


def _connector_from_row(row: dict[str, object]) -> Connector:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    host_allowlist = row.get("host_allowlist")
    hosts = tuple(item.strip() for item in str(host_allowlist or "").split(",") if item.strip())
    return Connector(
        id=str(row["id"]),
        connector_type=str(row["connector_type"]),
        name=str(row["name"]),
        base_url=str(row.get("base_url") or ""),
        enabled=_bool_value(row.get("enabled")),
        allow_ingress=_bool_value(row.get("allow_ingress")),
        allow_delivery=_bool_value(row.get("allow_delivery")),
        secret_ref=str(row.get("secret_ref") or ""),
        endpoint_ref=str(row.get("endpoint_ref") or ""),
        host_allowlist=hosts,
        metadata=metadata,
    )


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return False
