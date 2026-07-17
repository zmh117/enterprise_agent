from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.passwords import PasswordService
from app.modules.identity.domain import AuthenticatedPrincipal
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.config import IdentitySettings
from app.shared.exceptions import PermissionDenied


class AuthService:
    def __init__(
        self,
        repository: IdentityRepository,
        audit_service: AuditService,
        settings: IdentitySettings,
        password_service: PasswordService | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.settings = settings
        self.passwords = password_service or PasswordService()
        self._dummy_password_hash = self.passwords.hash(
            "not-a-real-user-password"
        )

    def login(
        self,
        *,
        username: str,
        password: str,
        user_agent_summary: str = "",
        remote_address_summary: str = "",
    ) -> tuple[AuthenticatedPrincipal, str, str]:
        user = self.repository.get_user_by_username(username)
        password_hash = (
            self.repository.get_password_hash(str(user["id"]))
            if user
            else self._dummy_password_hash
        )
        password_valid = self.passwords.verify(password_hash, password)
        valid = bool(user and str(user["status"]) == "enabled" and password_valid)
        if not valid or user is None:
            self.audit_service.record(
                "auth.login.failed",
                status="DENIED",
                summary="Local administrator login failed",
                payload={"username_hash": _sha256(username.lower())[:16]},
            )
            raise PermissionDenied(
                "Invalid credentials",
                safe_message="Invalid username or password",
                error_code="invalid_credentials",
            )
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session = self.repository.create_session(
            user_id=str(user["id"]),
            token_hash=_sha256(token),
            csrf_hash=_sha256(csrf),
            idle_expires_at=(
                now + timedelta(seconds=self.settings.session_idle_seconds)
            ).isoformat(),
            absolute_expires_at=(
                now + timedelta(seconds=self.settings.session_absolute_seconds)
            ).isoformat(),
            user_agent_summary=user_agent_summary[:200],
            remote_address_summary=remote_address_summary[:100],
        )
        principal = self._principal(user, session_id=str(session["id"]))
        self.audit_service.record(
            "auth.login.succeeded",
            status="SUCCEEDED",
            summary="Local administrator login succeeded",
            actor_id=principal.user_id,
            payload={"session_id": principal.session_id},
        )
        return principal, token, csrf

    def authenticate_session(self, token: str) -> AuthenticatedPrincipal:
        if not token:
            raise PermissionDenied(
                "Authentication required",
                safe_message="Authentication required",
                error_code="not_authenticated",
            )
        row = self.repository.get_session_by_token_hash(_sha256(token))
        if not row or str(row["status"]) != "active" or str(row["user_status"]) != "enabled":
            raise PermissionDenied(
                "Session is invalid",
                safe_message="Authentication required",
                error_code="not_authenticated",
            )
        now = datetime.now(UTC)
        if _parse_time(row["idle_expires_at"]) <= now or _parse_time(
            row["absolute_expires_at"]
        ) <= now:
            self.repository.revoke_session(str(row["id"]))
            raise PermissionDenied(
                "Session expired",
                safe_message="Session expired",
                error_code="session_expired",
            )
        self.repository.touch_session(
            str(row["id"]),
            (now + timedelta(seconds=self.settings.session_idle_seconds)).isoformat(),
        )
        user = self.repository.get_user(str(row["user_id"]))
        return self._principal(user, session_id=str(row["id"]))

    def verify_csrf(self, token: str, csrf: str) -> bool:
        row = self.repository.get_session_by_token_hash(_sha256(token))
        return bool(row and secrets.compare_digest(str(row["csrf_hash"]), _sha256(csrf)))

    def logout(self, principal: AuthenticatedPrincipal) -> None:
        if principal.session_id:
            self.repository.revoke_session(principal.session_id)
        self.audit_service.record(
            "auth.logout",
            status="SUCCEEDED",
            summary="Administrator session revoked",
            actor_id=principal.user_id,
            payload={"session_id": principal.session_id},
        )

    def change_password(
        self, *, principal: AuthenticatedPrincipal, current: str, new: str
    ) -> None:
        password_hash = self.repository.get_password_hash(principal.user_id)
        if not self.passwords.verify(password_hash, current):
            raise PermissionDenied(
                "Current password is invalid",
                safe_message="Current password is invalid",
            )
        self.repository.set_password_hash(principal.user_id, self.passwords.hash(new))
        self.repository.revoke_user_sessions(principal.user_id)
        self.audit_service.record(
            "auth.password.changed",
            status="SUCCEEDED",
            summary="User password changed and sessions revoked",
            actor_id=principal.user_id,
        )

    def bootstrap_admin(
        self, *, username: str, display_name: str, password: str
    ) -> dict[str, object]:
        if self.repository.admin_count() > 0:
            raise PermissionDenied(
                "Administrator already exists",
                safe_message="An administrator already exists",
            )
        with self.repository.database.transaction():
            user = self.repository.create_user(
                username=username, display_name=display_name
            )
            self.repository.set_password_hash(
                str(user["id"]), self.passwords.hash(password)
            )
            role = self.repository.get_role_by_code("platform-admin")
            if role is None:
                role = self.repository.create_role(
                    code="platform-admin",
                    name="平台管理员",
                    description="Full administration role",
                )
            self.repository.assign_role(
                user_id=str(user["id"]), role_id=str(role["id"])
            )
        return user

    def _principal(
        self, user: dict[str, object], *, session_id: str
    ) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id=str(user["id"]),
            username=str(user["username"]),
            display_name=str(user["display_name"]),
            role_codes=self.repository.role_codes_for_user(str(user["id"])),
            auth_source="local",
            session_id=session_id,
        )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parse_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
