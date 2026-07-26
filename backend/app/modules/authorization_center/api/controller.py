from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.authorization_center.application import (
    AuthorizationCenterService,
    AuthorizationExplanationService,
    BusinessAuthorizationService,
)
from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_csrf,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRoleRequest(StrictRequest):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    purpose_tags: list[str] = Field(default_factory=list, max_length=10)
    copy_from_role_id: str = ""


class RoleMetadataRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    purpose_tags: list[str] = Field(default_factory=list, max_length=10)
    status: Literal["enabled", "disabled"]
    confirmed: bool = False
    reason: str = Field(default="", max_length=500)


class AdminCapabilityBindingRequest(StrictRequest):
    capability_code: str = Field(min_length=2, max_length=120)
    resource_code: str = Field(default="*", max_length=200)


class AdminCapabilitiesRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    bindings: list[AdminCapabilityBindingRequest] = Field(default_factory=list, max_length=500)
    confirmed: bool = False
    reason: str = Field(default="", max_length=500)


class ApplicationScopeRequest(StrictRequest):
    environment_id: str = Field(min_length=1, max_length=200)
    base_id: str = Field(default="", max_length=200)
    workshop_id: str = Field(default="", max_length=200)


class CurrentAllScopeRequest(StrictRequest):
    level: Literal["environments", "bases", "workshops"]
    environment_id: str = Field(default="", max_length=200)
    base_id: str = Field(default="", max_length=200)


class ApplicationAccessRequest(StrictRequest):
    application_id: str = Field(min_length=1, max_length=200)
    capability_codes: list[str] = Field(default_factory=list, max_length=200)
    scopes: list[ApplicationScopeRequest] = Field(default_factory=list, max_length=1000)
    current_all: list[CurrentAllScopeRequest] = Field(default_factory=list, max_length=100)


class BusinessAccessRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    applications: list[ApplicationAccessRequest] = Field(default_factory=list, max_length=100)
    confirmed: bool = False
    reason: str = Field(default="", max_length=500)


class MemberChangeRequest(StrictRequest):
    user_id: str = Field(min_length=1, max_length=200)
    enabled: bool
    expires_at: str | None = Field(default=None, max_length=80)
    source: Literal["manual", "dingtalk_binding", "api"] = "manual"


class MemberBatchRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    changes: list[MemberChangeRequest] = Field(min_length=1, max_length=500)
    confirmed: bool = False


class UserRoleChangeRequest(StrictRequest):
    role_id: str = Field(min_length=1, max_length=200)
    expected_role_revision: int = Field(ge=1)
    enabled: bool
    expires_at: str | None = Field(default=None, max_length=80)


class UserRolesBatchRequest(StrictRequest):
    changes: list[UserRoleChangeRequest] = Field(min_length=1, max_length=100)
    confirmed: bool = False


class ExplanationRequest(StrictRequest):
    user_id: str = Field(min_length=1, max_length=200)
    application_id: str = Field(default="", max_length=200)
    application_code: str = Field(default="", max_length=120)
    capability_code: str = Field(default="", max_length=120)
    environment: str = Field(default="", max_length=120)
    base: str = Field(default="", max_length=120)
    workshop: str = Field(default="", max_length=120)
    stage: Literal["invoke", "worker_start", "tool_call", "delivery"] = "invoke"


def build_authorization_center_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/authorization",
        tags=["role-authorization"],
    )

    @router.get("/capabilities")
    def capability_catalog(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            service = _service(request)
            service._require_catalog(principal.user_id, "authorization.read")
            return service.capability_catalog()
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/roles")
    def roles(
        request: Request,
        search: str = Query(default="", max_length=200),
        status: str = Query(default="", pattern=r"^(|enabled|disabled)$"),
        origin: str = Query(default="", pattern=r"^(|system|custom)$"),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return _service(request).list_roles(
                actor_id=principal.user_id,
                search=search,
                status=status,
                origin=origin,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/roles")
    def create_role(request: Request, payload: CreateRoleRequest) -> dict[str, Any]:
        principal = _write_principal(request)
        try:
            return _service(request).create_role(
                actor_id=principal.user_id,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/roles/{role_id}")
    def role_detail(request: Request, role_id: str) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return _service(request).role_detail(
                actor_id=principal.user_id, role_id=role_id
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/roles/{role_id}/audit")
    def role_audit(
        request: Request,
        role_id: str,
        limit: int = Query(default=100, ge=1, le=100),
    ) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return _service(request).role_audit(
                actor_id=principal.user_id,
                role_id=role_id,
                limit=limit,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/roles/{role_id}/metadata")
    def update_metadata(
        request: Request, role_id: str, payload: RoleMetadataRequest
    ) -> dict[str, Any]:
        principal = _write_principal(request)
        try:
            return {
                "role": _service(request).update_metadata(
                    actor_id=principal.user_id,
                    role_id=role_id,
                    **payload.model_dump(),
                )
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/roles/{role_id}/admin-capabilities")
    def update_admin_capabilities(
        request: Request, role_id: str, payload: AdminCapabilitiesRequest
    ) -> dict[str, Any]:
        principal = _write_principal(request)
        try:
            data = payload.model_dump()
            return _service(request).replace_admin_capabilities(
                actor_id=principal.user_id,
                role_id=role_id,
                **data,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/roles/{role_id}/business-access")
    def update_business_access(
        request: Request, role_id: str, payload: BusinessAccessRequest
    ) -> dict[str, Any]:
        principal = _write_principal(request)
        try:
            return _service(request).replace_business_access(
                actor_id=principal.user_id,
                role_id=role_id,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/roles/{role_id}/members:batch")
    def update_members(
        request: Request, role_id: str, payload: MemberBatchRequest
    ) -> dict[str, Any]:
        principal = _write_principal(request)
        try:
            return _service(request).update_members(
                actor_id=principal.user_id,
                role_id=role_id,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/users/{user_id}/roles:batch")
    def update_user_roles(
        request: Request,
        user_id: str,
        payload: UserRolesBatchRequest,
    ) -> dict[str, Any]:
        principal = _write_principal(request)
        try:
            return _service(request).update_user_roles(
                actor_id=principal.user_id,
                user_id=user_id,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/assignable-catalog")
    def assignable_catalog(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return _service(request).assignable_catalog(actor_id=principal.user_id)
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/explanations")
    def explain(request: Request, payload: ExplanationRequest) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            service = _service(request)
            service._require_catalog(principal.user_id, "authorization.read")
            return AuthorizationExplanationService(_business_service(request)).explain(
                **payload.model_dump()
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/advanced-exceptions")
    def advanced_exceptions(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        service = _service(request)
        try:
            service._require_catalog(principal.user_id, "authorization.manage")
            if "platform-admin" not in container(request).identity_repository.role_codes_for_user(
                principal.user_id
            ):
                raise PermissionError
            c = container(request)
            return {
                "permission_policies": c.identity_repository.list_policies(),
                "platform_access_grants": c.database.execute(
                    """
                    select id, subject_type, subject_code, environment_id, base_id,
                           workshop_id, effect, status, priority, revision,
                           created_at, updated_at
                      from platform_access_grant
                     order by subject_type, subject_code, priority, id
                    """
                ),
                "notice": "高级授权例外仅供平台管理员审查；此接口不返回连接信息或凭据。",
            }
        except PermissionError as exc:
            from app.shared.exceptions import PermissionDenied

            raise handle_exception(
                PermissionDenied(
                    "Advanced exceptions require platform-admin",
                    safe_message="仅平台管理员可以查看高级授权例外",
                    error_code="permission_denied",
                )
            ) from exc
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router


def _service(request: Request) -> AuthorizationCenterService:
    return container(request).authorization_center_service


def _business_service(request: Request) -> BusinessAuthorizationService:
    return container(request).business_authorization_service


def _write_principal(request: Request) -> Any:
    principal = current_principal(request)
    require_csrf(request, principal)
    return principal
