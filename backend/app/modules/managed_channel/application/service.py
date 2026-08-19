from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Never, Protocol

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.dingding.application.dingtalk_stream_service import (
    DingTalkQuotedMessage,
    DingTalkStreamMessageService,
)
from app.modules.identity_discovery.application import DingTalkIdentityDiscoveryService
from app.modules.message_bus.application.message_publisher import (
    ChannelEventMessage,
    MessagePublisher,
)
from app.modules.platform_config.application.secrets import SecretProviderPort
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import AppError, NonRetryableExecutionError, NotFound

from ..domain import (
    ChannelIngressSubmission,
    DingTalkApplicationInput,
    DingTalkEnterpriseStatus,
    RuntimeConnectorState,
    normalize_dingtalk_corp_id,
    require_dingtalk_enterprise_transition,
    require_immutable_dingtalk_corp_id,
)
from ..infrastructure import ManagedChannelRepository
from .ports import ManagedWebhookProviderPort

_ALLOWED_RUNTIME_STATES = {
    "STOPPED",
    "STARTING",
    "CONNECTED",
    "REGISTERED",
    "RECONNECTING",
    "AUTH_FAILED",
    "ERROR",
}
_CODE_RE = re.compile(r"[^a-z0-9-]+")


class ChannelCredentialCipher(Protocol):
    def encrypt(self, value: str) -> str: ...

    def decrypt(self, value: str) -> str: ...


class ManagedChannelService:
    def __init__(
        self,
        *,
        repository: ManagedChannelRepository,
        webhook_provider: ManagedWebhookProviderPort,
        secret_provider: SecretProviderPort,
        connector_registry: ConnectorRegistry,
        audit_service: AuditService,
        stale_seconds: int = 30,
    ) -> None:
        self.repository = repository
        self.webhook_provider = webhook_provider
        self.secret_provider = secret_provider
        self.connector_registry = connector_registry
        self.audit_service = audit_service
        self.stale_seconds = max(stale_seconds, 10)

    def list_channels(self) -> list[dict[str, Any]]:
        result = [
            self._dingtalk_public(item) for item in self.repository.list_dingtalk_connectors()
        ]
        for item in self.webhook_provider.list_channels():
            runtime_status = str(
                item.get("runtime_status")
                or ("READY" if str(item["status"]) == "enabled" else "STOPPED")
            )
            result.append(
                {
                    "id": str(item["connector_id"]),
                    "kind": "WEBHOOK",
                    "name": str(item["name"]),
                    "code": str(item["code"]),
                    "webhook_trigger_id": str(item["id"]),
                    "routing_key": str(item["public_id"]),
                    "enabled": str(item["status"]) == "enabled",
                    "revision": int(item["revision"]),
                    "runtime": {
                        "status": runtime_status,
                        "last_message_at": item.get("recent_event_at"),
                        "last_error": str(item.get("last_error_summary") or ""),
                    },
                    "capabilities": {"private_chat": False, "group_chat": False},
                }
            )
        return sorted(result, key=lambda item: (str(item["kind"]), str(item["name"])))

    def webhook_connector_options(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self.repository.list_webhook_connector_options():
            connector = self.connector_registry.get(str(item["id"]))
            if (
                connector is not None
                and self.connector_registry.operational_status(connector).status == "READY"
            ):
                result.append(item)
        return result

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_webhook(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        trigger_type: str,
        connector_id: str,
    ) -> dict[str, Any]:
        return self.webhook_provider.create_channel(
            actor_id=actor_id,
            code=code,
            name=name,
            trigger_type=trigger_type,
            connector_id=connector_id,
        )

    def get_channel(self, channel_id: str) -> dict[str, Any]:
        return self._dingtalk_public(self.repository.get_connector(channel_id))

    def list_dingtalk_enterprises(self) -> list[dict[str, Any]]:
        return [
            self._enterprise_public(item) for item in self.repository.list_dingtalk_enterprises()
        ]

    def get_dingtalk_enterprise(self, enterprise_id: str) -> dict[str, Any]:
        item = self.repository.get_dingtalk_enterprise(enterprise_id)
        return self._enterprise_public(
            item,
            impacts=self.repository.dingtalk_enterprise_impacts(enterprise_id),
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_dingtalk_enterprise(
        self,
        *,
        name: str,
        actor_id: str,
    ) -> dict[str, Any]:
        normalized = self._enterprise_name(name)
        item = self.repository.create_dingtalk_enterprise(
            name=normalized,
            actor_id=actor_id,
        )
        self._audit_enterprise("created", actor_id, item)
        return self._enterprise_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def rename_dingtalk_enterprise(
        self,
        enterprise_id: str,
        *,
        name: str,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        before = self.repository.get_dingtalk_enterprise(enterprise_id)
        item = self.repository.rename_dingtalk_enterprise(
            enterprise_id,
            name=self._enterprise_name(name),
            expected_revision=expected_revision,
        )
        self._audit_enterprise(
            "renamed",
            actor_id,
            item,
            extra={"previous_name": before["name"], "current_name": item["name"]},
        )
        return self._enterprise_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def disable_dingtalk_enterprise(
        self,
        enterprise_id: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.repository.get_dingtalk_enterprise(enterprise_id)
        require_dingtalk_enterprise_transition(
            str(current["status"]), DingTalkEnterpriseStatus.DISABLED
        )
        item = self.repository.set_dingtalk_enterprise_status(
            enterprise_id,
            status=DingTalkEnterpriseStatus.DISABLED.value,
            expected_revision=expected_revision,
        )
        self._audit_enterprise("disabled", actor_id, item)
        return self._enterprise_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def archive_dingtalk_enterprise(
        self,
        enterprise_id: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.repository.get_dingtalk_enterprise(enterprise_id)
        require_dingtalk_enterprise_transition(
            str(current["status"]), DingTalkEnterpriseStatus.ARCHIVED
        )
        impacts = self.repository.dingtalk_enterprise_impacts(enterprise_id)
        enabled = [item for item in impacts if item["connector_enabled"]]
        if enabled:
            raise NonRetryableExecutionError(
                "DingTalk enterprise still has enabled application connections",
                safe_message="请先停用该企业下的全部钉钉应用连接，再归档企业",
                error_code="dingtalk_enterprise_connectors_enabled",
                field_errors=[
                    {
                        "field": "dingtalk_enterprise_id",
                        "message": "、".join(
                            sorted({str(item["connector_name"]) for item in enabled})
                        )[:300],
                    }
                ],
            )
        item = self.repository.set_dingtalk_enterprise_status(
            enterprise_id,
            status=DingTalkEnterpriseStatus.ARCHIVED.value,
            expected_revision=expected_revision,
        )
        self._audit_enterprise("archived", actor_id, item)
        return self._enterprise_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def restore_dingtalk_enterprise(
        self,
        enterprise_id: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.repository.get_dingtalk_enterprise(enterprise_id)
        require_dingtalk_enterprise_transition(
            str(current["status"]), DingTalkEnterpriseStatus.PENDING_VERIFICATION
        )
        item = self.repository.set_dingtalk_enterprise_status(
            enterprise_id,
            status=DingTalkEnterpriseStatus.PENDING_VERIFICATION.value,
            expected_revision=expected_revision,
            clear_verification=True,
        )
        self._audit_enterprise("restored_for_reverification", actor_id, item)
        return self._enterprise_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_dingtalk(
        self,
        payload: DingTalkApplicationInput,
        *,
        actor_id: str,
        enabled: bool,
    ) -> dict[str, Any]:
        normalized = self._validate(payload)
        enterprise = self.repository.get_dingtalk_enterprise(normalized.dingtalk_enterprise_id)
        if str(enterprise["status"]) in {
            DingTalkEnterpriseStatus.DISABLED.value,
            DingTalkEnterpriseStatus.ARCHIVED.value,
        }:
            raise NonRetryableExecutionError(
                "DingTalk enterprise is unavailable",
                safe_message="钉钉企业已停用或归档，不能新增应用连接",
                error_code="dingtalk_enterprise_unavailable",
            )
        if self.repository.find_by_client_id(normalized.client_id):
            raise NonRetryableExecutionError(
                "DingTalk Client ID already exists",
                safe_message="该钉钉 Client ID 已存在",
                error_code="channel_client_id_conflict",
            )
        secret_code = self._secret_code(normalized.client_id)
        with self.repository.database.unit_of_work():
            self.secret_provider.create_secret(
                code=secret_code,
                value=normalized.client_secret,
                purpose="dingtalk_stream_client_secret",
                actor_id=actor_id,
                metadata={"managed_by": "managed_channel"},
            )
            item = self.repository.create_dingtalk_connector(
                name=normalized.name,
                secret_ref=f"secret://platform/{secret_code}",
                metadata=self._metadata(normalized),
                dingtalk_enterprise_id=normalized.dingtalk_enterprise_id,
                enabled=enabled,
            )
        self._audit("created", actor_id, item)
        return self._dingtalk_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def update_dingtalk(
        self,
        connector_id: str,
        payload: DingTalkApplicationInput,
        *,
        expected_revision: int,
        actor_id: str,
        rotate_secret: bool,
    ) -> dict[str, Any]:
        normalized = self._validate(payload, secret_required=rotate_secret)
        enterprise = self.repository.get_dingtalk_enterprise(normalized.dingtalk_enterprise_id)
        if str(enterprise["status"]) in {
            DingTalkEnterpriseStatus.DISABLED.value,
            DingTalkEnterpriseStatus.ARCHIVED.value,
        }:
            raise NonRetryableExecutionError(
                "DingTalk enterprise is unavailable",
                safe_message="钉钉企业已停用或归档，不能用于应用连接",
                error_code="dingtalk_enterprise_unavailable",
            )
        current = self.repository.get_connector(connector_id)
        enterprise_changed = (
            str(current.get("dingtalk_enterprise_id") or "") != normalized.dingtalk_enterprise_id
        )
        duplicate = self.repository.find_by_client_id(normalized.client_id)
        if duplicate and str(duplicate["id"]) != connector_id:
            raise NonRetryableExecutionError(
                "DingTalk Client ID already exists",
                safe_message="该钉钉 Client ID 已存在",
                error_code="channel_client_id_conflict",
            )
        secret_ref = str(current["secret_ref"])
        with self.repository.database.unit_of_work():
            if rotate_secret:
                if secret_ref.startswith("secret://platform/"):
                    secret_code = secret_ref.removeprefix("secret://platform/")
                    try:
                        self.secret_provider.rotate_secret(
                            code=secret_code,
                            value=normalized.client_secret,
                            actor_id=actor_id,
                        )
                    except NotFound:
                        self.secret_provider.create_secret(
                            code=secret_code,
                            value=normalized.client_secret,
                            purpose="dingtalk_stream_client_secret",
                            actor_id=actor_id,
                            metadata={
                                "managed_by": "managed_channel",
                                "recovered_from": "dangling_reference",
                            },
                        )
                else:
                    secret_code = self._secret_code(normalized.client_id)
                    self.secret_provider.create_secret(
                        code=secret_code,
                        value=normalized.client_secret,
                        purpose="dingtalk_stream_client_secret",
                        actor_id=actor_id,
                        metadata={
                            "managed_by": "managed_channel",
                            "migrated_from": "bootstrap_reference",
                        },
                    )
                    secret_ref = f"secret://platform/{secret_code}"
            item = self.repository.update_dingtalk_connector(
                connector_id=connector_id,
                expected_revision=expected_revision,
                name=normalized.name,
                metadata=self._metadata(normalized),
                dingtalk_enterprise_id=normalized.dingtalk_enterprise_id,
                secret_ref=secret_ref,
                enabled=bool(current["enabled"]),
                force_revision=rotate_secret or enterprise_changed,
            )
        self._audit("updated", actor_id, item)
        return self._dingtalk_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_enabled(
        self,
        connector_id: str,
        *,
        enabled: bool,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.repository.get_connector(connector_id)
        enterprise = self.repository.get_dingtalk_enterprise(
            str(current.get("dingtalk_enterprise_id") or "")
        )
        if enabled and str(enterprise["status"]) in {
            DingTalkEnterpriseStatus.DISABLED.value,
            DingTalkEnterpriseStatus.ARCHIVED.value,
        }:
            raise NonRetryableExecutionError(
                "DingTalk enterprise is unavailable",
                safe_message="钉钉企业已停用或归档，不能启用应用连接",
                error_code="dingtalk_enterprise_unavailable",
            )
        item = self.repository.update_dingtalk_connector(
            connector_id=connector_id,
            expected_revision=expected_revision,
            name=str(current["name"]),
            metadata=dict(current["metadata"]),
            dingtalk_enterprise_id=str(current["dingtalk_enterprise_id"]),
            secret_ref=str(current["secret_ref"]),
            enabled=enabled,
        )
        self._audit("enabled" if enabled else "disabled", actor_id, item)
        return self._dingtalk_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def restart(
        self, connector_id: str, *, expected_revision: int, actor_id: str
    ) -> dict[str, Any]:
        current = self.repository.get_connector(connector_id)
        item = self.repository.update_dingtalk_connector(
            connector_id=connector_id,
            expected_revision=expected_revision,
            name=str(current["name"]),
            metadata=dict(current["metadata"]),
            dingtalk_enterprise_id=str(current["dingtalk_enterprise_id"]),
            secret_ref=str(current["secret_ref"]),
            enabled=bool(current["enabled"]),
            force_revision=True,
        )
        self._audit("restart_requested", actor_id, item)
        return self._dingtalk_public(item)

    @operation_unit_of_work(lambda service: service.repository.database)
    def test_configuration(
        self,
        connector_id: str,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        connector = self.connector_registry.get(connector_id)
        if connector is None:
            raise NonRetryableExecutionError(
                f"Unknown connector: {connector_id}",
                safe_message="连接器尚未配置",
                error_code="connector_not_found",
            )
        status = self.connector_registry.operational_status(connector)
        if status.status == "MISCONFIGURED":
            self.audit_service.record(
                "managed_channel.configuration_tested",
                status="FAILED",
                summary="Managed channel configuration test failed",
                actor_id=actor_id,
                payload={
                    "connector_id": connector_id,
                    "error_code": status.error_code,
                },
            )
            raise NonRetryableExecutionError(
                f"Connector {connector_id} configuration test failed",
                safe_message=status.safe_message,
                error_code=status.error_code,
            )
        result = {
            "status": "READY",
            "summary": "已保存的连接器凭据引用可以安全解析；未执行外部网络请求",
            "tested_at": datetime.now(UTC).isoformat(),
        }
        self.audit_service.record(
            "managed_channel.configuration_tested",
            status="SUCCEEDED",
            summary="Managed channel configuration test succeeded",
            actor_id=actor_id,
            payload={"connector_id": connector_id},
        )
        return result

    @operation_unit_of_work(lambda service: service.repository.database)
    def delete(self, connector_id: str, *, expected_revision: int, actor_id: str) -> None:
        references = self.repository.connector_references(connector_id)
        if references:
            raise NonRetryableExecutionError(
                "Managed channel is referenced by Business Applications",
                safe_message="渠道仍被业务应用引用，不能删除",
                error_code="channel_in_use",
                field_errors=[
                    {
                        "field": "connector_id",
                        "message": "、".join(
                            sorted({str(item["application_name"]) for item in references})
                        )[:300],
                    }
                ],
            )
        current = self.repository.get_connector(connector_id)
        if bool(current["enabled"]):
            raise NonRetryableExecutionError(
                "Enabled managed channel cannot be deleted",
                safe_message="请先停用渠道再删除",
                error_code="channel_enabled",
            )
        self.repository.soft_delete(connector_id, expected_revision=expected_revision)
        self.audit_service.record(
            "managed_channel.deleted",
            status="SUCCEEDED",
            summary="Managed channel deleted",
            actor_id=actor_id,
            payload={"connector_id": connector_id},
        )

    def eligible(self, trigger_type: str) -> list[dict[str, Any]]:
        if trigger_type in {"dingtalk_private", "dingtalk_group"}:
            items = [
                self._dingtalk_public(item)
                for item in self.repository.list_dingtalk_connectors(include_disabled=False)
                if bool(item["allow_ingress"])
            ]
            return [
                item
                for item in items
                if (
                    item["runtime"]["status"] != "MISCONFIGURED"
                    and item["enterprise"]["status"] == "ACTIVE"
                    and (
                        (
                            trigger_type == "dingtalk_private"
                            and item["capabilities"]["private_chat"]
                        )
                        or (trigger_type == "dingtalk_group" and item["capabilities"]["group_chat"])
                    )
                )
            ]
        if trigger_type == "webhook":
            return [
                {
                    "id": str(item["connector_id"]),
                    "kind": "WEBHOOK",
                    "name": str(item["name"]),
                    "code": str(item["code"]),
                    "webhook_trigger_id": str(item["id"]),
                    "routing_key": str(item["public_id"]),
                    "enabled": True,
                    "revision": int(item["revision"]),
                }
                for item in self.webhook_provider.list_channels()
                if str(item["status"]) == "enabled"
                and str(item.get("runtime_status") or "READY") != "MISCONFIGURED"
            ]
        raise NonRetryableExecutionError(
            f"Unsupported trigger provider: {trigger_type}",
            safe_message="该触发器类型尚未开放",
            error_code="channel_provider_unavailable",
        )

    def _dingtalk_public(self, item: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(item.get("metadata") or {})
        heartbeat = str(item.get("last_heartbeat_at") or "")
        observed = str(item.get("runtime_status") or "STOPPED")
        status = observed
        connector = self.connector_registry.get(str(item["id"]))
        operational = (
            self.connector_registry.operational_status(connector) if connector is not None else None
        )
        if operational is not None and operational.status == "MISCONFIGURED":
            status = "MISCONFIGURED"
        elif observed == "MISCONFIGURED":
            status = "RECONNECTING" if bool(item["enabled"]) else "STOPPED"
        elif bool(item["enabled"]) and (not heartbeat or self._stale(heartbeat)):
            status = "STALE"
        elif observed == "REGISTERED" and bool(item.get("registered")):
            status = "READY"
        references = self.repository.connector_references(str(item["id"]))
        return {
            "id": str(item["id"]),
            "kind": "DINGTALK_APP_ROBOT",
            "name": str(item["name"]),
            "client_id": str(metadata.get("client_id") or ""),
            "enterprise": {
                "id": str(item.get("dingtalk_enterprise_id") or ""),
                "name": str(item.get("dingtalk_enterprise_name") or ""),
                "status": str(item.get("dingtalk_enterprise_status") or "UNASSIGNED"),
                "corp_id_verified": bool(
                    item.get("dingtalk_enterprise_corp_id")
                    and item.get("dingtalk_enterprise_verified_at")
                ),
                "verified_at": item.get("dingtalk_enterprise_verified_at"),
            },
            "enabled": bool(item["enabled"]),
            "revision": int(item.get("revision") or 1),
            "secret_configured": bool(item.get("secret_ref")),
            "capabilities": {
                "private_chat": bool(metadata.get("allow_private_chat", True)),
                "group_chat": bool(metadata.get("allow_group_chat", True)),
                "require_group_at": bool(metadata.get("require_group_at", True)),
            },
            "references": [
                {
                    "application_code": str(reference.get("application_code") or ""),
                    "application_name": str(reference.get("application_name") or ""),
                    "application_revision": int(reference.get("application_revision") or 0),
                    "trigger_type": str(reference.get("trigger_type") or ""),
                }
                for reference in references
            ],
            "runtime": {
                "status": status,
                "loaded_revision": item.get("loaded_revision"),
                "last_heartbeat_at": item.get("last_heartbeat_at"),
                "last_message_at": item.get("last_message_at"),
                "last_error": (
                    operational.safe_message
                    if operational is not None and operational.status == "MISCONFIGURED"
                    else str(item.get("last_error_summary") or "")
                ),
            },
            "updated_at": item.get("updated_at"),
        }

    def _stale(self, value: str) -> bool:
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError:
            return True
        return timestamp < datetime.now(UTC) - timedelta(seconds=self.stale_seconds)

    @staticmethod
    def _validate(
        payload: DingTalkApplicationInput, *, secret_required: bool = True
    ) -> DingTalkApplicationInput:
        name = payload.name.strip()
        client_id = payload.client_id.strip()
        enterprise_id = payload.dingtalk_enterprise_id.strip()
        secret = payload.client_secret.strip()
        if len(name) < 2 or len(name) > 120:
            raise _invalid("name", "渠道名称长度必须为 2 到 120")
        if not client_id or len(client_id) > 128:
            raise _invalid("client_id", "必须填写有效 Client ID")
        if not enterprise_id or len(enterprise_id) > 200:
            raise _invalid("dingtalk_enterprise_id", "必须选择钉钉企业")
        if secret_required and not secret:
            raise _invalid("client_secret", "必须填写 Client Secret")
        return DingTalkApplicationInput(
            name=name,
            client_id=client_id,
            client_secret=secret,
            dingtalk_enterprise_id=enterprise_id,
            allow_private_chat=payload.allow_private_chat,
            allow_group_chat=payload.allow_group_chat,
            require_group_at=payload.require_group_at,
        )

    @staticmethod
    def _metadata(payload: DingTalkApplicationInput) -> dict[str, Any]:
        return {
            "client_id": payload.client_id,
            "allow_private_chat": payload.allow_private_chat,
            "allow_group_chat": payload.allow_group_chat,
            "require_group_at": payload.require_group_at,
            "managed_channel_kind": "DINGTALK_APP_ROBOT",
        }

    @staticmethod
    def _enterprise_name(value: str) -> str:
        normalized = value.strip()
        if not (1 <= len(normalized) <= 120):
            raise _invalid("name", "企业名称长度必须为 1 到 120")
        return normalized

    @staticmethod
    def _enterprise_public(
        item: dict[str, Any],
        *,
        impacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "corp_id": str(item.get("corp_id") or ""),
            "status": str(item["status"]),
            "verified_at": item.get("verified_at"),
            "revision": int(item["revision"]),
            "connector_count": int(item.get("connector_count") or 0),
            "enabled_connector_count": int(item.get("enabled_connector_count") or 0),
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
        }
        if impacts is not None:
            result["impacts"] = impacts
        return result

    def _audit_enterprise(
        self,
        event: str,
        actor_id: str,
        item: dict[str, Any],
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.audit_service.record(
            f"dingtalk_enterprise.{event}",
            status="SUCCEEDED",
            summary=f"DingTalk enterprise {event}",
            actor_id=actor_id,
            payload={
                "dingtalk_enterprise_id": item["id"],
                "status": item["status"],
                "revision": item["revision"],
                **(extra or {}),
            },
        )

    @staticmethod
    def _secret_code(client_id: str) -> str:
        stem = _CODE_RE.sub("-", client_id.lower()).strip("-")[:48] or "robot"
        digest = hashlib.sha256(client_id.encode()).hexdigest()[:10]
        return f"dingtalk-{stem}-{digest}"

    def _audit(self, event: str, actor_id: str, item: dict[str, Any]) -> None:
        self.audit_service.record(
            f"managed_channel.{event}",
            status="SUCCEEDED",
            summary=f"Managed channel {event}",
            actor_id=actor_id,
            payload={
                "connector_id": item["id"],
                "connector_type": item["connector_type"],
                "revision": item["revision"],
                "enabled": bool(item["enabled"]),
            },
        )


class RuntimeControlService:
    lease_name = "dingtalk-stream-runtime-singleton"

    def __init__(
        self,
        *,
        repository: ManagedChannelRepository,
        secret_resolver: Callable[[object], str],
        credential_cipher: ChannelCredentialCipher,
        audit_service: AuditService,
        max_event_bytes: int = 256 * 1024,
        lease_ttl_seconds: int = 15,
    ) -> None:
        self.repository = repository
        self.secret_resolver = secret_resolver
        self.credential_cipher = credential_cipher
        self.audit_service = audit_service
        self.max_event_bytes = max_event_bytes
        self.lease_ttl_seconds = lease_ttl_seconds

    @operation_unit_of_work(lambda service: service.repository.database)
    def acquire(self, runtime_id: str) -> dict[str, Any] | None:
        return self.repository.acquire_lease(
            lease_name=self.lease_name,
            runtime_id=_runtime_id(runtime_id),
            ttl_seconds=self.lease_ttl_seconds,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def renew(self, runtime_id: str, lease_token: str) -> dict[str, Any] | None:
        return self.repository.renew_lease(
            lease_name=self.lease_name,
            runtime_id=_runtime_id(runtime_id),
            lease_token=lease_token,
            ttl_seconds=self.lease_ttl_seconds,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def release(self, runtime_id: str, lease_token: str) -> bool:
        return self.repository.release_lease(
            lease_name=self.lease_name,
            runtime_id=_runtime_id(runtime_id),
            lease_token=lease_token,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def desired_snapshot(self, runtime_id: str, lease_token: str) -> dict[str, Any]:
        self.repository.require_lease(runtime_id=_runtime_id(runtime_id), lease_token=lease_token)
        items: list[dict[str, Any]] = []
        for connector in self.repository.list_dingtalk_connectors(include_disabled=False):
            enterprise_status = str(connector.get("dingtalk_enterprise_status") or "")
            if enterprise_status not in {
                DingTalkEnterpriseStatus.PENDING_VERIFICATION.value,
                DingTalkEnterpriseStatus.ACTIVE.value,
            }:
                continue
            try:
                secret = self.secret_resolver(connector["secret_ref"])
            except Exception:
                secret = ""
            metadata = dict(connector["metadata"])
            try:
                client_id = str(metadata.get("client_id") or "") or self.secret_resolver(
                    metadata.get("client_id_ref")
                )
            except Exception:
                client_id = ""
            if not secret:
                self._mark_misconfigured(
                    connector,
                    runtime_id=runtime_id,
                    error_code="channel_secret_unavailable",
                    error_summary="钉钉渠道凭据缺失、已停用或无法解析，请重新绑定后测试",
                )
                continue
            if not client_id:
                self._mark_misconfigured(
                    connector,
                    runtime_id=runtime_id,
                    error_code="channel_client_id_unavailable",
                    error_summary="钉钉渠道 Client ID 缺失或无法解析，请修正后测试",
                )
                continue
            items.append(
                {
                    "connector_id": str(connector["id"]),
                    "revision": int(connector["revision"]),
                    "name": str(connector["name"]),
                    "client_id": client_id,
                    "client_secret": secret,
                    "dingtalk_enterprise_id": str(connector.get("dingtalk_enterprise_id") or ""),
                    "enterprise_status": enterprise_status,
                    "allow_private_chat": bool(metadata.get("allow_private_chat", True)),
                    "allow_group_chat": bool(metadata.get("allow_group_chat", True)),
                    "require_group_at": bool(metadata.get("require_group_at", True)),
                }
            )
        revision = max((int(item["revision"]) for item in items), default=0)
        return {"revision": revision, "connectors": items}

    @operation_unit_of_work(lambda service: service.repository.database)
    def report_states(
        self,
        runtime_id: str,
        lease_token: str,
        states: list[RuntimeConnectorState],
    ) -> None:
        runtime_id = _runtime_id(runtime_id)
        self.repository.require_lease(runtime_id=runtime_id, lease_token=lease_token)
        for state in states:
            if state.status not in _ALLOWED_RUNTIME_STATES:
                raise _invalid("status", "Runtime 状态无效")
            connector = self.repository.get_connector(state.connector_id)
            if int(connector["revision"]) < state.revision:
                raise _invalid("revision", "Runtime 配置修订超前")
            try:
                secret = self.secret_resolver(connector["secret_ref"])
            except Exception:
                secret = ""
            if not secret:
                self._mark_misconfigured(
                    connector,
                    runtime_id=runtime_id,
                    error_code="channel_secret_unavailable",
                    error_summary="钉钉渠道凭据缺失、已停用或无法解析，请重新绑定后测试",
                )
                continue
            self.repository.upsert_runtime_state(
                connector_id=state.connector_id,
                runtime_id=runtime_id,
                runtime_status=state.status,
                loaded_revision=state.revision,
                connected=state.connected,
                registered=state.registered,
                error_code=state.error_code,
                error_summary=_safe_error(state.error_summary),
            )

    @operation_unit_of_work(lambda service: service.repository.database)
    def receive(
        self,
        runtime_id: str,
        lease_token: str,
        submission: ChannelIngressSubmission,
    ) -> tuple[dict[str, Any], bool]:
        runtime_id = _runtime_id(runtime_id)
        self.repository.require_lease(runtime_id=runtime_id, lease_token=lease_token)
        connector = self.repository.get_connector(submission.connector_id)
        if not bool(connector["enabled"]) or not bool(connector["allow_ingress"]):
            raise NonRetryableExecutionError(
                "Connector is not enabled for ingress",
                safe_message="渠道未启用或不允许接入",
                error_code="channel_not_eligible",
            )
        enterprise_id = str(connector.get("dingtalk_enterprise_id") or "")
        if not enterprise_id:
            raise NonRetryableExecutionError(
                "DingTalk connector has no governed enterprise",
                safe_message="钉钉应用连接尚未选择受治理企业",
                error_code="dingtalk_enterprise_required",
            )
        enterprise = self.repository.get_dingtalk_enterprise(enterprise_id)
        verification_key = f"{submission.connector_id}:{submission.external_event_id}"
        if str(enterprise.get("verification_event_id") or "") == verification_key:
            return (
                {
                    "id": verification_key,
                    "status": "ENTERPRISE_VERIFIED",
                    "correlation_id": submission.correlation_id,
                },
                False,
            )
        if str(enterprise["status"]) in {
            DingTalkEnterpriseStatus.DISABLED.value,
            DingTalkEnterpriseStatus.ARCHIVED.value,
        }:
            raise NonRetryableExecutionError(
                "DingTalk enterprise is unavailable",
                safe_message="钉钉企业已停用或归档",
                error_code="dingtalk_enterprise_unavailable",
            )
        sender_corp_id = str(
            submission.normalized_event.get("senderCorpId")
            or submission.normalized_event.get("sender_corp_id")
            or ""
        )
        chatbot_corp_id = str(
            submission.normalized_event.get("chatbotCorpId")
            or submission.normalized_event.get("chatbot_corp_id")
            or ""
        )
        try:
            sender_corp_id = normalize_dingtalk_corp_id(sender_corp_id)
            chatbot_corp_id = normalize_dingtalk_corp_id(chatbot_corp_id)
            if sender_corp_id != chatbot_corp_id:
                raise NonRetryableExecutionError(
                    "DingTalk sender and chatbot Corp IDs differ",
                    safe_message="钉钉测试消息的企业信息不一致",
                    error_code="dingtalk_corp_id_mismatch",
                )
            require_immutable_dingtalk_corp_id(enterprise.get("corp_id"), sender_corp_id)
        except NonRetryableExecutionError as exc:
            self.audit_service.record(
                "dingtalk_enterprise.message_rejected",
                status="DENIED",
                summary="DingTalk enterprise Corp ID validation failed",
                actor_id=None,
                payload={
                    "dingtalk_enterprise_id": enterprise_id,
                    "connector_id": submission.connector_id,
                    "external_event_id": submission.external_event_id,
                    "error_code": exc.error_code,
                },
            )
            raise
        if str(enterprise["status"]) == DingTalkEnterpriseStatus.PENDING_VERIFICATION.value:
            duplicate = self.repository.find_dingtalk_enterprise_by_corp_id(sender_corp_id)
            if duplicate and str(duplicate["id"]) != enterprise_id:
                raise NonRetryableExecutionError(
                    "DingTalk Corp ID belongs to another enterprise",
                    safe_message="该钉钉企业已在平台中完成接入",
                    error_code="dingtalk_corp_id_conflict",
                )
            verified = self.repository.verify_dingtalk_enterprise(
                enterprise_id,
                corp_id=sender_corp_id,
                source_event_id=verification_key,
                expected_revision=int(enterprise["revision"]),
            )
            self.audit_service.record(
                "dingtalk_enterprise.verified",
                status="SUCCEEDED",
                summary="DingTalk enterprise verified from trusted Stream message",
                actor_id=None,
                payload={
                    "dingtalk_enterprise_id": enterprise_id,
                    "connector_id": submission.connector_id,
                    "external_event_id": submission.external_event_id,
                    "revision": verified["revision"],
                },
            )
            return (
                {
                    "id": verification_key,
                    "status": "ENTERPRISE_VERIFIED",
                    "correlation_id": submission.correlation_id,
                },
                True,
            )
        try:
            secret = self.secret_resolver(connector["secret_ref"])
        except Exception:
            secret = ""
        if not secret:
            self._mark_misconfigured(
                connector,
                runtime_id=runtime_id,
                error_code="channel_secret_unavailable",
                error_summary="钉钉渠道凭据缺失、已停用或无法解析，请重新绑定后测试",
            )
            raise NonRetryableExecutionError(
                "DingTalk connector secret is unavailable",
                safe_message="钉钉渠道配置不可用",
                error_code="channel_misconfigured",
            )
        if submission.request_bytes > self.max_event_bytes:
            raise NonRetryableExecutionError(
                "Channel event exceeds size limit",
                safe_message="渠道消息超过大小限制",
                error_code="channel_event_too_large",
            )
        normalized = json.loads(json.dumps(submission.normalized_event))
        session_webhook = str(
            normalized.pop("sessionWebhook", "") or normalized.pop("session_webhook", "")
        )
        ciphertext = self.credential_cipher.encrypt(session_webhook) if session_webhook else ""
        event, created = self.repository.receive_event(
            source_type="dingding_stream",
            connector_id=submission.connector_id,
            external_event_id=submission.external_event_id,
            correlation_id=submission.correlation_id,
            payload_hash=submission.payload_hash,
            request_bytes=submission.request_bytes,
            safe_summary=submission.safe_summary,
            normalized_event=normalized,
            reply_credential_ciphertext=ciphertext,
        )
        self.repository.upsert_runtime_state(
            connector_id=submission.connector_id,
            runtime_id=runtime_id,
            runtime_status="REGISTERED",
            loaded_revision=int(connector["revision"]),
            connected=True,
            registered=True,
            error_code="",
            error_summary="",
            message_received=True,
        )
        return event, created

    def _mark_misconfigured(
        self,
        connector: dict[str, Any],
        *,
        runtime_id: str,
        error_code: str,
        error_summary: str,
    ) -> None:
        self.repository.upsert_runtime_state(
            connector_id=str(connector["id"]),
            runtime_id=runtime_id,
            runtime_status="ERROR",
            loaded_revision=int(connector["revision"]),
            connected=False,
            registered=False,
            error_code=error_code,
            error_summary=error_summary,
        )


class ChannelOutboxPublisher:
    def __init__(
        self,
        *,
        repository: ManagedChannelRepository,
        publisher: MessagePublisher,
        max_attempts: int = 8,
        retry_base_seconds: int = 5,
        worker_id: str = "channel-outbox",
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.worker_id = worker_id

    def publish_pending(self, *, limit: int = 100) -> dict[str, int]:
        self.repository.recover_stale_claims()
        published = failed = 0
        for _ in range(min(max(limit, 1), 1000)):
            item = self.repository.claim_outbox(worker_id=self.worker_id)
            if item is None:
                break
            try:
                self.publisher.publish_channel_event(
                    str(item["channel_event_id"]), str(item["correlation_id"])
                )
            except Exception as exc:
                failed += 1
                self.repository.mark_outbox_failed(
                    str(item["id"]),
                    error_summary=_safe_error(
                        str(getattr(exc, "safe_message", type(exc).__name__))
                    ),
                    max_attempts=self.max_attempts,
                    base_delay=self.retry_base_seconds,
                )
                continue
            self.repository.mark_outbox_published(str(item["id"]))
            published += 1
        return {"published": published, "failed": failed}


class ChannelDispatchService:
    def __init__(
        self,
        *,
        repository: ManagedChannelRepository,
        stream_service: DingTalkStreamMessageService,
        credential_cipher: ChannelCredentialCipher,
        identity_discovery_service: DingTalkIdentityDiscoveryService | None = None,
    ) -> None:
        self.repository = repository
        self.stream_service = stream_service
        self.credential_cipher = credential_cipher
        self.identity_discovery_service = identity_discovery_service

    def handle(self, message: ChannelEventMessage) -> None:
        event = self.repository.get_event(message.channel_event_id)
        if event.get("job_id") or str(event["status"]) not in {
            "ACCEPTED",
            "DISPATCH_PENDING",
        }:
            return
        payload = dict(event["normalized_event"])
        payload["_source_ingress_event_id"] = str(event["id"])
        payload["_received_at"] = str(event["received_at"])
        ciphertext = str(event.get("reply_credential_ciphertext") or "")
        if ciphertext:
            payload["sessionWebhook"] = self.credential_cipher.decrypt(ciphertext)
        quoted_message = self._resolve_quoted_message(event=event, payload=payload)
        try:
            result = self.stream_service.handle_callback(
                payload=payload,
                correlation_id=str(event["correlation_id"]),
                connector_id=str(event["connector_id"]),
                defer_rejection_notification=True,
                quoted_message=quoted_message,
            )
        except AppError as exc:
            self.repository.mark_event_rejected(
                str(event["id"]),
                error_code=exc.error_code or "channel_dispatch_failed",
                error_summary=exc.safe_message,
            )
            return
        if result.job_id:
            self.repository.attach_job(str(event["id"]), result.job_id)
        elif result.status == "attachments_staged":
            self.repository.mark_event_attachments_staged(str(event["id"]))
        elif result.status == "system_notice":
            self.repository.mark_event_attachments_staged(str(event["id"]))
        elif result.status not in {"ignored"}:
            with self.repository.database.unit_of_work():
                if (
                    result.discovery_observation is not None
                    and self.identity_discovery_service is not None
                ):
                    self.identity_discovery_service.observe_rejection(
                        result.discovery_observation,
                        source_ingress_event_id=str(event["id"]),
                        received_at=str(event["received_at"]),
                        rejection_code=result.error_code,
                    )
                self.repository.mark_event_rejected(
                    str(event["id"]),
                    error_code=result.error_code or result.status,
                    error_summary=result.reason or result.ack_message,
                )
            self.stream_service.notify_deferred_rejection(result)

    def _resolve_quoted_message(
        self,
        *,
        event: dict[str, Any],
        payload: dict[str, Any],
    ) -> DingTalkQuotedMessage | None:
        original_message_id = str(
            payload.get("originalMsgId") or payload.get("original_message_id") or ""
        ).strip()
        if not original_message_id:
            return None
        original_event = self.repository.find_event_by_external_id(
            source_type="dingding_stream",
            connector_id=str(event["connector_id"]),
            external_event_id=original_message_id,
        )
        if original_event is None or str(original_event["id"]) == str(event["id"]):
            return None
        if str(original_event.get("received_at") or "") > str(event.get("received_at") or ""):
            return None
        return self.stream_service.resolve_quoted_message(
            current_payload=payload,
            original_payload=dict(original_event["normalized_event"]),
        )


class UnavailableChannelCredentialCipher:
    def encrypt(self, value: str) -> str:
        del value
        self._raise()

    def decrypt(self, value: str) -> str:
        del value
        self._raise()

    @staticmethod
    def _raise() -> Never:
        raise NonRetryableExecutionError(
            "Master Key file is required for channel credentials",
            safe_message="尚未配置渠道凭据加密",
            error_code="channel_credential_encryption_unavailable",
        )


def _runtime_id(value: str) -> str:
    result = value.strip()
    if not result or len(result) > 128:
        raise _invalid("runtime_id", "Runtime ID 无效")
    return result


def _safe_error(value: str) -> str:
    text = str(value or "")
    for token in ("token", "secret", "webhook", "authorization"):
        if token in text.lower():
            return "Runtime operation failed"
    return text[:500]


def _invalid(field: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Managed channel validation failed",
        safe_message="渠道配置无效",
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )
