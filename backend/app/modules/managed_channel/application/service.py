from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Never, Protocol

from app.modules.audit.application.audit_service import AuditService
from app.modules.dingding.application.dingtalk_stream_service import (
    DingTalkStreamMessageService,
)
from app.modules.message_bus.application.message_publisher import (
    ChannelEventMessage,
    MessagePublisher,
)
from app.modules.platform_config.application.secrets import SecretProviderPort
from app.shared.exceptions import AppError, NonRetryableExecutionError

from ..domain import ChannelIngressSubmission, DingTalkApplicationInput, RuntimeConnectorState
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
        audit_service: AuditService,
        stale_seconds: int = 30,
    ) -> None:
        self.repository = repository
        self.webhook_provider = webhook_provider
        self.secret_provider = secret_provider
        self.audit_service = audit_service
        self.stale_seconds = max(stale_seconds, 10)

    def list_channels(self) -> list[dict[str, Any]]:
        result = [self._dingtalk_public(item) for item in self.repository.list_dingtalk_connectors()]
        for item in self.webhook_provider.list_channels():
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
                        "status": "READY" if str(item["status"]) == "enabled" else "STOPPED",
                        "last_message_at": item.get("recent_event_at"),
                        "last_error": "",
                    },
                    "capabilities": {"private_chat": False, "group_chat": False},
                }
            )
        return sorted(result, key=lambda item: (str(item["kind"]), str(item["name"])))

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

    def create_dingtalk(
        self,
        payload: DingTalkApplicationInput,
        *,
        actor_id: str,
        enabled: bool,
    ) -> dict[str, Any]:
        normalized = self._validate(payload)
        if self.repository.find_by_client_id(normalized.client_id):
            raise NonRetryableExecutionError(
                "DingTalk Client ID already exists",
                safe_message="该钉钉 Client ID 已存在",
                error_code="channel_client_id_conflict",
            )
        secret_code = self._secret_code(normalized.client_id)
        with self.repository.database.transaction():
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
                enabled=enabled,
            )
        self._audit("created", actor_id, item)
        return self._dingtalk_public(item)

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
        current = self.repository.get_connector(connector_id)
        duplicate = self.repository.find_by_client_id(normalized.client_id)
        if duplicate and str(duplicate["id"]) != connector_id:
            raise NonRetryableExecutionError(
                "DingTalk Client ID already exists",
                safe_message="该钉钉 Client ID 已存在",
                error_code="channel_client_id_conflict",
            )
        with self.repository.database.transaction():
            if rotate_secret:
                secret_code = str(current["secret_ref"]).removeprefix("secret://platform/")
                self.secret_provider.rotate_secret(
                    code=secret_code,
                    value=normalized.client_secret,
                    actor_id=actor_id,
                )
            item = self.repository.update_dingtalk_connector(
                connector_id=connector_id,
                expected_revision=expected_revision,
                name=normalized.name,
                metadata=self._metadata(normalized),
                secret_ref=str(current["secret_ref"]),
                enabled=bool(current["enabled"]),
                force_revision=rotate_secret,
            )
        self._audit("updated", actor_id, item)
        return self._dingtalk_public(item)

    def set_enabled(
        self,
        connector_id: str,
        *,
        enabled: bool,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.repository.get_connector(connector_id)
        item = self.repository.update_dingtalk_connector(
            connector_id=connector_id,
            expected_revision=expected_revision,
            name=str(current["name"]),
            metadata=dict(current["metadata"]),
            secret_ref=str(current["secret_ref"]),
            enabled=enabled,
        )
        self._audit("enabled" if enabled else "disabled", actor_id, item)
        return self._dingtalk_public(item)

    def restart(
        self, connector_id: str, *, expected_revision: int, actor_id: str
    ) -> dict[str, Any]:
        current = self.repository.get_connector(connector_id)
        item = self.repository.update_dingtalk_connector(
            connector_id=connector_id,
            expected_revision=expected_revision,
            name=str(current["name"]),
            metadata=dict(current["metadata"]),
            secret_ref=str(current["secret_ref"]),
            enabled=bool(current["enabled"]),
            force_revision=True,
        )
        self._audit("restart_requested", actor_id, item)
        return self._dingtalk_public(item)

    def delete(
        self, connector_id: str, *, expected_revision: int, actor_id: str
    ) -> None:
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
                    trigger_type == "dingtalk_private"
                    and item["capabilities"]["private_chat"]
                )
                or (
                    trigger_type == "dingtalk_group"
                    and item["capabilities"]["group_chat"]
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
        if bool(item["enabled"]) and (not heartbeat or self._stale(heartbeat)):
            status = "STALE"
        elif observed == "REGISTERED" and bool(item.get("registered")):
            status = "READY"
        return {
            "id": str(item["id"]),
            "kind": "DINGTALK_APP_ROBOT",
            "name": str(item["name"]),
            "client_id": str(metadata.get("client_id") or ""),
            "tenant_code": str(metadata.get("tenant_code") or ""),
            "enabled": bool(item["enabled"]),
            "revision": int(item.get("revision") or 1),
            "secret_configured": bool(item.get("secret_ref")),
            "capabilities": {
                "private_chat": bool(metadata.get("allow_private_chat", True)),
                "group_chat": bool(metadata.get("allow_group_chat", True)),
                "require_group_at": bool(metadata.get("require_group_at", True)),
            },
            "runtime": {
                "status": status,
                "loaded_revision": item.get("loaded_revision"),
                "last_heartbeat_at": item.get("last_heartbeat_at"),
                "last_message_at": item.get("last_message_at"),
                "last_error": str(item.get("last_error_summary") or ""),
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
        tenant_code = payload.tenant_code.strip()
        secret = payload.client_secret.strip()
        if len(name) < 2 or len(name) > 120:
            raise _invalid("name", "渠道名称长度必须为 2 到 120")
        if not client_id or len(client_id) > 128:
            raise _invalid("client_id", "必须填写有效 Client ID")
        if not tenant_code or len(tenant_code) > 128:
            raise _invalid("tenant_code", "必须填写企业标识")
        if secret_required and not secret:
            raise _invalid("client_secret", "必须填写 Client Secret")
        return DingTalkApplicationInput(
            name=name,
            client_id=client_id,
            client_secret=secret,
            tenant_code=tenant_code,
            allow_private_chat=payload.allow_private_chat,
            allow_group_chat=payload.allow_group_chat,
            require_group_at=payload.require_group_at,
        )

    @staticmethod
    def _metadata(payload: DingTalkApplicationInput) -> dict[str, Any]:
        return {
            "client_id": payload.client_id,
            "tenant_code": payload.tenant_code,
            "allow_private_chat": payload.allow_private_chat,
            "allow_group_chat": payload.allow_group_chat,
            "require_group_at": payload.require_group_at,
            "managed_channel_kind": "DINGTALK_APP_ROBOT",
        }

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
        max_event_bytes: int = 256 * 1024,
        lease_ttl_seconds: int = 15,
    ) -> None:
        self.repository = repository
        self.secret_resolver = secret_resolver
        self.credential_cipher = credential_cipher
        self.max_event_bytes = max_event_bytes
        self.lease_ttl_seconds = lease_ttl_seconds

    def acquire(self, runtime_id: str) -> dict[str, Any] | None:
        return self.repository.acquire_lease(
            lease_name=self.lease_name,
            runtime_id=_runtime_id(runtime_id),
            ttl_seconds=self.lease_ttl_seconds,
        )

    def renew(self, runtime_id: str, lease_token: str) -> dict[str, Any] | None:
        return self.repository.renew_lease(
            lease_name=self.lease_name,
            runtime_id=_runtime_id(runtime_id),
            lease_token=lease_token,
            ttl_seconds=self.lease_ttl_seconds,
        )

    def release(self, runtime_id: str, lease_token: str) -> bool:
        return self.repository.release_lease(
            lease_name=self.lease_name,
            runtime_id=_runtime_id(runtime_id),
            lease_token=lease_token,
        )

    def desired_snapshot(self, runtime_id: str, lease_token: str) -> dict[str, Any]:
        self.repository.require_lease(runtime_id=_runtime_id(runtime_id), lease_token=lease_token)
        items: list[dict[str, Any]] = []
        for connector in self.repository.list_dingtalk_connectors(include_disabled=False):
            secret = self.secret_resolver(connector["secret_ref"])
            metadata = dict(connector["metadata"])
            client_id = str(metadata.get("client_id") or "") or self.secret_resolver(
                metadata.get("client_id_ref")
            )
            if not secret:
                raise NonRetryableExecutionError(
                    "DingTalk connector secret is unavailable",
                    safe_message="钉钉渠道凭据不可用",
                    error_code="channel_secret_unavailable",
                )
            if not client_id:
                raise NonRetryableExecutionError(
                    "DingTalk connector Client ID is unavailable",
                    safe_message="钉钉渠道 Client ID 不可用",
                    error_code="channel_client_id_unavailable",
                )
            items.append(
                {
                    "connector_id": str(connector["id"]),
                    "revision": int(connector["revision"]),
                    "name": str(connector["name"]),
                    "client_id": client_id,
                    "client_secret": secret,
                    "tenant_code": str(metadata.get("tenant_code") or ""),
                    "allow_private_chat": bool(metadata.get("allow_private_chat", True)),
                    "allow_group_chat": bool(metadata.get("allow_group_chat", True)),
                    "require_group_at": bool(metadata.get("require_group_at", True)),
                }
            )
        revision = max((int(item["revision"]) for item in items), default=0)
        return {"revision": revision, "connectors": items}

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
        if submission.request_bytes > self.max_event_bytes:
            raise NonRetryableExecutionError(
                "Channel event exceeds size limit",
                safe_message="渠道消息超过大小限制",
                error_code="channel_event_too_large",
            )
        normalized = json.loads(json.dumps(submission.normalized_event))
        session_webhook = str(
            normalized.pop("sessionWebhook", "")
            or normalized.pop("session_webhook", "")
        )
        ciphertext = (
            self.credential_cipher.encrypt(session_webhook) if session_webhook else ""
        )
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
                    error_summary=_safe_error(str(getattr(exc, "safe_message", type(exc).__name__))),
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
    ) -> None:
        self.repository = repository
        self.stream_service = stream_service
        self.credential_cipher = credential_cipher

    def handle(self, message: ChannelEventMessage) -> None:
        event = self.repository.get_event(message.channel_event_id)
        if event.get("job_id") or str(event["status"]) not in {
            "ACCEPTED",
            "DISPATCH_PENDING",
        }:
            return
        payload = dict(event["normalized_event"])
        ciphertext = str(event.get("reply_credential_ciphertext") or "")
        if ciphertext:
            payload["sessionWebhook"] = self.credential_cipher.decrypt(ciphertext)
        try:
            result = self.stream_service.handle_callback(
                payload=payload,
                correlation_id=str(event["correlation_id"]),
                connector_id=str(event["connector_id"]),
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
        elif result.status not in {"ignored"}:
            self.repository.mark_event_rejected(
                str(event["id"]),
                error_code=result.status,
                error_summary=result.reason or result.ack_message,
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
            "APP_CONFIG_MASTER_KEY is required for channel credentials",
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
