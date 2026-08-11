from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_csrf,
)
from app.modules.identity.api.external_identity_schemas import (
    BeginOnesIdentityResponse,
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


def build_external_identity_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["external-identities"])

    @router.get(
        "/me/external-identities",
        response_model=SelfIdentityOverviewResponse,
    )
    def self_overview(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        c = container(request)
        try:
            identities = c.identity_repository.list_external_identities(
                principal.user_id
            )
            dingtalk = [
                _dingtalk_summary(c, identity, include_admin_fields=False)
                for identity in identities
                if identity["provider"] == "dingtalk" and identity["status"] != "unbound"
            ]
            ones_status = c.ones_identity_binding_service.self_status(
                actor_id=principal.user_id
            )
            return {
                "user": {
                    "id": principal.user_id,
                    "display_name": principal.display_name,
                },
                "dingtalk": dingtalk,
                "ones": ones_status["ones"],
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get(
        "/me/external-identities/ones",
        response_model=SelfOnesStatusResponse,
    )
    def self_ones_status(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return cast(
                dict[str, Any],
                container(request).ones_identity_binding_service.self_status(
                    actor_id=principal.user_id
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post(
        "/me/external-identities/ones/challenges",
        response_model=BeginOnesIdentityResponse,
    )
    def begin_self_ones_binding(
        request: Request,
        payload: BeginOnesBindingRequest,
    ) -> dict[str, Any]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            challenge = container(
                request
            ).ones_identity_binding_service.begin_self_binding(
                actor_id=principal.user_id,
                email=payload.email,
                password=payload.password.get_secret_value(),
            )
            return {"challenge": challenge}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post(
        "/me/external-identities/ones/confirm",
        response_model=SelfOnesStatusResponse,
    )
    def confirm_self_ones_binding(
        request: Request,
        payload: ConfirmOnesBindingRequest,
    ) -> dict[str, Any]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return cast(
                dict[str, Any],
                container(request).ones_identity_binding_service.confirm_self_binding(
                    actor_id=principal.user_id,
                    challenge_id=payload.challenge_id,
                    default_team_id=payload.default_team_id,
                    replace_existing=payload.replace_existing,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.delete("/me/external-identities/ones")
    def self_unbind_ones(request: Request) -> dict[str, str]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            container(request).ones_identity_binding_service.self_unbind(
                actor_id=principal.user_id
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"status": "unbound"}

    return router


def admin_identity_overview(c: Any, user_id: str) -> dict[str, Any]:
    identities = [
        (
            _dingtalk_summary(c, identity, include_admin_fields=True)
            if identity["provider"] == "dingtalk"
            else c.ones_identity_binding_service.project_admin(identity)
        )
        for identity in c.identity_repository.list_external_identities(user_id)
        if identity["provider"] in {"dingtalk", "ones"}
    ]
    return {
        "user_id": user_id,
        "current": [item for item in identities if item["status"] != "unbound"],
        "history": [item for item in identities if item["status"] == "unbound"],
    }


def _dingtalk_summary(
    c: Any,
    identity: dict[str, Any],
    *,
    include_admin_fields: bool,
) -> dict[str, Any]:
    enterprise_id = str(identity.get("dingtalk_enterprise_id") or "")
    enterprise = (
        c.database.execute_one(
            "select name, corp_id from dingtalk_enterprise where id = ?",
            (enterprise_id,),
        )
        if enterprise_id
        else None
    )
    result: dict[str, Any] = {
        "provider": "dingtalk",
        "nickname": str(identity.get("display_name") or ""),
        "status": str(identity.get("status") or "disabled"),
        "enterprise": (
            {
                "name": str(enterprise.get("name") or ""),
                "corp_id": str(enterprise.get("corp_id") or ""),
            }
            if enterprise
            else None
        ),
        "last_used_at": identity.get("last_seen_at"),
        "staff_id": str(identity.get("external_subject_id") or ""),
    }
    if include_admin_fields:
        result.update(
            {
                "identity_id": str(identity["id"]),
                "revision": int(identity.get("revision") or 1),
                "binding_confirmed_at": identity.get("verified_at"),
                "observations": c.identity_repository.list_dingtalk_application_observations(
                    str(identity["id"])
                ),
            }
        )
    return result
