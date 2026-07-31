from __future__ import annotations

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.application.ones_identity import OnesIdentityVerifier
from app.modules.identity.domain import AuthenticatedPrincipal, ExternalIdentityDescriptor
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import AppError, NonRetryableExecutionError, PermissionDenied


class IdentityService:
    def __init__(
        self,
        repository: IdentityRepository,
        audit_service: AuditService,
        connector_registry: ConnectorRegistry | None = None,
        ones_verifier: OnesIdentityVerifier | None = None,
        ones_instance_code: str = "default",
        ones_display_name: str = "ONES",
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.connector_registry = connector_registry
        self.ones_verifier = ones_verifier
        self.ones_instance_code = ones_instance_code.strip() or "default"
        self.ones_display_name = ones_display_name.strip() or "ONES"

    @property
    def ones_available(self) -> bool:
        return bool(self.ones_verifier and self.ones_verifier.available)

    def resolve_external(
        self, descriptor: ExternalIdentityDescriptor
    ) -> AuthenticatedPrincipal:
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
    def bind_dingtalk(
        self,
        *,
        actor_id: str,
        user_id: str,
        tenant_code: str,
        external_subject_id: str,
        connector_id: str,
        expected_user_revision: int,
        display_name: str = "",
    ) -> dict[str, object]:
        if self.connector_registry is None:
            raise PermissionDenied(
                "Connector registry is unavailable",
                safe_message="无法验证钉钉连接器",
            )
        connector = self.connector_registry.require_dingtalk_stream_ingress(connector_id)
        trusted_tenant = self.connector_registry.metadata_value(connector, "tenant_code")
        if not trusted_tenant or trusted_tenant != tenant_code:
            raise PermissionDenied(
                "DingTalk tenant does not match trusted connector metadata",
                safe_message="钉钉企业与所选连接器不匹配",
                error_code="tenant_mismatch",
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
            identity = self.repository.bind_external_identity(
                user_id=user_id,
                provider="dingtalk",
                tenant_code=tenant_code,
                external_subject_id=external_subject_id,
                connector_id=connector_id,
                display_name=display_name,
                metadata={"verification_method": "trusted_connector"},
            )
        except NonRetryableExecutionError:
            self.audit_service.record(
                "identity.external.binding_conflict",
                status="DENIED",
                summary="DingTalk identity binding conflict",
                actor_id=actor_id,
                payload={
                    "user_id": user_id,
                    "tenant_code": tenant_code,
                    "connector_id": connector_id,
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
                "tenant_code": tenant_code,
                "connector_id": connector_id,
                "before_count": len(before),
            },
        )
        return identity

    def bind_ones(
        self,
        *,
        actor_id: str,
        user_id: str,
        email: str,
        password: str,
        expected_user_revision: int,
    ) -> dict[str, object]:
        self._require_bindable_user(
            user_id=user_id,
            expected_user_revision=expected_user_revision,
            provider="ones",
            actor_id=actor_id,
        )
        if self.ones_verifier is None or not self.ones_verifier.available:
            raise NonRetryableExecutionError(
                "ONES identity provider is unavailable",
                safe_message="ONES 身份验证不可用",
                error_code="ones_connection_unavailable",
            )
        try:
            verified = self.ones_verifier.verify(email=email, password=password)
        except AppError as exc:
            self.audit_service.record(
                "identity.external.verification_failed",
                status="DENIED",
                summary="ONES identity verification failed",
                actor_id=actor_id,
                payload={
                    "user_id": user_id,
                    "provider": "ones",
                    "instance_code": self.ones_instance_code,
                    "error_code": exc.error_code or "ones_verification_failed",
                },
            )
            raise
        try:
            with self.repository.database.unit_of_work():
                current = self._require_bindable_user(
                    user_id=user_id,
                    expected_user_revision=expected_user_revision,
                    provider="ones",
                    actor_id=actor_id,
                )
                identity = self.repository.bind_external_identity(
                    user_id=user_id,
                    provider="ones",
                    tenant_code=self.ones_instance_code,
                    external_subject_id=verified.user_uuid,
                    connector_id="",
                    display_name=verified.display_name,
                    metadata={
                        "verification_method": "ones_password_login",
                        "team_uuids": list(verified.team_uuids),
                    },
                )
                self.audit_service.record(
                    "identity.external.bound",
                    status="SUCCEEDED",
                    summary="ONES identity bound to internal user",
                    actor_id=actor_id,
                    payload={
                        "user_id": user_id,
                        "identity_id": identity["id"],
                        "provider": "ones",
                        "instance_code": self.ones_instance_code,
                        "team_count": len(verified.team_uuids),
                        "user_revision": current["revision"],
                    },
                )
        except NonRetryableExecutionError as exc:
            if exc.error_code == "identity_conflict":
                self.audit_service.record(
                    "identity.external.binding_conflict",
                    status="DENIED",
                    summary="ONES identity binding conflict",
                    actor_id=actor_id,
                    payload={
                        "user_id": user_id,
                        "provider": "ones",
                        "instance_code": self.ones_instance_code,
                    },
                )
            raise
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

    def _require_bindable_user(
        self,
        *,
        user_id: str,
        expected_user_revision: int,
        provider: str,
        actor_id: str,
    ) -> dict[str, object]:
        user = self.repository.get_user(user_id)
        if str(user.get("account_type") or "human") != "human":
            self.audit_service.record(
                "identity.external.binding_denied",
                status="DENIED",
                summary="Service account external identity binding denied",
                actor_id=actor_id,
                payload={"user_id": user_id, "provider": provider},
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
        return user
