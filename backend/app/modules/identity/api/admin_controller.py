from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)
from app.modules.identity.api.external_identity_schemas import IdentityMutationResponse
from app.modules.identity.api.external_identity_controller import admin_identity_overview


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


class IdentityStatusRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    status: Status


def build_identity_admin_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["identity-admin"])

    @router.get("/users")
    def list_users(
        request: Request,
        search: str = Query(default="", max_length=200),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        include_disabled: bool = True,
    ) -> dict[str, Any]:
        require_action(request, resource_type="user", resource_code="*", action="read")
        c = container(request)
        total = c.identity_repository.count_users(
            include_disabled=include_disabled,
            search=search,
        )
        return {
            "users": c.identity_repository.list_users(
                include_disabled=include_disabled,
                search=search,
                limit=page_size,
                offset=(page - 1) * page_size,
            ),
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
        }

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
        require_action(request, resource_type="user", resource_code=user_id, action="read")
        c = container(request)
        authorization_summary = c.authorization_center_service.effective_summary(user_id)
        return {
            "user": c.identity_repository.get_user(user_id),
            "roles": authorization_summary["roles"],
            "authorization_summary": authorization_summary,
            "sessions": c.identity_repository.list_sessions(user_id),
        }

    @router.put("/users/{user_id}")
    def update_user(request: Request, user_id: str, payload: UpdateUserRequest) -> dict[str, Any]:
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

    @router.get("/users/{user_id}/external-identities")
    def external_identities(request: Request, user_id: str) -> dict[str, Any]:
        require_action(
            request,
            resource_type="identity",
            resource_code="*",
            action="manage",
        )
        try:
            return admin_identity_overview(container(request), user_id)
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/users/{user_id}/roles")
    def assign_role(request: Request, user_id: str, payload: MembershipRequest) -> dict[str, Any]:
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

    @router.put(
        "/identities/{identity_id}/status",
        response_model=IdentityMutationResponse,
    )
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
        return {"identity": _identity_mutation_summary(identity)}

    @router.delete(
        "/identities/{identity_id}",
        response_model=IdentityMutationResponse,
    )
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
            identity = container(request).identity_service.unbind_identity(
                actor_id=principal.user_id,
                identity_id=identity_id,
                expected_revision=expected_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"identity": _identity_mutation_summary(identity)}

    @router.get("/roles")
    def list_roles(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="role", resource_code="*", action="manage")
        return {"roles": container(request).identity_repository.list_roles()}

    @router.get("/roles/{role_id}")
    def get_role(request: Request, role_id: str) -> dict[str, Any]:
        require_action(request, resource_type="role", resource_code=role_id, action="manage")
        repository = container(request).identity_repository
        role = repository.get_role(role_id)
        return {
            "role": role,
            "members": repository.list_role_members(role_id),
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
    def update_role(request: Request, role_id: str, payload: UpdateRoleRequest) -> dict[str, Any]:
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

    @router.get("/audit-events")
    def list_audit_events(request: Request, limit: int = 200) -> dict[str, Any]:
        require_action(request, resource_type="audit", resource_code="*", action="read")
        return {"events": container(request).audit_repository.list_recent(limit=limit)}

    @router.get("/mcp-operation-audits")
    def list_mcp_operation_audits(
        request: Request,
        job_id: str = Query(default="", max_length=200),
        server_code: str = Query(default="", max_length=128),
        tool_identifier: str = Query(default="", max_length=200),
        event_kind: str = Query(default="", max_length=32),
        status: str = Query(default="", max_length=32),
        mcp_call_id: str = Query(default="", max_length=200),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="audit",
            resource_code="*",
            action="read",
        )
        c = container(request)
        filters = {
            "job_id": job_id,
            "server_code": server_code,
            "tool_identifier": tool_identifier,
            "event_kind": event_kind,
            "status": status,
            "mcp_call_id": mcp_call_id,
        }
        clauses = [f"{column} = ?" for column, value in filters.items() if value]
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params: tuple[Any, ...] = (
            *(value for value in filters.values() if value),
            limit,
        )
        rows = c.database.execute(
            f"""
            select * from mcp_operation_audit
            {where}
            order by created_at desc, id desc
            limit ?
            """,
            params,
        )
        c.audit_service.record(
            "mcp.audit.read",
            status="success",
            summary="MCP operation audit list read",
            actor_id=principal.user_id,
            payload={**filters, "count": len(rows), "limit": limit},
        )
        return {"events": [_mcp_audit_projection(row) for row in rows]}

    @router.get("/mcp-operation-audits/{audit_id}")
    def get_mcp_operation_audit(request: Request, audit_id: str) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="audit",
            resource_code="*",
            action="read",
        )
        c = container(request)
        row = c.database.execute_one(
            "select * from mcp_operation_audit where id = ?",
            (audit_id,),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="未找到 MCP 操作审计")
        c.audit_service.record(
            "mcp.audit.read",
            status="success",
            summary="MCP operation audit detail read",
            job_id=str(row["job_id"]),
            actor_id=principal.user_id,
            payload={"mcp_operation_audit_id": audit_id},
        )
        return {"event": _mcp_audit_projection(row)}

    @router.get("/dingtalk-tenants")
    def list_dingtalk_tenants(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="identity", resource_code="*", action="manage")
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

    @router.get("/external-identity-providers")
    def list_external_identity_providers(request: Request) -> dict[str, Any]:
        require_action(
            request,
            resource_type="identity",
            resource_code="*",
            action="manage",
        )
        c = container(request)
        dingtalk_count = int(
            (
                c.database.execute_one(
                    """
                    select count(*) as count
                    from integration_connector
                    where connector_type = 'dingtalk_enterprise_stream'
                      and enabled = 1
                      and allow_ingress = 1
                    """
                )
                or {"count": 0}
            )["count"]
        )
        return {
            "providers": [
                {
                    "code": "dingtalk",
                    "display_name": "钉钉",
                    "available": dingtalk_count > 0,
                },
                {
                    "code": "ones",
                    "display_name": c.ones_identity_binding_service.display_name,
                    "available": c.ones_identity_binding_service.available,
                    "instance_code": c.ones_identity_binding_service.instance_code,
                },
            ]
        }

    @router.get("/identity-conflicts")
    def identity_conflict(
        request: Request,
        tenant_code: str,
        external_subject_id: str,
        provider: Literal["dingtalk"] = "dingtalk",
    ) -> dict[str, Any]:
        require_action(request, resource_type="identity", resource_code="*", action="manage")
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
    def revoke_user_session(request: Request, user_id: str, session_id: str) -> dict[str, str]:
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

            raise HTTPException(status_code=404, detail="未找到会话")
        container(request).audit_service.record(
            "admin.session.revoked",
            status="SUCCEEDED",
            summary="User session revoked by administrator",
            actor_id=principal.user_id,
            payload={"user_id": user_id, "session_id": session_id},
        )
        return {"status": "revoked"}

    return router


def _mcp_audit_projection(row: dict[str, Any]) -> dict[str, Any]:
    projected = dict(row)
    for name in (
        "tool_request_json",
        "provider_request_json",
        "provider_response_json",
        "tool_response_json",
        "business_request_json",
        "business_response_json",
    ):
        try:
            parsed = json.loads(str(projected.get(name) or "{}"))
        except json.JSONDecodeError:
            parsed = {}
        projected[name.removesuffix("_json")] = parsed if isinstance(parsed, dict) else {}
        projected.pop(name, None)
    projected["request_truncated"] = bool(projected.get("request_truncated"))
    projected["response_truncated"] = bool(projected.get("response_truncated"))
    return projected


def _identity_mutation_summary(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(identity["id"]),
        "status": str(identity["status"]),
        "revision": int(identity["revision"]),
    }


def _metadata_tenant(value: str, default: str) -> str:
    import json

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default
    return str(parsed.get("tenant_code") or default)
