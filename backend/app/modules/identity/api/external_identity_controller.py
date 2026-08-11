from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.modules.identity.api.dependencies import container, current_principal, handle_exception


def build_external_identity_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["external-identities"])

    @router.get("/me/external-identities")
    def self_overview(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        c = container(request)
        try:
            identities = [
                _dingtalk_summary(c, identity, include_admin_fields=False)
                for identity in c.identity_repository.list_external_identities(
                    principal.user_id
                )
                if identity["provider"] == "dingtalk"
                and identity["status"] != "unbound"
            ]
            return {
                "user": {
                    "id": principal.user_id,
                    "display_name": principal.display_name,
                },
                "dingtalk": identities,
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router


def admin_identity_overview(c: Any, user_id: str) -> dict[str, Any]:
    identities = [
        _dingtalk_summary(c, identity, include_admin_fields=True)
        for identity in c.identity_repository.list_external_identities(user_id)
        if identity["provider"] == "dingtalk"
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
