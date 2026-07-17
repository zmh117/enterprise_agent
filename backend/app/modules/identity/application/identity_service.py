from __future__ import annotations

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.domain import AuthenticatedPrincipal, ExternalIdentityDescriptor
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


class IdentityService:
    def __init__(
        self,
        repository: IdentityRepository,
        audit_service: AuditService,
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.connector_registry = connector_registry

    def resolve_external(
        self, descriptor: ExternalIdentityDescriptor
    ) -> AuthenticatedPrincipal:
        identity = self.repository.find_external_identity(
            provider=descriptor.provider,
            tenant_code=descriptor.tenant_code,
            external_subject_id=descriptor.external_subject_id,
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
                safe_message="Your DingTalk account is not authorized; contact an administrator",
                error_code="identity_not_bound",
            )
        self.repository.touch_external_identity(str(identity["id"]))
        user = self.repository.get_user(str(identity["user_id"]))
        return AuthenticatedPrincipal(
            user_id=str(user["id"]),
            username=str(user["username"]),
            display_name=str(user["display_name"]),
            role_codes=self.repository.role_codes_for_user(str(user["id"])),
            external_identity_id=str(identity["id"]),
            auth_source=descriptor.provider,
        )

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
                safe_message="DingTalk connector cannot be verified",
            )
        connector = self.connector_registry.require_dingtalk_stream_ingress(connector_id)
        trusted_tenant = self.connector_registry.metadata_value(connector, "tenant_code")
        if not trusted_tenant or trusted_tenant != tenant_code:
            raise PermissionDenied(
                "DingTalk tenant does not match trusted connector metadata",
                safe_message="DingTalk tenant does not match the selected connector",
                error_code="tenant_mismatch",
            )
        user = self.repository.get_user(user_id)
        if str(user["status"]) != "enabled" or int(user["revision"]) != expected_user_revision:
            raise NonRetryableExecutionError(
                "User revision conflict",
                safe_message="User was modified; refresh and try again",
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
