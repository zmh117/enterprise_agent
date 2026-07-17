from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_csrf,
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=512)


class LoginRateLimiter:
    def __init__(self, limit: int = 10, window_seconds: int = 300) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.attempts: dict[str, deque[float]] = defaultdict(deque)

    def require(self, key: str) -> None:
        now = time.monotonic()
        attempts = self.attempts[key]
        while attempts and attempts[0] < now - self.window_seconds:
            attempts.popleft()
        if len(attempts) >= self.limit:
            raise HTTPException(status_code=429, detail="Too many login attempts")

    def record_failure(self, key: str) -> None:
        self.attempts[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        self.attempts.pop(key, None)


_login_limiter = LoginRateLimiter()


def build_auth_router() -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["admin-auth"])

    @router.post("/login")
    def login(request: Request, response: Response, payload: LoginRequest) -> dict[str, Any]:
        c = container(request)
        if not c.settings.identity.web_admin_enabled:
            raise HTTPException(status_code=404, detail="Web administration is disabled")
        client_host = request.client.host if request.client else ""
        rate_key = f"{payload.username.lower()}:{client_host}"
        _login_limiter.require(rate_key)
        try:
            principal, token, csrf = c.auth_service.login(
                username=payload.username,
                password=payload.password,
                user_agent_summary=request.headers.get("user-agent", ""),
                remote_address_summary=client_host,
            )
        except Exception as exc:
            _login_limiter.record_failure(rate_key)
            mapped = handle_exception(exc)
            if mapped.status_code == 403:
                mapped.status_code = 401
            raise mapped from exc
        _login_limiter.clear(rate_key)
        cookie = c.settings.identity
        response.set_cookie(
            cookie.session_cookie_name,
            token,
            httponly=True,
            secure=cookie.cookie_secure,
            samesite="lax",
            max_age=cookie.session_absolute_seconds,
            path="/",
        )
        response.set_cookie(
            cookie.csrf_cookie_name,
            csrf,
            httponly=False,
            secure=cookie.cookie_secure,
            samesite="lax",
            max_age=cookie.session_absolute_seconds,
            path="/",
        )
        return {"user": _principal_payload(principal, c.authorization_evaluator)}

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        c = container(request)
        return {
            "user": _principal_payload(
                current_principal(request), c.authorization_evaluator
            )
        }

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict[str, str]:
        principal = current_principal(request)
        require_csrf(request, principal)
        c = container(request)
        c.auth_service.logout(principal)
        response.delete_cookie(c.settings.identity.session_cookie_name, path="/")
        response.delete_cookie(c.settings.identity.csrf_cookie_name, path="/")
        return {"status": "logged_out"}

    @router.post("/password")
    def change_password(request: Request, payload: ChangePasswordRequest) -> dict[str, str]:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            container(request).auth_service.change_password(
                principal=principal,
                current=payload.current_password,
                new=payload.new_password,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"status": "password_changed"}

    @router.get("/sessions")
    def sessions(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        return {
            "sessions": container(request).identity_repository.list_sessions(
                principal.user_id
            )
        }

    @router.delete("/sessions/{session_id}")
    def revoke_session(request: Request, session_id: str) -> dict[str, str]:
        principal = current_principal(request)
        require_csrf(request, principal)
        changed = container(request).identity_repository.revoke_owned_session(
            session_id=session_id,
            user_id=principal.user_id,
        )
        if not changed:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "revoked"}

    return router


def _principal_payload(principal: Any, authorization: Any) -> dict[str, Any]:
    checks = {
        "users_manage": ("user", "*", "manage"),
        "roles_manage": ("role", "*", "manage"),
        "identities_manage": ("identity", "*", "manage"),
        "agent_edit": ("agent", "default-diagnostic-agent", "edit"),
        "agent_publish": ("agent", "default-diagnostic-agent", "publish"),
        "audit_read": ("audit", "*", "read"),
    }
    return {
        "id": principal.user_id,
        "username": principal.username,
        "display_name": principal.display_name,
        "roles": list(principal.role_codes),
        "auth_source": principal.auth_source,
        "capabilities": {
            name: authorization.decide(
                user_id=principal.user_id,
                resource_type=resource_type,
                resource_code=resource_code,
                action=action,
            ).allowed
            for name, (resource_type, resource_code, action) in checks.items()
        },
    }
