from __future__ import annotations

import math
from typing import Any, Literal

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.admin.domain import ADMIN_CAPABILITIES, ADMIN_CAPABILITY_BY_CODE
from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_action,
    require_csrf,
)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CreateUserRequest(_StrictRequest):
    username: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=320)
    password: str | None = Field(default=None, min_length=12, max_length=512)


class _UpdateUserRequest(_StrictRequest):
    expected_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=320)
    status: Literal["enabled", "disabled"]


class _CreateRoleRequest(_StrictRequest):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    purpose_tags: list[str] = Field(default_factory=list, max_length=20)


class _UpdateRoleRequest(_StrictRequest):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    purpose_tags: list[str] = Field(default_factory=list, max_length=20)
    status: Literal["enabled", "disabled"]


class _ReplaceAdminCapabilitiesRequest(_StrictRequest):
    expected_revision: int = Field(ge=1)
    capability_codes: list[str] = Field(default_factory=list, max_length=200)


class _ReplaceBusinessAccessRequest(_StrictRequest):
    expected_revision: int = Field(ge=1)
    application_ids: list[str] = Field(default_factory=list, max_length=200)


class _MembershipChange(_StrictRequest):
    user_id: str = Field(min_length=1, max_length=200)
    enabled: bool
    expected_revision: int = Field(ge=0)


class _ReplaceMembersRequest(_StrictRequest):
    expected_revision: int = Field(ge=1)
    changes: list[_MembershipChange] = Field(default_factory=list, max_length=200)


def build_identity_admin_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["identity-governance"])

    @router.get("/users")
    def users(
        request: Request,
        search: str = Query(default="", max_length=120),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        require_action(request, resource_type="user", resource_code="*", action="read")
        repository = container(request).identity_repository
        total = repository.count_users(
            include_disabled=include_disabled,
            search=search,
        )
        values = repository.list_users(
            include_disabled=include_disabled,
            search=search,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "users": [_public_user(value) for value in values],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": math.ceil(total / page_size) if total else 0,
            },
        }

    @router.post("/users")
    def create_user(
        request: Request,
        payload: _CreateUserRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            user = container(request).identity_admin_service.create_user(
                actor_id=principal.user_id,
                username=payload.username,
                display_name=payload.display_name,
                email=payload.email,
                password=payload.password,
            )
            return {"user": _public_user(user)}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/users/{user_id}")
    def user_detail(request: Request, user_id: str) -> dict[str, Any]:
        require_action(request, resource_type="user", resource_code=user_id, action="read")
        repository = container(request).identity_repository
        try:
            user = repository.get_user(user_id)
            return {
                "user": _public_user(user),
                "roles": [_public_role_membership(item) for item in repository.list_user_roles(user_id)],
                "sessions": repository.list_sessions(user_id),
                "external_identities": repository.list_external_identities(user_id),
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/users/{user_id}")
    def update_user(
        request: Request,
        user_id: str,
        payload: _UpdateUserRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            user = container(request).identity_admin_service.update_user(
                actor_id=principal.user_id,
                user_id=user_id,
                expected_revision=payload.expected_revision,
                display_name=payload.display_name,
                email=payload.email,
                status=payload.status,
            )
            return {"user": _public_user(user)}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/users/{user_id}/sessions/{session_id}/revoke")
    def revoke_user_session(
        request: Request,
        user_id: str,
        session_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, str]:
        del idempotency_key
        principal = require_action(
            request,
            resource_type="user_session",
            resource_code=user_id,
            action="revoke",
            csrf=True,
        )
        changed = container(request).identity_repository.revoke_owned_session(
            session_id=session_id,
            user_id=user_id,
        )
        if not changed:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="未找到活动会话")
        container(request).audit_service.record(
            "admin.user_session.revoked",
            status="SUCCEEDED",
            summary="User session revoked by administrator",
            actor_id=principal.user_id,
            payload={"user_id": user_id, "session_id": session_id},
        )
        return {"status": "revoked"}

    @router.get("/authorization/capabilities")
    def capability_catalog(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="role", resource_code="*", action="read")
        return {"items": [item.to_dict() for item in ADMIN_CAPABILITIES]}

    @router.get("/authorization/roles")
    def roles(
        request: Request,
        search: str = Query(default="", max_length=120),
        status: str = Query(default="", max_length=20),
        origin: str = Query(default="", max_length=20),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        require_action(request, resource_type="role", resource_code="*", action="read")
        values, total = container(request).authorization_center_repository.list_roles(
            search=search,
            status=status,
            origin=origin,
            limit=limit,
            offset=offset,
        )
        return {"items": values, "page": {"limit": limit, "offset": offset, "total": total}}

    @router.post("/authorization/roles")
    def create_role(
        request: Request,
        payload: _CreateRoleRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = require_action(
            request, resource_type="role", resource_code="*", action="manage", csrf=True
        )
        repository = container(request).authorization_center_repository
        try:
            role = repository.create_role(
                code=payload.code,
                name=payload.name.strip(),
                description=payload.description.strip(),
                purpose_tags=_tags(payload.purpose_tags),
            )
            container(request).audit_service.record(
                "admin.role.created",
                status="SUCCEEDED",
                summary="RBAC role created",
                actor_id=principal.user_id,
                payload={"role_id": role["id"], "role_code": role["code"]},
            )
            return _role_detail(request, str(role["id"]))
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/authorization/roles/{role_id}")
    def role_detail(request: Request, role_id: str) -> dict[str, Any]:
        require_action(request, resource_type="role", resource_code=role_id, action="read")
        try:
            return _role_detail(request, role_id)
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/authorization/roles/{role_id}/metadata")
    def update_role(
        request: Request,
        role_id: str,
        payload: _UpdateRoleRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = require_action(
            request, resource_type="role", resource_code=role_id, action="manage", csrf=True
        )
        try:
            role = container(request).authorization_center_repository.update_metadata(
                role_id,
                expected_revision=payload.expected_revision,
                name=payload.name.strip(),
                description=payload.description.strip(),
                purpose_tags=_tags(payload.purpose_tags),
                status=payload.status,
            )
            container(request).audit_service.record(
                "admin.role.metadata.updated",
                status="SUCCEEDED",
                summary="Role metadata updated",
                actor_id=principal.user_id,
                payload={"role_id": role_id, "revision": role["metadata_revision"]},
            )
            return {"role": role}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/authorization/roles/{role_id}/admin-capabilities")
    def replace_admin_capabilities(
        request: Request,
        role_id: str,
        payload: _ReplaceAdminCapabilitiesRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = require_action(
            request, resource_type="role", resource_code=role_id, action="manage", csrf=True
        )
        try:
            definitions = _capability_closure(payload.capability_codes)
            result = container(request).authorization_center_repository.replace_admin_bindings(
                role_id,
                expected_revision=payload.expected_revision,
                bindings=[
                    {
                        "capability_code": item.code,
                        "resource_type": item.resource_type,
                        "resource_code": item.resource_code,
                    }
                    for item in definitions
                ],
            )
            container(request).audit_service.record(
                "admin.role.capabilities.updated",
                status="SUCCEEDED",
                summary="Role management capabilities updated",
                actor_id=principal.user_id,
                payload={
                    "role_id": role_id,
                    "revision": result["revision"],
                    "capability_codes": [item.code for item in definitions],
                },
            )
            return result
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/authorization/roles/{role_id}/business-access")
    def replace_business_access(
        request: Request,
        role_id: str,
        payload: _ReplaceBusinessAccessRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = require_action(
            request, resource_type="role", resource_code=role_id, action="manage", csrf=True
        )
        repository = container(request).authorization_center_repository
        try:
            application_ids = sorted(set(payload.application_ids))
            for application_id in application_ids:
                application = container(request).database.execute_one(
                    "select id from business_application where id = ? and status != 'archived'",
                    (application_id,),
                )
                if application is None:
                    raise ValueError("业务应用不存在或已归档")
            result = repository.replace_business_access(
                role_id,
                expected_revision=payload.expected_revision,
                applications=[{"application_id": value} for value in application_ids],
            )
            container(request).audit_service.record(
                "admin.role.business_access.updated",
                status="SUCCEEDED",
                summary="Role Application access updated",
                actor_id=principal.user_id,
                payload={"role_id": role_id, "revision": result["revision"], "application_ids": application_ids},
            )
            return result
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/authorization/assignable-applications")
    def assignable_applications(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="role", resource_code="*", action="read")
        return {
            "items": container(request).database.execute(
                """
                select id, code, name, description, project_code, status
                  from business_application
                 where status != 'archived'
                 order by lower(name), code
                """
            )
        }

    @router.post("/authorization/roles/{role_id}/members:batch")
    def update_members(
        request: Request,
        role_id: str,
        payload: _ReplaceMembersRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = require_action(
            request, resource_type="role", resource_code=role_id, action="manage", csrf=True
        )
        repository = container(request).authorization_center_repository
        try:
            with container(request).database.unit_of_work():
                repository.bump_membership_revision(role_id, payload.expected_revision)
                values = []
                for change in payload.changes:
                    values.append(
                        container(request).identity_admin_service.assign_role(
                            actor_id=principal.user_id,
                            user_id=change.user_id,
                            role_id=role_id,
                            enabled=change.enabled,
                            expected_revision=change.expected_revision,
                        )
                    )
            return {
                "revision": repository.get_role(role_id)["membership_revision"],
                "members": [_public_member(value) for value in container(request).identity_repository.list_role_members(role_id)],
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router


def _role_detail(request: Request, role_id: str) -> dict[str, Any]:
    repository = container(request).authorization_center_repository
    role = repository.get_role(role_id)
    return {
        "role": role,
        "admin": {
            "revision": role["admin_revision"],
            "bindings": repository.list_admin_bindings(role_id),
            "implicit_all": bool(role["protected"] and role["code"] == "platform-admin"),
        },
        "business": {
            "revision": role["business_revision"],
            "applications": repository.list_business_access(role_id),
        },
        "membership": {
            "revision": role["membership_revision"],
            "members": [
                _public_member(value)
                for value in container(request).identity_repository.list_role_members(role_id)
            ],
        },
    }


def _capability_closure(codes: list[str]) -> list[Any]:
    pending = list(dict.fromkeys(codes))
    selected: set[str] = set()
    while pending:
        code = pending.pop()
        definition = ADMIN_CAPABILITY_BY_CODE.get(code)
        if definition is None or not definition.assignable:
            raise ValueError("管理权限不存在或不可分配")
        if code in selected:
            continue
        selected.add(code)
        pending.extend(definition.dependencies)
    return [item for item in ADMIN_CAPABILITIES if item.code in selected]


def _public_user(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "id",
            "username",
            "display_name",
            "email",
            "status",
            "account_type",
            "revision",
            "created_at",
            "updated_at",
        )
    }


def _public_role_membership(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "id",
            "code",
            "name",
            "description",
            "status",
            "origin",
            "protected",
            "membership_id",
            "membership_status",
            "membership_revision",
            "expires_at",
            "assigned_by",
            "assignment_source",
        )
    }


def _public_member(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "id",
            "username",
            "display_name",
            "email",
            "status",
            "account_type",
            "membership_id",
            "membership_status",
            "membership_revision",
            "expires_at",
            "assigned_by",
            "assignment_source",
        )
    }


def _tags(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))
