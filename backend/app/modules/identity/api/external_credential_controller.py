from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_action,
    require_csrf,
)
from app.modules.identity.api.external_identity_schemas import (
    AdminOnesStatusResponse,
    SelfIdentityOverviewResponse,
    SelfOnesStatusResponse,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BeginOnesBindingRequest(StrictRequest):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=512)


class ConfirmOnesBindingRequest(StrictRequest):
    challenge_id: str = Field(min_length=1, max_length=200)
    default_team_id: str = Field(min_length=1, max_length=200)
    replace_existing: bool = False


class ChangeDefaultTeamRequest(StrictRequest):
    default_team_id: str = Field(min_length=1, max_length=200)
    expected_identity_revision: int = Field(ge=1)


def build_external_credential_router() -> APIRouter:
    router = APIRouter(tags=["external-credentials"])

    @router.get(
        "/api/me/external-identities",
        response_model=SelfIdentityOverviewResponse,
    )
    def self_overview(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return cast(
                dict[str, Any],
                container(request).external_credential_binding_service.self_overview(
                    actor_id=principal.user_id
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get(
        "/api/me/external-identities/ones",
        response_model=SelfOnesStatusResponse,
    )
    def self_status(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return cast(
                dict[str, Any],
                container(request).external_credential_binding_service.self_status(
                    actor_id=principal.user_id
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/api/me/external-identities/ones/challenges")
    def begin_self_binding(
        request: Request,
        payload: BeginOnesBindingRequest,
    ) -> dict[str, Any]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            challenge = container(request).external_credential_binding_service.begin_self_binding(
                actor_id=principal.user_id,
                email=payload.email,
                password=payload.password.get_secret_value(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"challenge": challenge}

    @router.post(
        "/api/me/external-identities/ones/confirm",
        response_model=SelfOnesStatusResponse,
    )
    def confirm_self_binding(
        request: Request,
        payload: ConfirmOnesBindingRequest,
    ) -> dict[str, Any]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return cast(
                dict[str, Any],
                container(request).external_credential_binding_service.confirm_self_binding(
                    actor_id=principal.user_id,
                    challenge_id=payload.challenge_id,
                    default_team_id=payload.default_team_id,
                    replace_existing=payload.replace_existing,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put(
        "/api/me/external-identities/ones/default-team",
        response_model=SelfOnesStatusResponse,
    )
    def change_default_team(
        request: Request,
        payload: ChangeDefaultTeamRequest,
    ) -> dict[str, Any]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return cast(
                dict[str, Any],
                container(request).external_credential_binding_service.change_default_team(
                    actor_id=principal.user_id,
                    default_team_id=payload.default_team_id,
                    expected_identity_revision=payload.expected_identity_revision,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/api/me/external-identities/dingtalk/challenges")
    def begin_dingtalk_binding(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            challenge = container(
                request
            ).external_credential_binding_service.begin_dingtalk_binding(actor_id=principal.user_id)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"challenge": challenge}

    @router.delete("/api/me/external-identities/ones")
    def self_unbind(request: Request) -> dict[str, str]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            container(request).external_credential_binding_service.self_unbind(
                actor_id=principal.user_id
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"status": "unbound"}

    @router.get(
        "/api/admin/users/{user_id}/external-credentials/ones",
        response_model=AdminOnesStatusResponse,
    )
    def admin_status(
        request: Request,
        user_id: str,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="external_credential",
            resource_code=user_id,
            action="read",
        )
        try:
            return cast(
                dict[str, Any],
                container(request).external_credential_binding_service.admin_status(
                    actor_id=principal.user_id,
                    user_id=user_id,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put(
        "/api/admin/users/{user_id}/external-credentials/ones/disable",
        response_model=AdminOnesStatusResponse,
    )
    def admin_disable(
        request: Request,
        user_id: str,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="external_credential",
            resource_code=user_id,
            action="disable",
            csrf=True,
        )
        try:
            return cast(
                dict[str, Any],
                container(request).external_credential_binding_service.admin_disable(
                    actor_id=principal.user_id,
                    user_id=user_id,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.delete("/api/admin/users/{user_id}/external-credentials/ones")
    def admin_unbind(
        request: Request,
        user_id: str,
    ) -> dict[str, str]:
        principal = require_action(
            request,
            resource_type="external_credential",
            resource_code=user_id,
            action="unbind",
            csrf=True,
        )
        try:
            container(request).external_credential_binding_service.admin_unbind(
                actor_id=principal.user_id,
                user_id=user_id,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"status": "unbound"}

    return router
