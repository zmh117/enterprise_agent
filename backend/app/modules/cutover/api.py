from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request

from app.modules.identity.api.dependencies import current_principal, require_action, require_csrf
from app.shared.exceptions import AppError


def _service(request: Request) -> Any:
    return request.app.state.container.cutover_service


def _read(request: Request) -> str:
    principal = current_principal(request)
    require_action(
        request,
        resource_type="platform_cutover",
        resource_code="legacy-platform",
        action="read",
    )
    return principal.user_id


def _write(request: Request) -> str:
    principal = current_principal(request)
    require_csrf(request, principal)
    require_action(
        request,
        resource_type="platform_cutover",
        resource_code="legacy-platform",
        action="manage",
    )
    return principal.user_id


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, AppError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.error_code, "message": exc.safe_message},
        )
    return HTTPException(
        status_code=500,
        detail={"code": "cutover_failed", "message": "破坏性切换失败"},
    )


def build_cutover_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/cutover", tags=["platform-cutover"])

    @router.get("/check")
    def check(request: Request) -> dict[str, Any]:
        _read(request)
        return cast(dict[str, Any], _service(request).check())

    @router.post("/clean")
    def clean(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        actor_id = _write(request)
        try:
            return cast(
                dict[str, Any],
                _service(request).clean(
                    actor_id=actor_id,
                    manifest_hash=str(payload.get("manifest_hash") or ""),
                    confirmation=str(payload.get("confirmation") or ""),
                    entrances_stopped=payload.get("entrances_stopped") is True,
                    workers_stopped=payload.get("workers_stopped") is True,
                    legacy_services_stopped=payload.get("legacy_services_stopped") is True,
                ),
            )
        except Exception as exc:
            raise _handle(exc) from exc

    @router.get("/verify")
    def verify(request: Request) -> dict[str, Any]:
        _read(request)
        return cast(dict[str, Any], _service(request).verify())

    return router
