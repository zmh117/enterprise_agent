from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)


Status = Literal["enabled", "disabled"]


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=320)
    password: str | None = Field(default=None, min_length=12, max_length=512)


class UpdateUserRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=320)
    status: Status


class CreateRoleRequest(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class UpdateRoleRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    status: Status


class MembershipRequest(BaseModel):
    role_id: str
    enabled: bool = True
    expected_revision: int = Field(ge=0)


class BindDingTalkRequest(BaseModel):
    expected_user_revision: int = Field(ge=1)
    tenant_code: str = Field(min_length=1, max_length=120)
    external_subject_id: str = Field(min_length=1, max_length=200)
    connector_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=200)


class IdentityStatusRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    status: Status


class PermissionRequest(BaseModel):
    id: str | None = None
    subject_type: Literal["user", "role"]
    subject_code: str
    resource_type: str
    resource_code: str = "*"
    action: str = "use"
    effect: Literal["allow", "deny"] = "allow"
    priority: int = 100
    status: Status = "enabled"
    expected_revision: int = Field(ge=0)


def build_identity_admin_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["identity-admin"])

    @router.get("/users")
    def list_users(request: Request) -> dict[str, Any]:
        require_action(
            request, resource_type="user", resource_code="*", action="manage"
        )
        c = container(request)
        return {"users": c.identity_repository.list_users()}

    @router.post("/users")
    def create_user(request: Request, payload: CreateUserRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="user",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            user = container(request).identity_admin_service.create_user(
                actor_id=principal.user_id,
                username=payload.username,
                display_name=payload.display_name,
                email=payload.email,
                password=payload.password,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"user": user}

    @router.get("/users/{user_id}")
    def get_user(request: Request, user_id: str) -> dict[str, Any]:
        require_action(
            request, resource_type="user", resource_code=user_id, action="manage"
        )
        c = container(request)
        return {
            "user": c.identity_repository.get_user(user_id),
            "roles": c.identity_repository.list_user_roles(user_id),
            "identities": c.identity_repository.list_external_identities(user_id),
            "sessions": c.identity_repository.list_sessions(user_id),
        }

    @router.put("/users/{user_id}")
    def update_user(
        request: Request, user_id: str, payload: UpdateUserRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="user",
            resource_code=user_id,
            action="manage",
            csrf=True,
        )
        try:
            user = container(request).identity_admin_service.update_user(
                actor_id=principal.user_id,
                user_id=user_id,
                expected_revision=payload.expected_revision,
                display_name=payload.display_name,
                email=payload.email,
                status=payload.status,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"user": user}

    @router.post("/users/{user_id}/roles")
    def assign_role(
        request: Request, user_id: str, payload: MembershipRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="role",
            resource_code=payload.role_id,
            action="manage",
            csrf=True,
        )
        try:
            membership = container(request).identity_admin_service.assign_role(
                actor_id=principal.user_id,
                user_id=user_id,
                role_id=payload.role_id,
                enabled=payload.enabled,
                expected_revision=payload.expected_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"membership": membership}

    @router.post("/users/{user_id}/dingtalk-identities")
    def bind_dingtalk(
        request: Request, user_id: str, payload: BindDingTalkRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="identity",
            resource_code=user_id,
            action="manage",
            csrf=True,
        )
        try:
            identity = container(request).identity_service.bind_dingtalk(
                actor_id=principal.user_id,
                user_id=user_id,
                tenant_code=payload.tenant_code,
                external_subject_id=payload.external_subject_id,
                connector_id=payload.connector_id,
                display_name=payload.display_name,
                expected_user_revision=payload.expected_user_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"identity": identity}

    @router.put("/identities/{identity_id}/status")
    def set_identity_status(
        request: Request, identity_id: str, payload: IdentityStatusRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="identity",
            resource_code=identity_id,
            action="manage",
            csrf=True,
        )
        try:
            identity = container(request).identity_service.set_identity_status(
                actor_id=principal.user_id,
                identity_id=identity_id,
                status=payload.status,
                expected_revision=payload.expected_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"identity": identity}

    @router.delete("/identities/{identity_id}")
    def unbind_identity(
        request: Request, identity_id: str, expected_revision: int
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="identity",
            resource_code=identity_id,
            action="manage",
            csrf=True,
        )
        try:
            identity = container(request).identity_service.set_identity_status(
                actor_id=principal.user_id,
                identity_id=identity_id,
                status="disabled",
                expected_revision=expected_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"identity": identity}

    @router.get("/roles")
    def list_roles(request: Request) -> dict[str, Any]:
        require_action(
            request, resource_type="role", resource_code="*", action="manage"
        )
        return {"roles": container(request).identity_repository.list_roles()}

    @router.get("/roles/{role_id}")
    def get_role(request: Request, role_id: str) -> dict[str, Any]:
        require_action(
            request, resource_type="role", resource_code=role_id, action="manage"
        )
        repository = container(request).identity_repository
        role = repository.get_role(role_id)
        return {
            "role": role,
            "members": repository.list_role_members(role_id),
            "permissions": repository.list_role_policies(str(role["code"])),
        }

    @router.post("/roles")
    def create_role(request: Request, payload: CreateRoleRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="role",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            role = container(request).identity_admin_service.create_role(
                actor_id=principal.user_id,
                code=payload.code,
                name=payload.name,
                description=payload.description,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"role": role}

    @router.put("/roles/{role_id}")
    def update_role(
        request: Request, role_id: str, payload: UpdateRoleRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="role",
            resource_code=role_id,
            action="manage",
            csrf=True,
        )
        try:
            role = container(request).identity_admin_service.update_role(
                actor_id=principal.user_id,
                role_id=role_id,
                expected_revision=payload.expected_revision,
                name=payload.name,
                description=payload.description,
                status=payload.status,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"role": role}

    @router.post("/permissions")
    def upsert_permission(
        request: Request, payload: PermissionRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="user" if payload.subject_type == "user" else "role",
            resource_code=payload.subject_code,
            action="manage",
            csrf=True,
        )
        try:
            policy = container(request).identity_admin_service.upsert_policy(
                actor_id=principal.user_id,
                policy_id=payload.id,
                subject_type=payload.subject_type,
                subject_code=payload.subject_code,
                resource_type=payload.resource_type,
                resource_code=payload.resource_code,
                action=payload.action,
                effect=payload.effect,
                priority=payload.priority,
                status=payload.status,
                expected_revision=payload.expected_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"permission": policy}

    @router.get("/permissions")
    def list_permissions(request: Request) -> dict[str, Any]:
        require_action(
            request, resource_type="role", resource_code="*", action="manage"
        )
        return {"permissions": container(request).identity_repository.list_policies()}

    @router.get("/audit-events")
    def list_audit_events(request: Request, limit: int = 200) -> dict[str, Any]:
        require_action(
            request, resource_type="audit", resource_code="*", action="read"
        )
        return {
            "events": container(request).audit_repository.list_recent(limit=limit)
        }

    @router.get("/dingtalk-tenants")
    def list_dingtalk_tenants(request: Request) -> dict[str, Any]:
        require_action(
            request, resource_type="identity", resource_code="*", action="manage"
        )
        c = container(request)
        connectors = [
            row
            for row in c.database.execute(
                """
                select id, name, metadata, enabled
                from integration_connector
                where connector_type = 'dingtalk_enterprise_stream'
                order by name
                """
            )
            if int(row["enabled"]) == 1
        ]
        return {
            "tenants": [
                {
                    "connector_id": row["id"],
                    "name": row["name"],
                    "tenant_code": _metadata_tenant(
                        str(row.get("metadata") or "{}"),
                        c.settings.identity.dingtalk_tenant_code,
                    ),
                }
                for row in connectors
            ]
        }

    @router.get("/identity-conflicts")
    def identity_conflict(
        request: Request,
        tenant_code: str,
        external_subject_id: str,
        provider: str = "dingtalk",
    ) -> dict[str, Any]:
        require_action(
            request, resource_type="identity", resource_code="*", action="manage"
        )
        existing = container(request).identity_repository.find_external_identity(
            provider=provider,
            tenant_code=tenant_code,
            external_subject_id=external_subject_id,
            include_disabled=True,
        )
        return {
            "conflict": bool(existing),
            "binding": existing,
        }

    @router.delete("/users/{user_id}/sessions/{session_id}")
    def revoke_user_session(
        request: Request, user_id: str, session_id: str
    ) -> dict[str, str]:
        principal = require_action(
            request,
            resource_type="user",
            resource_code=user_id,
            action="manage",
            csrf=True,
        )
        changed = container(request).identity_repository.revoke_owned_session(
            session_id=session_id,
            user_id=user_id,
        )
        if not changed:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Session not found")
        container(request).audit_service.record(
            "admin.session.revoked",
            status="SUCCEEDED",
            summary="User session revoked by administrator",
            actor_id=principal.user_id,
            payload={"user_id": user_id, "session_id": session_id},
        )
        return {"status": "revoked"}

    return router


def _metadata_tenant(value: str, default: str) -> str:
    import json

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default
    return str(parsed.get("tenant_code") or default)
