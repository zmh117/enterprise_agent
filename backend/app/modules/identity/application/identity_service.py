from __future__ import annotations

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.domain import AuthenticatedPrincipal, ExternalIdentityDescriptor
from app.modules.identity.infrastructure import (
    ExternalIdentityCredentialRepository,
    IdentityRepository,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


class IdentityService:
    def __init__(
        self,
        repository: IdentityRepository,
        audit_service: AuditService,
        connector_registry: ConnectorRegistry | None = None,
        credential_repository: ExternalIdentityCredentialRepository | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.connector_registry = connector_registry
        self.credential_repository = credential_repository

    @operation_unit_of_work(lambda service: service.repository.database)
    def resolve_external(self, descriptor: ExternalIdentityDescriptor) -> AuthenticatedPrincipal:
        if descriptor.provider == "dingtalk":
            if not descriptor.dingtalk_enterprise_id:
                raise PermissionDenied(
                    "DingTalk enterprise identity is required",
                    safe_message="钉钉应用尚未关联受治理企业",
                    error_code="dingtalk_enterprise_required",
                )
            identity = self.repository.find_dingtalk_identity(
                dingtalk_enterprise_id=descriptor.dingtalk_enterprise_id,
                external_subject_id=descriptor.external_subject_id,
                include_disabled=True,
            )
        else:
            identity = self.repository.find_external_identity(
                provider=descriptor.provider,
                tenant_code=descriptor.tenant_code,
                external_subject_id=descriptor.external_subject_id,
                include_disabled=True,
            )
        if not identity:
            self.audit_service.record(
                "identity.external.denied",
                status="DENIED",
                summary="External identity is not bound or enabled",
                actor_id=None,
                payload={
                    "provider": descriptor.provider,
                    "tenant_code": descriptor.tenant_code,
                    "connector_id": descriptor.connector_id,
                },
            )
            raise PermissionDenied(
                "External identity is not bound",
                safe_message="你的钉钉账号尚未绑定平台用户，请联系管理员完成绑定",
                error_code="identity_not_bound",
            )
        if str(identity["status"]) == "unbound":
            self.audit_service.record(
                "identity.external.denied",
                status="DENIED",
                summary="External identity is unbound",
                actor_id=str(identity["user_id"]),
                payload={
                    "external_identity_id": identity["id"],
                    "provider": descriptor.provider,
                    "tenant_code": descriptor.tenant_code,
                    "connector_id": descriptor.connector_id,
                    "reason_code": "identity_not_bound",
                },
            )
            raise PermissionDenied(
                "External identity is unbound",
                safe_message="你的钉钉账号尚未绑定平台用户，请联系管理员完成绑定",
                error_code="identity_not_bound",
            )
        if str(identity["status"]) != "enabled":
            self.audit_service.record(
                "identity.external.denied",
                status="DENIED",
                summary="External identity is disabled or unbound",
                actor_id=str(identity["user_id"]),
                payload={
                    "external_identity_id": identity["id"],
                    "provider": descriptor.provider,
                    "tenant_code": descriptor.tenant_code,
                    "connector_id": descriptor.connector_id,
                    "reason_code": "identity_inactive",
                },
            )
            raise PermissionDenied(
                "External identity is disabled or unbound",
                safe_message="你的钉钉身份已停用，请联系管理员",
                error_code="identity_inactive",
            )
        if str(identity.get("user_status") or "") != "enabled":
            self.audit_service.record(
                "identity.external.denied",
                status="DENIED",
                summary="External identity owner is disabled",
                actor_id=str(identity["user_id"]),
                payload={
                    "external_identity_id": identity["id"],
                    "provider": descriptor.provider,
                    "tenant_code": descriptor.tenant_code,
                    "connector_id": descriptor.connector_id,
                    "reason_code": "identity_user_inactive",
                },
            )
            raise PermissionDenied(
                "External identity owner is disabled",
                safe_message="你的平台账号已停用，请联系管理员",
                error_code="identity_user_inactive",
            )
        if descriptor.provider == "dingtalk" and descriptor.source_ingress_event_id:
            self.repository.record_dingtalk_message_facts(
                identity_id=str(identity["id"]),
                connector_id=descriptor.connector_id,
                source_ingress_event_id=descriptor.source_ingress_event_id,
                nickname=descriptor.display_name,
                occurred_at=descriptor.occurred_at,
                received_at=descriptor.received_at,
            )
        else:
            self.repository.touch_external_identity(str(identity["id"]))
        user = self.repository.get_user(str(identity["user_id"]))
        if str(user.get("account_type") or "human") != "human":
            self.audit_service.record(
                "identity.external.denied",
                status="DENIED",
                summary="External authentication is unavailable for service accounts",
                actor_id=str(user["id"]),
                payload={"provider": descriptor.provider},
            )
            raise PermissionDenied(
                "Service account external authentication denied",
                safe_message="此外部身份未获授权",
                error_code="service_account_identity_forbidden",
            )
        return AuthenticatedPrincipal(
            user_id=str(user["id"]),
            username=str(user["username"]),
            display_name=str(user["display_name"]),
            role_codes=self.repository.role_codes_for_user(str(user["id"])),
            external_identity_id=str(identity["id"]),
            auth_source=descriptor.provider,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def bind_dingtalk_candidate(
        self,
        *,
        actor_id: str,
        user_id: str,
        dingtalk_enterprise_id: str,
        external_subject_id: str,
        source_connector_id: str,
        source_ingress_event_id: str,
        observed_at: str,
        expected_user_revision: int,
        display_name: str = "",
        replace_current: bool = False,
        restore_historical: bool = False,
    ) -> dict[str, object]:
        source = self.repository.database.execute_one(
            """
            select c.id, c.enabled, c.deleted, c.dingtalk_enterprise_id,
                   e.status as enterprise_status
              from integration_connector c
              join dingtalk_enterprise e on e.id = c.dingtalk_enterprise_id
              join channel_ingress_event ie on ie.connector_id = c.id
             where c.id = ? and ie.id = ?
               and c.connector_type = 'dingtalk_enterprise_stream'
            """,
            (source_connector_id, source_ingress_event_id),
        )
        if (
            source is None
            or not bool(source["enabled"])
            or bool(source["deleted"])
            or str(source["enterprise_status"]) != "ACTIVE"
            or str(source["dingtalk_enterprise_id"]) != dingtalk_enterprise_id
        ):
            raise PermissionDenied(
                "DingTalk candidate source is no longer trusted",
                safe_message="候选来源应用或钉钉企业当前不可用，请刷新后重试",
                error_code="identity_discovery_connector_unavailable",
            )
        user = self.repository.get_user(user_id)
        if str(user.get("account_type") or "human") != "human":
            self.audit_service.record(
                "identity.external.binding_denied",
                status="DENIED",
                summary="Service account external identity binding denied",
                actor_id=actor_id,
                payload={"user_id": user_id, "provider": "dingtalk"},
            )
            raise PermissionDenied(
                "Service accounts cannot bind external identities",
                safe_message="服务账号不能绑定外部身份",
                error_code="service_account_identity_forbidden",
            )
        if str(user["status"]) != "enabled" or int(user["revision"]) != expected_user_revision:
            raise NonRetryableExecutionError(
                "User revision conflict",
                safe_message="用户信息已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        before = self.repository.list_external_identities(user_id)
        try:
            identity = self.repository.bind_dingtalk_identity(
                user_id=user_id,
                dingtalk_enterprise_id=dingtalk_enterprise_id,
                external_subject_id=external_subject_id,
                display_name=display_name,
                source_connector_id=source_connector_id,
                source_ingress_event_id=source_ingress_event_id,
                observed_at=observed_at,
                replace_current=replace_current,
                restore_historical=restore_historical,
            )
        except NonRetryableExecutionError:
            self.audit_service.record(
                "identity.external.binding_conflict",
                status="DENIED",
                summary="DingTalk identity binding conflict",
                actor_id=actor_id,
                payload={
                    "user_id": user_id,
                    "dingtalk_enterprise_id": dingtalk_enterprise_id,
                },
            )
            raise
        self.audit_service.record(
            "identity.external.bound",
            status="SUCCEEDED",
            summary="DingTalk identity bound to internal user",
            actor_id=actor_id,
            payload={
                "user_id": user_id,
                "identity_id": identity["id"],
                "dingtalk_enterprise_id": dingtalk_enterprise_id,
                "before_count": len(before),
            },
        )
        return identity

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_identity_status(
        self,
        *,
        actor_id: str,
        identity_id: str,
        status: str,
        expected_revision: int,
    ) -> dict[str, object]:
        before = self.repository.get_external_identity(identity_id)
        if str(before["provider"]) == "ones" and status == "enabled":
            raise PermissionDenied(
                "Administrators cannot enable ONES identities",
                safe_message="ONES 身份必须由用户本人重新验证后启用",
                error_code="ones_self_reverification_required",
            )
        credential_revision: int | None = None
        if (
            str(before["provider"]) == "ones"
            and status == "disabled"
            and self.credential_repository is not None
        ):
            credential = self.credential_repository.get_by_identity(identity_id)
            if credential is not None and str(credential["status"]) != "DISABLED":
                projected = self.credential_repository.disable(
                    credential_id=str(credential["id"]),
                    expected_revision=int(credential["revision"]),
                )
                credential_revision = int(projected["revision"])
        identity = self.repository.set_external_identity_status(
            identity_id, status=status, expected_revision=expected_revision
        )
        self.audit_service.record(
            "identity.external.status_changed",
            status="SUCCEEDED",
            summary="External identity status changed",
            actor_id=actor_id,
            payload={
                "identity_id": identity_id,
                "user_id": identity["user_id"],
                "before_status": before["status"],
                "after_status": status,
                "provider_user_id": before.get("external_subject_id"),
                "credential_revision": credential_revision,
            },
        )
        return identity

    @operation_unit_of_work(lambda service: service.repository.database)
    def unbind_identity(
        self,
        *,
        actor_id: str,
        identity_id: str,
        expected_revision: int,
    ) -> dict[str, object]:
        before = self.repository.get_external_identity(identity_id)
        if str(before["provider"]) == "ones":
            raise PermissionDenied(
                "Administrators cannot unbind ONES identities",
                safe_message="ONES 身份只能由用户本人解绑",
                error_code="ones_self_unbind_required",
            )
        identity = self.repository.unbind_external_identity(
            identity_id,
            expected_revision=expected_revision,
        )
        self.audit_service.record(
            "identity.external.unbound",
            status="SUCCEEDED",
            summary="External identity unbound from internal user",
            actor_id=actor_id,
            payload={
                "identity_id": identity_id,
                "user_id": identity["user_id"],
                "provider": identity["provider"],
                "before_status": before["status"],
                "after_status": identity["status"],
            },
        )
        return identity
