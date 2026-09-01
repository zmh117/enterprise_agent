from __future__ import annotations

from collections.abc import Callable

from app.bootstrap import Container
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import (
    DingTalkAccessTokenClient,
)
from app.shared.exceptions import AppError, NonRetryableExecutionError
from services.dingtalk_mcp_server.provider import DingTalkContactsClient


ContactsClientFactory = Callable[[str], DingTalkContactsClient]


class DingTalkUnionIdCompletionService:
    """Completes a trusted Staff ID identity with its Provider union ID.

    Provider I/O is deliberately performed before the short persistence unit of
    work. The model, JWT and Tool arguments never supply either identifier.
    """

    def __init__(
        self,
        runtime: Container,
        *,
        contacts_client_factory: ContactsClientFactory | None = None,
    ) -> None:
        self.runtime = runtime
        self.contacts_client_factory = contacts_client_factory

    def complete(
        self,
        *,
        identity_id: str,
        connector_id: str,
        external_subject_id: str,
    ) -> str:
        try:
            response = self._contacts_client(connector_id).get_user(
                user_id=external_subject_id,
                language="zh_CN",
            )
            user = response.get("user")
            if not isinstance(user, dict):
                raise self._incomplete("DingTalk contact detail did not contain a user")
            if str(user.get("user_id") or "") != external_subject_id:
                raise self._incomplete("DingTalk contact detail user ID did not match")
            union_id = str(user.get("union_id") or "").strip()
            if not union_id:
                raise self._incomplete("DingTalk contact detail did not contain union ID")
            with self.runtime.database.unit_of_work():
                completed = self.runtime.identity_repository.complete_dingtalk_union_id(
                    identity_id=identity_id,
                    external_subject_id=external_subject_id,
                    union_id=union_id,
                )
            persisted = str(completed.get("union_id") or "")
            if persisted != union_id:
                raise self._incomplete("Persisted DingTalk union ID did not match Provider fact")
            self.runtime.audit_service.record(
                "identity.dingtalk.union_id_completed",
                status="SUCCEEDED",
                summary="DingTalk union ID completed from trusted contact detail",
                actor_id=str(completed.get("user_id") or "") or None,
                payload={
                    "external_identity_id": identity_id,
                    "connector_id": connector_id,
                },
            )
            return persisted
        except AppError as exc:
            self.runtime.audit_service.record(
                "identity.dingtalk.union_id_completion_failed",
                status="DENIED",
                summary="DingTalk union ID completion failed safely",
                actor_id=None,
                payload={
                    "external_identity_id": identity_id,
                    "connector_id": connector_id,
                    "error_code": exc.error_code or "dingtalk_identity_incomplete",
                },
            )
            raise

    def _contacts_client(self, connector_id: str) -> DingTalkContactsClient:
        if self.contacts_client_factory is not None:
            return self.contacts_client_factory(connector_id)
        connector = self.runtime.connector_registry.require_dingtalk_stream_ingress(connector_id)
        client_id = self.runtime.connector_registry.metadata_value(connector, "client_id")
        client_secret = self.runtime.connector_registry.resolve_secret(connector)
        if not client_id or not client_secret:
            raise NonRetryableExecutionError(
                "DingTalk Connector credentials are unavailable",
                safe_message="钉钉应用凭据不可用",
                error_code="dingtalk_connector_credentials_unavailable",
            )
        return DingTalkContactsClient(
            DingTalkAccessTokenClient(
                client_id=client_id,
                client_secret=client_secret,
                timeout_seconds=5,
            )
        )

    @staticmethod
    def _incomplete(message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message="当前钉钉身份缺少 Union ID，请联系管理员核查应用通讯录权限",
            error_code="dingtalk_identity_incomplete",
        )
