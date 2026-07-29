from __future__ import annotations

from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.application.identity_service import IdentityService
from app.modules.identity.application.passwords import PasswordService
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError


class IdentityAdminService:
    def __init__(
        self,
        repository: IdentityRepository,
        identity_service: IdentityService,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
    ) -> None:
        self.repository = repository
        self.identity_service = identity_service
        self.authorization = authorization
        self.audit_service = audit_service
        self.passwords = PasswordService()

    def create_user(
        self,
        *,
        actor_id: str,
        username: str,
        display_name: str,
        email: str,
        password: str | None = None,
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="user",
            resource_code="*",
            action="manage",
        )
        normalized_username = username.strip()
        normalized_display_name = display_name.strip()
        if not normalized_username:
            raise NonRetryableExecutionError(
                "Username is required",
                safe_message="请输入用户名",
                error_code="invalid_user",
                field_errors=[{"field": "username", "message": "请输入用户名"}],
            )
        if not normalized_display_name:
            raise NonRetryableExecutionError(
                "Display name is required",
                safe_message="请输入显示名称",
                error_code="invalid_user",
                field_errors=[
                    {"field": "display_name", "message": "请输入显示名称"}
                ],
            )
        if self.repository.get_user_by_username(normalized_username) is not None:
            raise NonRetryableExecutionError(
                "Username already exists",
                safe_message="用户名已被使用",
                error_code="username_conflict",
                field_errors=[
                    {"field": "username", "message": "用户名已被使用"}
                ],
            )
        with self.repository.database.unit_of_work():
            user = self.repository.create_user(
                username=normalized_username,
                display_name=normalized_display_name,
                email=email.strip(),
            )
            if password:
                self.repository.set_password_hash(
                    str(user["id"]), self.passwords.hash(password)
                )
            self.audit_service.record(
                "admin.user.created",
                status="SUCCEEDED",
                summary="Internal user created",
                actor_id=actor_id,
                payload={
                    "user_id": user["id"],
                    "username": user["username"],
                    "password_configured": bool(password),
                },
            )
        return user

    def update_user(
        self,
        *,
        actor_id: str,
        user_id: str,
        expected_revision: int,
        display_name: str,
        email: str,
        status: str,
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="user",
            resource_code=user_id,
            action="manage",
        )
        try:
            with self.repository.database.unit_of_work():
                if status != "enabled":
                    self.repository.lock_platform_admin_invariant()
                before = self.repository.get_user(user_id)
                reduces_verified_admins = bool(
                    status != "enabled"
                    and str(before["status"]) == "enabled"
                    and self.repository.is_verified_human_platform_admin(user_id)
                )
                user = self.repository.update_user(
                    user_id,
                    expected_revision=expected_revision,
                    display_name=display_name.strip(),
                    email=email.strip(),
                    status=status,
                )
                if reduces_verified_admins:
                    self.repository.require_verified_human_platform_admins()
                if status != "enabled":
                    self.repository.revoke_user_sessions(user_id)
                self.audit_service.record(
                    "admin.user.updated",
                    status="SUCCEEDED",
                    summary="Internal user updated",
                    actor_id=actor_id,
                    payload={
                        "user_id": user_id,
                        "before": {
                            "display_name": before["display_name"],
                            "email": before["email"],
                            "status": before["status"],
                            "revision": before["revision"],
                        },
                        "after": user,
                    },
                )
        except NonRetryableExecutionError as exc:
            self._record_platform_admin_invariant_denied(
                exc,
                actor_id=actor_id,
                operation="user.disable",
                target_id=user_id,
            )
            raise
        return user

    def delete_user(
        self,
        *,
        actor_id: str,
        user_id: str,
        expected_revision: int,
        confirmed: bool,
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="user",
            resource_code=user_id,
            action="manage",
        )
        if not confirmed:
            raise NonRetryableExecutionError(
                "User deletion requires confirmation",
                safe_message="删除用户前需要二次确认",
                error_code="confirmation_required",
            )
        try:
            with self.repository.database.unit_of_work():
                self.repository.lock_platform_admin_invariant()
                reduces_verified_admins = (
                    self.repository.is_verified_human_platform_admin(user_id)
                )
                deleted = self.repository.delete_user(
                    user_id,
                    expected_revision=expected_revision,
                )
                if reduces_verified_admins:
                    self.repository.require_verified_human_platform_admins()
                self.audit_service.record(
                    "admin.user.deleted",
                    status="SUCCEEDED",
                    summary="Internal user deleted",
                    actor_id=actor_id,
                    payload={
                        "user_id": user_id,
                        "username": deleted["username"],
                        "account_type": deleted["account_type"],
                    },
                )
        except NonRetryableExecutionError as exc:
            self._record_platform_admin_invariant_denied(
                exc,
                actor_id=actor_id,
                operation="user.delete",
                target_id=user_id,
            )
            raise
        return deleted

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_role(
        self, *, actor_id: str, code: str, name: str, description: str
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="role",
            resource_code="*",
            action="manage",
        )
        role = self.repository.create_role(
            code=code.strip(), name=name.strip(), description=description.strip()
        )
        self.audit_service.record(
            "admin.role.created",
            status="SUCCEEDED",
            summary="RBAC role created",
            actor_id=actor_id,
            payload={"role_id": role["id"], "role_code": role["code"]},
        )
        return role

    @operation_unit_of_work(lambda service: service.repository.database)
    def update_role(
        self,
        *,
        actor_id: str,
        role_id: str,
        expected_revision: int,
        name: str,
        description: str,
        status: str,
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="role",
            resource_code=role_id,
            action="manage",
        )
        before = self.repository.get_role(role_id)
        role = self.repository.update_role(
            role_id,
            expected_revision=expected_revision,
            name=name,
            description=description,
            status=status,
        )
        self.audit_service.record(
            "admin.role.updated",
            status="SUCCEEDED",
            summary="RBAC role updated",
            actor_id=actor_id,
            payload={"role_id": role_id, "before": before, "after": role},
        )
        return role

    def assign_role(
        self,
        *,
        actor_id: str,
        user_id: str,
        role_id: str,
        enabled: bool,
        expected_revision: int,
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="user",
            resource_code=user_id,
            action="manage",
        )
        self.authorization.require(
            user_id=actor_id,
            resource_type="role",
            resource_code=role_id,
            action="manage",
        )
        try:
            with self.repository.database.unit_of_work():
                role = self.repository.get_role(role_id)
                reduces_verified_admins = False
                if not enabled and str(role["code"]) == "platform-admin":
                    self.repository.lock_platform_admin_invariant()
                    reduces_verified_admins = (
                        self.repository.is_verified_human_platform_admin(user_id)
                    )
                if enabled:
                    membership = self.repository.assign_role(
                        user_id=user_id,
                        role_id=role_id,
                        expected_revision=expected_revision,
                    )
                else:
                    membership = self.repository.remove_role(
                        user_id=user_id,
                        role_id=role_id,
                        expected_revision=expected_revision,
                    )
                if reduces_verified_admins:
                    self.repository.require_verified_human_platform_admins()
                self.audit_service.record(
                    "admin.membership.changed",
                    status="SUCCEEDED",
                    summary="User role membership changed",
                    actor_id=actor_id,
                    payload={
                        "user_id": user_id,
                        "role_id": role_id,
                        "expected_revision": expected_revision,
                        "after": membership,
                    },
                )
        except NonRetryableExecutionError as exc:
            self._record_platform_admin_invariant_denied(
                exc,
                actor_id=actor_id,
                operation="platform_admin_membership.disable",
                target_id=user_id,
            )
            raise
        return membership

    def _record_platform_admin_invariant_denied(
        self,
        exc: NonRetryableExecutionError,
        *,
        actor_id: str,
        operation: str,
        target_id: str,
    ) -> None:
        if exc.error_code != "platform_admin_invariant":
            return
        self.audit_service.record(
            "platform_admin_invariant_denied",
            status="DENIED",
            summary="Platform administrator invariant denied mutation",
            actor_id=actor_id,
            payload={"operation": operation, "target_id": target_id},
        )
