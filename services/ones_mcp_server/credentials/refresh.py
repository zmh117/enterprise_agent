from __future__ import annotations

import threading
import time
from typing import Any

from app.modules.identity.application.ones_identity import OnesIdentityVerifier
from app.modules.identity.infrastructure.external_identity_credentials import (
    ExternalIdentityCredentialRepository,
)
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.shared.exceptions import AppError
from services.ones_mcp_server.auth.principal import (
    OnesPrincipalResolver,
    ResolvedOnesPrincipal,
)
from services.ones_mcp_server.errors import OnesMcpError, error_code


class OnesCredentialRefreshService:
    """Serializes per-credential refresh and preserves revision-based convergence."""

    def __init__(
        self,
        resolver: OnesPrincipalResolver,
        login_verifier: OnesIdentityVerifier,
        credentials: ExternalIdentityCredentialRepository,
        audit: McpAuditCoordinator,
    ) -> None:
        self.resolver = resolver
        self.login_verifier = login_verifier
        self.credentials = credentials
        self.audit = audit
        self._locks_guard = threading.Lock()
        self._credential_locks: dict[str, threading.Lock] = {}

    def resolve_after_unauthorized(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        tool_identifier: str,
    ) -> ResolvedOnesPrincipal:
        original_revision = principal.credential.revision
        lock = self._lock_for(principal.credential.id)
        with lock:
            current = self.resolver.resolve(claims, tool_identifier=tool_identifier)
            if current.credential.revision == original_revision:
                self._refresh(handle, current)
            return self.resolver.resolve(claims, tool_identifier=tool_identifier)

    def reject_after_second_unauthorized(
        self,
        *,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
    ) -> None:
        self.credentials.mark_reauth_required(
            credential_id=principal.credential.id,
            expected_revision=principal.credential.revision,
            error_code="ones_provider_unauthorized_after_refresh",
        )
        self.audit.append_event(
            handle,
            event_kind="CREDENTIAL",
            attempt=1,
            status="FAILED",
            error_code="ones_provider_unauthorized_after_refresh",
            credential_revision=principal.credential.revision,
        )
        raise OnesMcpError(
            "ONES Provider rejected the refreshed Token",
            safe_message="ONES 身份需要本人重新验证",
            error_code="ones_credential_reverification_required",
        )

    def _refresh(
        self,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
    ) -> None:
        started = time.monotonic()
        try:
            verified = self.login_verifier.verify(
                email=principal.credential.secrets.email,
                password=principal.credential.secrets.password,
            )
            if (
                verified.user_uuid != principal.provider_user_id
                or principal.team_id not in verified.team_uuids
            ):
                raise OnesMcpError(
                    "ONES login identity or Team changed",
                    safe_message="ONES 身份信息已变化，请本人重新验证",
                    error_code="ones_credential_identity_changed",
                )
            rotated = self.credentials.rotate_token(
                credential_id=principal.credential.id,
                expected_revision=principal.credential.revision,
                token=verified.token,
            )
            self.audit.append_event(
                handle,
                event_kind="CREDENTIAL",
                attempt=0,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={
                    "provider_email": principal.provider_email,
                    "provider_user_id": principal.provider_user_id,
                    "previous_revision": principal.credential.revision,
                    "revision": int(rotated["revision"]),
                },
            )
        except AppError as exc:
            if getattr(exc, "error_code", "") == "mcp_audit_unavailable":
                raise
            try:
                self.credentials.mark_reauth_required(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                    error_code=error_code(exc),
                )
            except AppError:
                pass
            self.audit.append_event(
                handle,
                event_kind="CREDENTIAL",
                attempt=0,
                status="FAILED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={
                    "provider_email": principal.provider_email,
                    "provider_user_id": principal.provider_user_id,
                    "revision": principal.credential.revision,
                },
            )
            raise OnesMcpError(
                "ONES credential refresh failed",
                safe_message="ONES 身份需要本人重新验证",
                error_code="ones_credential_reverification_required",
            ) from exc

    def _lock_for(self, credential_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._credential_locks.setdefault(credential_id, threading.Lock())
