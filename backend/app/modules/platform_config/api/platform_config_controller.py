from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.bootstrap import Container
from app.modules.identity.api.dependencies import (
    current_principal,
    require_action,
    require_csrf,
)
from app.shared.exceptions import AppError, NotFound, PermissionDenied


def _container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container


def _principal(request: Request) -> Any:
    principal = current_principal(request)
    require_csrf(request, principal)
    return principal


def _require_secret_read(request: Request) -> None:
    require_action(
        request,
        resource_type="secret",
        resource_code="*",
        action="read",
    )


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=exc.safe_message)
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=exc.safe_message)
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.safe_message)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="服务器内部错误")


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "") or "").strip()


def build_platform_config_router() -> APIRouter:
    """Expose only the secret lifecycle needed by ``platformctl``.

    Resource configuration is intentionally served by ``/api/admin/mcp``.
    The retired topology, handler, capability and runtime-config routes do not
    have aliases or feature flags.
    """

    router = APIRouter(prefix="/api/platform/secrets", tags=["platform-secrets"])

    @router.get("")
    def list_secrets(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        _require_secret_read(request)
        return {
            "secrets": _container(request).platform_config_service.list_platform_secrets(
                include_disabled=include_disabled
            )
        }

    @router.post("")
    async def create_secret(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        principal = _principal(request)
        try:
            secret = _container(request).platform_config_service.create_platform_secret(
                payload,
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": secret}

    @router.get("/{code}")
    def get_secret(request: Request, code: str) -> dict[str, Any]:
        _require_secret_read(request)
        try:
            secret = _container(request).platform_config_service.get_platform_secret(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": secret}

    @router.get("/{code}/usage")
    def get_secret_usage(request: Request, code: str) -> dict[str, Any]:
        _require_secret_read(request)
        try:
            usage = _container(request).platform_config_service.get_platform_secret_usage(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"usage": usage}

    @router.post("/{code}/rotate")
    async def rotate_secret(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        principal = _principal(request)
        try:
            secret = _container(request).platform_config_service.rotate_platform_secret(
                code,
                payload,
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": secret}

    @router.post("/{code}/disable")
    async def disable_secret(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        principal = _principal(request)
        try:
            secret = _container(request).platform_config_service.disable_platform_secret(
                code,
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
                expected_revision=int(payload.get("expected_revision") or 0),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": secret}

    return router
