from __future__ import annotations

from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.ones_identity import OnesIdentityVerifier
from app.modules.identity.infrastructure.ones_identity_challenges import (
    OnesIdentityChallengeRepository,
)
from app.modules.identity.infrastructure.repository import IdentityRepository
from app.shared.exceptions import AppError, NonRetryableExecutionError, PermissionDenied


class OnesIdentityBindingService:
    def __init__(
        self,
        *,
        identity_repository: IdentityRepository,
        challenge_repository: OnesIdentityChallengeRepository,
        verifier: OnesIdentityVerifier,
        audit_service: AuditService,
        instance_code: str,
        display_name: str,
        challenge_ttl_seconds: int = 600,
    ) -> None:
        self.identity_repository = identity_repository
        self.challenge_repository = challenge_repository
        self.verifier = verifier
        self.audit_service = audit_service
        self.instance_code = instance_code.strip() or "default"
        self.display_name = display_name.strip() or "ONES"
        self.challenge_ttl_seconds = challenge_ttl_seconds

    @property
    def available(self) -> bool:
        return self.verifier.available

    def begin_self_binding(
        self,
        *,
        actor_id: str,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        self._require_self_user(actor_id)
        if not self.verifier.available:
            raise NonRetryableExecutionError(
                "ONES identity provider is unavailable",
                safe_message="ONES 身份验证不可用",
                error_code="ones_connection_unavailable",
            )
        try:
            verified = self.verifier.verify(email=email, password=password)
        except AppError as exc:
            self.audit_service.record(
                "identity.ones.verification",
                status="FAILED",
                summary="ONES identity verification failed",
                actor_id=actor_id,
                payload={
                    "user_id": actor_id,
                    "instance_code": self.instance_code,
                    "error_code": exc.error_code or "ones_verification_failed",
                },
            )
            raise
        challenge = self.challenge_repository.create(
            user_id=actor_id,
            verified=verified,
            ttl_seconds=self.challenge_ttl_seconds,
        )
        self.audit_service.record(
            "identity.ones.verification",
            status="SUCCEEDED",
            summary="ONES identity facts verified",
            actor_id=actor_id,
            payload={
                "user_id": actor_id,
                "challenge_id": challenge["id"],
                "instance_code": self.instance_code,
                "team_count": len(challenge["teams"]),
            },
        )
        return challenge

    def confirm_self_binding(
        self,
        *,
        actor_id: str,
        challenge_id: str,
        default_team_id: str,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        self._require_self_user(actor_id)
        database = self.identity_repository.database
        with database.unit_of_work():
            challenge = self.challenge_repository.consume(
                challenge_id,
                user_id=actor_id,
                default_team_id=default_team_id,
            )
            current = self._current_identities(actor_id)
            if len(current) > 1:
                raise NonRetryableExecutionError(
                    "Multiple current ONES identities exist",
                    safe_message="ONES 身份数据不一致，请联系管理员",
                    error_code="ones_identity_inconsistent",
                )
            existing = current[0] if current else None
            replacing = bool(
                existing
                and str(existing["external_subject_id"])
                != str(challenge["external_user_id"])
            )
            if replacing and not replace_existing:
                raise NonRetryableExecutionError(
                    "Explicit confirmation is required to replace ONES identity",
                    safe_message="当前账号已绑定其他 ONES 用户，请确认换绑",
                    error_code="ones_identity_replace_confirmation_required",
                )
            if replacing and existing is not None:
                self.identity_repository.unbind_external_identity(
                    str(existing["id"]),
                    expected_revision=int(existing["revision"]),
                )
            identity = self.identity_repository.bind_external_identity(
                user_id=actor_id,
                provider="ones",
                tenant_code=self.instance_code,
                external_subject_id=str(challenge["external_user_id"]),
                connector_id="",
                display_name=str(challenge["display_name"]),
                metadata={
                    "verification_method": "ones_password_login",
                    "teams": list(challenge["teams"]),
                    "team_uuids": list(challenge["team_ids"]),
                    "default_team_id": default_team_id.strip(),
                },
            )
            self.audit_service.record(
                "identity.ones.bound",
                status="SUCCEEDED",
                summary="ONES identity facts bound",
                actor_id=actor_id,
                payload={
                    "user_id": actor_id,
                    "identity_id": identity["id"],
                    "instance_code": self.instance_code,
                    "default_team_id": default_team_id.strip(),
                    "team_count": len(challenge["teams"]),
                    "replaced_existing": replacing,
                },
            )
        return self.self_status(actor_id=actor_id)

    def self_status(self, *, actor_id: str) -> dict[str, Any]:
        user = self._require_self_user(actor_id)
        current = self._current_identities(actor_id)
        if len(current) > 1:
            raise NonRetryableExecutionError(
                "Multiple current ONES identities exist",
                safe_message="ONES 身份数据不一致，请联系管理员",
                error_code="ones_identity_inconsistent",
            )
        return {
            "user": {"id": user["id"], "display_name": user["display_name"]},
            "ones": self.project_self(current[0]) if current else None,
        }

    def self_unbind(self, *, actor_id: str) -> None:
        self._require_self_user(actor_id)
        current = self._current_identities(actor_id)
        if len(current) > 1:
            raise NonRetryableExecutionError(
                "Multiple current ONES identities exist",
                safe_message="ONES 身份数据不一致，请联系管理员",
                error_code="ones_identity_inconsistent",
            )
        if not current:
            return
        identity = current[0]
        with self.identity_repository.database.unit_of_work():
            self.identity_repository.unbind_external_identity(
                str(identity["id"]), expected_revision=int(identity["revision"])
            )
            self.audit_service.record(
                "identity.ones.unbound",
                status="SUCCEEDED",
                summary="User soft-unbound own ONES identity",
                actor_id=actor_id,
                payload={"user_id": actor_id, "identity_id": identity["id"]},
            )

    @staticmethod
    def project_self(identity: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(identity.get("metadata") or {})
        teams = _normalized_teams(metadata)
        default_team_id = str(metadata.get("default_team_id") or "")
        default_team = next(
            (team for team in teams if team["id"] == default_team_id), None
        )
        return {
            "provider": "ones",
            "user_name": str(identity.get("display_name") or ""),
            "status": str(identity.get("status") or "disabled"),
            "default_team": default_team,
            "verified_at": identity.get("verified_at"),
            "user_id": str(identity.get("external_subject_id") or ""),
            "teams": teams,
        }

    @classmethod
    def project_admin(cls, identity: dict[str, Any]) -> dict[str, Any]:
        return {
            **cls.project_self(identity),
            "identity_id": str(identity["id"]),
            "revision": int(identity.get("revision") or 1),
        }

    def _current_identities(self, user_id: str) -> list[dict[str, Any]]:
        return [
            identity
            for identity in self.identity_repository.list_external_identities(user_id)
            if identity["provider"] == "ones" and identity["status"] != "unbound"
        ]

    def _require_self_user(self, actor_id: str) -> dict[str, Any]:
        user = self.identity_repository.get_user(actor_id)
        if str(user.get("account_type") or "human") != "human":
            raise PermissionDenied(
                "Service accounts cannot bind external identities",
                safe_message="服务账号不能绑定外部身份",
                error_code="service_account_identity_forbidden",
            )
        if str(user["status"]) != "enabled":
            raise PermissionDenied(
                "Disabled users cannot bind external identities",
                safe_message="当前账号不可管理外部身份",
                error_code="identity_user_inactive",
            )
        return user


def _normalized_teams(metadata: dict[str, Any]) -> list[dict[str, str]]:
    raw_teams = metadata.get("teams")
    teams: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(raw_teams, list):
        for value in raw_teams:
            if not isinstance(value, dict):
                continue
            team_id = str(value.get("id") or "").strip()
            if not team_id or team_id in seen:
                continue
            seen.add(team_id)
            teams.append({"id": team_id, "name": str(value.get("name") or "").strip()})
    for value in metadata.get("team_uuids") or []:
        team_id = str(value).strip()
        if team_id and team_id not in seen:
            seen.add(team_id)
            teams.append({"id": team_id, "name": ""})
    return teams
