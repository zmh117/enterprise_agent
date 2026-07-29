from __future__ import annotations

from collections.abc import Callable
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
SECRET_REQUIRED_CONNECTOR_TYPES = {
    DINGTALK_STREAM_CONNECTOR_TYPE,
    "dingtalk_callback",
    "dingtalk_enterprise_robot",
    "dingtalk_webhook_robot",
    "email",
    "grafana_alert",
    "webhook",
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


@dataclass(frozen=True)
class ConnectorOperationalStatus:
    status: str
    error_code: str = ""
    safe_message: str = ""


class ConnectorRegistry:
    def __init__(
        self,
        repository: ConfigurationRepository,
        reference_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self.repository = repository
        self.reference_resolver = reference_resolver

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
                safe_message="该连接器不允许用于消息接入",
            )
        self._require_configured(connector, for_ingress=True)
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
                safe_message="该连接器不允许用于结果投递",
            )
        self._require_configured(connector, for_ingress=False)
        return connector

    def require_dingtalk_stream_ingress(self, connector_id: str) -> Connector:
        connector = self.require_ingress(connector_id)
        if connector.connector_type != DINGTALK_STREAM_CONNECTOR_TYPE:
            raise PermissionDenied(
                f"Connector {connector_id} is not a DingTalk Stream ingress connector",
                safe_message="该连接器不是钉钉 Stream 接入连接器",
            )
        return connector

    def resolve_secret(self, connector: Connector) -> str:
        return self.resolve_reference(connector.secret_ref)

    def resolve_reference(self, value: object) -> str:
        return self._resolve_reference(value)

    def operational_status(self, connector: Connector) -> ConnectorOperationalStatus:
        if self.requires_secret(connector):
            try:
                secret = self.resolve_secret(connector)
            except Exception:
                secret = ""
            if not secret:
                return ConnectorOperationalStatus(
                    status="MISCONFIGURED",
                    error_code="connector_secret_unavailable",
                    safe_message="连接器凭据缺失、已停用或无法解析，请重新绑定后测试",
                )
        if not connector.enabled:
            return ConnectorOperationalStatus(status="DISABLED")
        return ConnectorOperationalStatus(status="READY")

    def requires_secret(self, connector: Connector) -> bool:
        return connector.connector_type in SECRET_REQUIRED_CONNECTOR_TYPES

    def _resolve_reference(self, value: object) -> str:
        text = str(value or "")
        if not text:
            return ""
        if text.startswith("env:"):
            raise NonRetryableExecutionError(
                "env connector references require explicit import",
                safe_message="env 凭据引用必须先导入凭据中心",
            )
        if text.startswith("secret://platform/") and self.reference_resolver is not None:
            return self.reference_resolver(text)
        if text.startswith(("vault:", "kms:")):
            raise NonRetryableExecutionError(
                "Reserved secret provider is not implemented",
                safe_message="Provider 尚未实现",
            )
        raise NonRetryableExecutionError(
            "Unsupported connector secret reference",
            safe_message="连接器只能使用凭据中心 Secret",
        )

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

    def endpoint_url(self, connector: Connector) -> str:
        return self.resolved_endpoint_url(connector)

    def assert_host_allowed(self, connector: Connector, url: str) -> None:
        if not url:
            return
        parsed = urlparse(url)
        if connector.host_allowlist and parsed.hostname not in connector.host_allowlist:
            raise NonRetryableExecutionError(
                f"Delivery host {parsed.hostname} is not allowed",
                safe_message="不允许使用此投递主机",
            )

    def _require(self, connector_id: str) -> Connector:
        connector = self.get(connector_id)
        if connector is None:
            raise NonRetryableExecutionError(
                f"Unknown connector: {connector_id}",
                safe_message="连接器尚未配置",
            )
        return connector

    def _require_configured(self, connector: Connector, *, for_ingress: bool) -> None:
        status = self.operational_status(connector)
        if status.status != "MISCONFIGURED":
            return
        error_type = PermissionDenied if for_ingress else NonRetryableExecutionError
        raise error_type(
            f"Connector {connector.id} is misconfigured",
            safe_message=status.safe_message,
            error_code=status.error_code,
        )


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
