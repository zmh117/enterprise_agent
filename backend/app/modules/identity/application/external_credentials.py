from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3
import time
from typing import Any

from app.modules.api_capability.application import AuthenticationProfileV1
from app.modules.api_capability.infrastructure import (
    ApiConnectionRepository,
    RestrictedHttpJsonClient,
)
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import (
    AuthorizationEvaluator,
)
from app.modules.identity.infrastructure import (
    ExternalApiCredentialCipher,
    ExternalApiCredentialRepository,
    IdentityRepository,
)
from app.shared.exceptions import NonRetryableExecutionError


class ExternalCredentialBindingService:
    def __init__(
        self,
        *,
        identity_repository: IdentityRepository,
        credential_repository: ExternalApiCredentialRepository,
        connection_repository: ApiConnectionRepository,
        credential_cipher: ExternalApiCredentialCipher | None,
        audit_service: AuditService,
        authorization: AuthorizationEvaluator,
        http_client: RestrictedHttpJsonClient | None = None,
        challenge_ttl_seconds: int = 600,
    ) -> None:
        self.identity_repository = identity_repository
        self.credential_repository = credential_repository
        self.connection_repository = connection_repository
        self.credential_cipher = credential_cipher
        self.audit_service = audit_service
        self.authorization = authorization
        self.http_client = http_client or RestrictedHttpJsonClient()
        self.challenge_ttl_seconds = max(60, min(challenge_ttl_seconds, 1800))

    def self_status(self, *, actor_id: str) -> dict[str, Any]:
        user = self._require_self_user(actor_id)
        identities = [
            item
            for item in self.identity_repository.list_external_identities(actor_id)
            if item["provider"] == "ones"
        ]
        return {
            "user": {
                "id": user["id"],
                "display_name": user["display_name"],
            },
            "identity": identities[0] if identities else None,
            "credential": self.credential_repository.get_latest_public(user_id=actor_id),
        }

    def begin_self_binding(
        self,
        *,
        actor_id: str,
        email: str,
        password: str,
        connection_revision_id: str = "",
    ) -> dict[str, Any]:
        self._require_self_user(actor_id)
        cipher = self._require_cipher()
        revision = (
            self.connection_repository.get_revision(connection_revision_id)
            if connection_revision_id
            else self.connection_repository.latest_published_revision()
        )
        if str(revision["status"]) != "PUBLISHED":
            raise NonRetryableExecutionError(
                "Connection Revision is unavailable",
                safe_message="所选 ONES Connection Revision 当前不可用",
                error_code="connection_revision_unavailable",
            )
        profile = AuthenticationProfileV1(revision["authentication"])
        try:
            subject = profile.authenticate(
                client=self.http_client,
                connection=revision,
                email=email,
                password=password,
            )
        except Exception as exc:
            self.audit_service.record(
                "external_credential.self_verification",
                status="FAILED",
                summary="ONES self verification failed",
                actor_id=actor_id,
                payload={
                    "user_id": actor_id,
                    "connection_revision_id": revision["id"],
                    "result": "failed",
                    "error_code": str(getattr(exc, "error_code", "") or "ones_verification_failed"),
                },
            )
            raise
        encrypted = cipher.encrypt(subject.token)
        challenge = self.credential_repository.create_challenge(
            user_id=actor_id,
            connection_revision_id=str(revision["id"]),
            external_user_id=subject.external_user_id,
            display_name=subject.display_name,
            teams=[dict(team) for team in subject.teams],
            encrypted_token=encrypted,
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=self.challenge_ttl_seconds)
            ).isoformat(),
        )
        self.audit_service.record(
            "external_credential.self_verification",
            status="SUCCEEDED",
            summary="ONES self verification challenge created",
            actor_id=actor_id,
            payload={
                "user_id": actor_id,
                "challenge_id": challenge["id"],
                "connection_revision_id": revision["id"],
                "team_count": len(challenge["teams"]),
                "result": "succeeded",
            },
        )
        return challenge

    def confirm_self_binding(
        self,
        *,
        actor_id: str,
        challenge_id: str,
        connection_revision_id: str,
        default_team_id: str,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        self._require_self_user(actor_id)
        credential: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                credential = self.credential_repository.consume_challenge(
                    challenge_id,
                    user_id=actor_id,
                    connection_revision_id=connection_revision_id,
                    default_team_id=default_team_id,
                    replace_existing=replace_existing,
                )
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 2:
                    raise
                time.sleep(0.01 * (attempt + 1))
        if credential is None:
            raise RuntimeError("Challenge confirmation did not complete")
        identity = self.identity_repository.get_external_identity(
            str(credential["external_identity_id"])
        )
        self.audit_service.record(
            "external_credential.bound",
            status="SUCCEEDED",
            summary="ONES identity and personal credential bound",
            actor_id=actor_id,
            payload={
                "user_id": actor_id,
                "identity_id": identity["id"],
                "credential_revision": credential["revision"],
                "connection_revision_id": connection_revision_id,
                "default_team_id": default_team_id,
                "result": "succeeded",
            },
        )
        return {"identity": identity, "credential": credential}

    def admin_status(
        self,
        *,
        actor_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        self._require_admin(actor_id, "read", user_id)
        self.identity_repository.get_user(user_id)
        return {
            "user_id": user_id,
            "credential": self.credential_repository.get_latest_public(user_id=user_id),
        }

    def self_unbind(self, *, actor_id: str) -> None:
        self._require_self_user(actor_id)
        self.credential_repository.soft_unbind(user_id=actor_id)
        self.audit_service.record(
            "external_credential.self_unbound",
            status="SUCCEEDED",
            summary="User soft-unbound own ONES identity and credential",
            actor_id=actor_id,
            payload={
                "user_id": actor_id,
                "result": "succeeded",
            },
        )

    def admin_disable(
        self,
        *,
        actor_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        self._require_admin(actor_id, "disable", user_id)
        credential = self.credential_repository.set_status(
            user_id=user_id,
            status="DISABLED",
            error_code="disabled_by_admin",
        )
        self.audit_service.record(
            "external_credential.disabled",
            status="SUCCEEDED",
            summary="Personal external credential disabled by administrator",
            actor_id=actor_id,
            payload={
                "actor_id": actor_id,
                "user_id": user_id,
                "result": "succeeded",
            },
        )
        return credential

    def admin_unbind(
        self,
        *,
        actor_id: str,
        user_id: str,
    ) -> None:
        self._require_admin(actor_id, "unbind", user_id)
        self.credential_repository.soft_unbind(user_id=user_id)
        self.audit_service.record(
            "external_credential.unbound",
            status="SUCCEEDED",
            summary="ONES identity and credential soft-unbound",
            actor_id=actor_id,
            payload={
                "actor_id": actor_id,
                "user_id": user_id,
                "result": "succeeded",
            },
        )

    def apply_http_status(self, *, user_id: str, status: int) -> None:
        if status == 401:
            self.credential_repository.set_status(
                user_id=user_id,
                status="INVALID",
                error_code="external_api_unauthorized",
            )
        elif status == 403:
            self.credential_repository.get_current_public(user_id=user_id)

    def _require_self_user(self, actor_id: str) -> dict[str, Any]:
        user = self.identity_repository.get_user(actor_id)
        if str(user["status"]) != "enabled" or str(user.get("account_type") or "human") != "human":
            raise NonRetryableExecutionError(
                "Current user cannot bind external credentials",
                safe_message="当前账号不能绑定 ONES",
                error_code="external_credential_self_manage_forbidden",
            )
        return user

    def _require_admin(
        self,
        actor_id: str,
        action: str,
        user_id: str,
    ) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="external_credential",
            resource_code=user_id,
            action=action,
        )

    def _require_cipher(self) -> ExternalApiCredentialCipher:
        if self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "External API credential encryption is unavailable",
                safe_message="尚未配置外部 API 凭据加密",
                error_code="external_credential_encryption_unavailable",
            )
        return self.credential_cipher
