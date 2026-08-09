from __future__ import annotations

from typing import Any

from app.modules.permission.application.permission_service import PermissionService
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NotFound, PermissionDenied

from ..infrastructure.repository import PlatformConfigRepository
from .secret_usage import PlatformSecretUsageService
from .secrets import SecretProviderPort
from .validation import validate_code


class PlatformConfigService:
    """Small secret-control service retained after the legacy platform retirement.

    MCP resources and deployments are governed by ``McpResourceService``. This
    class deliberately has no topology, handler, capability, runtime-config or
    generic resource-management entry points.
    """

    def __init__(
        self,
        repository: PlatformConfigRepository,
        permission_service: PermissionService,
        secret_provider: SecretProviderPort,
        *,
        environment: str = "production",
    ) -> None:
        del environment
        self.repository = repository
        self.permission_service = permission_service
        self.secret_provider = secret_provider
        self.secret_usage_service = PlatformSecretUsageService(repository)

    def require_secret_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Secret administrator actor is required",
                safe_message="缺少凭据管理员操作人",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="secret",
            resource_code="*",
            action="manage",
        )

    def list_platform_secrets(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return [
            self._public_secret(item)
            for item in self.repository.list_platform_secrets(include_disabled=include_disabled)
        ]

    def get_platform_secret(self, code: str) -> dict[str, Any]:
        secret = self.repository.get_platform_secret_by_code(validate_code(code))
        if not secret:
            raise NotFound(f"Platform secret not found: {code}")
        return self._public_secret(secret)

    def get_platform_secret_usage(self, code: str) -> dict[str, Any]:
        secret = self.repository.get_platform_secret_by_code(validate_code(code))
        if not secret:
            raise NotFound(f"Platform secret not found: {code}")
        dependencies = self.secret_usage_service.dependencies(
            secret_id=str(secret["id"]),
            secret_ref=str(secret["ref"]),
        )
        return {
            "secret": self._public_secret(secret),
            "usage_count": len(dependencies),
            "active_usage_count": sum(1 for item in dependencies if item["active"]),
            "dependencies": dependencies,
        }

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_platform_secret(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        before = self.repository.get_platform_secret_by_code(code)
        value = str(payload.pop("value", "") or "")
        try:
            secret = self.secret_provider.create_secret(
                code=code,
                value=value,
                purpose=str(payload.get("purpose") or ""),
                actor_id=actor_id,
                metadata={},
            )
        finally:
            value = ""
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "create", actor_id, before, correlation_id)
        return public

    @operation_unit_of_work(lambda service: service.repository.database)
    def rotate_platform_secret(
        self,
        code: str,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        before = self.repository.get_platform_secret_by_code(validate_code(code))
        expected_revision = int(payload.get("expected_revision") or 0)
        if expected_revision < 1:
            raise ValueError("expected_revision is required")
        value = str(payload.pop("value", "") or "")
        try:
            secret = self.secret_provider.rotate_secret(
                code=code,
                value=value,
                actor_id=actor_id,
                expected_revision=expected_revision,
            )
        finally:
            value = ""
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "rotate", actor_id, before, correlation_id)
        return public

    @operation_unit_of_work(lambda service: service.repository.database)
    def disable_platform_secret(
        self,
        code: str,
        *,
        actor_id: str,
        correlation_id: str = "",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        if expected_revision is None or expected_revision < 1:
            raise ValueError("expected_revision is required")
        before = self.repository.get_platform_secret_by_code(validate_code(code))
        secret = self.secret_provider.disable_secret(
            code=code,
            actor_id=actor_id,
            expected_revision=expected_revision,
        )
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "disable", actor_id, before, correlation_id)
        return public

    def _audit(
        self,
        entity_type: str,
        after: dict[str, Any],
        action: str,
        actor_id: str,
        before: dict[str, Any] | None,
        correlation_id: str,
    ) -> None:
        self.repository.record_config_audit(
            entity_type=entity_type,
            entity_id=str(after["id"]),
            action=action,
            actor_id=actor_id,
            before=before or {},
            after=after,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _public_secret(secret: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": secret["id"],
            "code": secret["code"],
            "provider": secret["provider"],
            "secret_ref": secret["ref"],
            "purpose": secret.get("purpose") or "",
            "status": secret["status"],
            "active_version": int(secret.get("active_version") or 0),
            "configured": bool(secret.get("configured")),
            "masked_summary": secret.get("masked_summary") or "",
            "revision": int(secret.get("revision") or 0),
            "updated_at": secret.get("updated_at"),
        }
