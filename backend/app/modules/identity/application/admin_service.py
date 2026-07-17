from __future__ import annotations

from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.application.identity_service import IdentityService
from app.modules.identity.application.passwords import PasswordService
from app.modules.identity.infrastructure import IdentityRepository


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
        with self.repository.database.transaction():
            user = self.repository.create_user(
                username=username.strip(),
                display_name=display_name.strip(),
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
        before = self.repository.get_user(user_id)
        user = self.repository.update_user(
            user_id,
            expected_revision=expected_revision,
            display_name=display_name,
            email=email,
            status=status,
        )
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
        return user

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
        return membership

    def upsert_policy(
        self,
        *,
        actor_id: str,
        policy_id: str | None,
        subject_type: str,
        subject_code: str,
        resource_type: str,
        resource_code: str,
        action: str,
        effect: str,
        priority: int,
        status: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        self.authorization.require(
            user_id=actor_id,
            resource_type="user" if subject_type == "user" else "role",
            resource_code=subject_code,
            action="manage",
        )
        before = self.repository.get_policy(policy_id) if policy_id else None
        policy = self.repository.upsert_policy(
            policy_id=policy_id,
            subject_type=subject_type,
            subject_code=subject_code,
            resource_type=resource_type,
            resource_code=resource_code,
            action=action,
            effect=effect,
            priority=priority,
            status=status,
            expected_revision=expected_revision,
        )
        self.audit_service.record(
            "admin.permission.updated",
            status="SUCCEEDED",
            summary="RBAC permission updated",
            actor_id=actor_id,
            payload={
                "policy_id": policy["id"],
                "before": before or {},
                "after": policy,
            },
        )
        return policy
