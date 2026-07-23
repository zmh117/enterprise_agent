from __future__ import annotations

from typing import Any, cast

from fastapi import HTTPException, Request

from app.modules.identity.domain import AuthenticatedPrincipal
from app.shared.exceptions import AppError, NotFound, PermissionDenied


def container(request: Request) -> Any:
    value = getattr(request.app.state, "container", None)
    if value is None:
        raise RuntimeError("Application container is not initialized")
    return value


def current_principal(request: Request) -> AuthenticatedPrincipal:
    c = container(request)
    settings = c.settings.identity
    token = request.cookies.get(settings.session_cookie_name, "")
    if token:
        try:
            return cast(
                AuthenticatedPrincipal,
                c.auth_service.authenticate_session(token),
            )
        except PermissionDenied as exc:
            raise HTTPException(status_code=401, detail=exc.safe_message) from exc
    if (
        settings.test_identity_headers_enabled
        and c.settings.environment in {"local", "test", "testing"}
    ):
        subject = (
            request.headers.get("x-admin-user-id")
            or request.headers.get("x-agent-user-id")
            or ""
        ).strip()
        if subject:
            user = c.identity_repository.get_user_by_username(subject)
            if user is None:
                try:
                    user = c.identity_repository.get_user(subject)
                except NotFound:
                    user = None
            if user and str(user["status"]) == "enabled":
                return AuthenticatedPrincipal(
                    user_id=str(user["id"]),
                    username=str(user["username"]),
                    display_name=str(user["display_name"]),
                    role_codes=c.identity_repository.role_codes_for_user(str(user["id"])),
                    auth_source="test-header",
                )
    raise HTTPException(status_code=401, detail="Authentication required")


def optional_legacy_actor(request: Request) -> str:
    c = container(request)
    if (
        c.settings.feature_configuration.unified_identity_enabled
        or c.settings.feature_configuration.web_admin_enabled
    ):
        return current_principal(request).user_id
    return (
        request.headers.get("x-admin-user-id")
        or request.headers.get("x-agent-user-id")
        or ""
    ).strip()


def require_csrf(request: Request, principal: AuthenticatedPrincipal) -> None:
    c = container(request)
    if principal.auth_source == "test-header":
        return
    settings = c.settings.identity
    origin = request.headers.get("origin", "")
    if origin and origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Origin is not allowed")
    if c.settings.environment not in {"local", "test", "testing"} and not origin:
        raise HTTPException(status_code=403, detail="Origin is required")
    session_token = request.cookies.get(settings.session_cookie_name, "")
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name, "")
    csrf_header = request.headers.get("x-csrf-token", "")
    if (
        not session_token
        or not csrf_cookie
        or not csrf_header
        or csrf_cookie != csrf_header
        or not c.auth_service.verify_csrf(session_token, csrf_header)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def require_action(
    request: Request,
    *,
    resource_type: str,
    resource_code: str,
    action: str,
    csrf: bool = False,
) -> AuthenticatedPrincipal:
    principal = current_principal(request)
    if csrf:
        require_csrf(request, principal)
    try:
        container(request).authorization_evaluator.require(
            user_id=principal.user_id,
            resource_type=resource_type,
            resource_code=resource_code,
            action=action,
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=exc.safe_message) from exc
    return principal


def handle_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=exc.safe_message)
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=exc.safe_message)
    if isinstance(exc, AppError):
        status = 409 if exc.error_code in {"revision_conflict", "identity_conflict"} else 400
        return HTTPException(
            status_code=status,
            detail={
                "message": exc.safe_message,
                "code": exc.error_code or "invalid_request",
                "field_errors": exc.field_errors,
            },
        )
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal server error")
