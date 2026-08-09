from __future__ import annotations

import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import (
    DingTalkBindingChallengeRepository,
    IdentityRepository,
    OnesProviderAuthenticator,
    ProviderCredentialCipher,
    ProviderCredentialRepository,
    ProviderInstanceRepository,
)
from app.shared.exceptions import NonRetryableExecutionError


_DINGTALK_CODE = re.compile(r"^EA-BIND-[A-Za-z0-9_-]{20,64}$")


class ExternalCredentialBindingService:
    """Self-service identity and personal ONES credential boundary."""

    def __init__(
        self,
        *,
        identity_repository: IdentityRepository,
        credential_repository: ProviderCredentialRepository,
        provider_instances: ProviderInstanceRepository,
        credential_cipher: ProviderCredentialCipher | None,
        authenticator: OnesProviderAuthenticator,
        audit_service: AuditService,
        authorization: AuthorizationEvaluator,
        provider_instance_code: str,
        dingtalk_challenges: DingTalkBindingChallengeRepository,
        challenge_ttl_seconds: int = 600,
        dingtalk_challenge_ttl_seconds: int = 600,
    ) -> None:
        self.identity_repository = identity_repository
        self.credential_repository = credential_repository
        self.provider_instances = provider_instances
        self.credential_cipher = credential_cipher
        self.authenticator = authenticator
        self.audit_service = audit_service
        self.authorization = authorization
        self.provider_instance_code = provider_instance_code
        self.dingtalk_challenges = dingtalk_challenges
        self.challenge_ttl_seconds = max(60, min(challenge_ttl_seconds, 1800))
        self.dingtalk_challenge_ttl_seconds = max(60, min(dingtalk_challenge_ttl_seconds, 1800))

    def self_status(self, *, actor_id: str) -> dict[str, Any]:
        overview = self.self_overview(actor_id=actor_id)
        return {"user": overview["user"], "ones": overview["ones"]}

    def self_overview(self, *, actor_id: str) -> dict[str, Any]:
        user = self._require_self_user(actor_id)
        identities, credential = self._current_binding_snapshot(actor_id)
        ones_identity = next(
            (identity for identity in identities if identity["provider"] == "ones"),
            None,
        )
        return {
            "user": {"id": user["id"], "display_name": user["display_name"]},
            "dingtalk": [
                self._self_dingtalk_identity(identity)
                for identity in identities
                if identity["provider"] == "dingtalk" and identity["status"] != "unbound"
            ],
            "ones": self._self_ones_identity(ones_identity, credential),
        }

    def begin_self_binding(
        self,
        *,
        actor_id: str,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        self._require_self_user(actor_id)
        cipher = self._require_cipher()
        provider = self.provider_instances.get_by_code(
            self.provider_instance_code,
            require_active=True,
        )
        try:
            subject = self.authenticator.authenticate(
                provider_instance=provider,
                email=email,
                password=password,
            )
        except Exception as exc:
            self.audit_service.record(
                "provider_credential.self_verification",
                status="FAILED",
                summary="ONES self verification failed",
                actor_id=actor_id,
                payload={
                    "user_id": actor_id,
                    "provider_instance_id": provider["id"],
                    "result": "failed",
                    "error_code": str(getattr(exc, "error_code", "") or "ones_verification_failed"),
                },
            )
            raise
        finally:
            password = ""
        encrypted = cipher.encrypt(subject.token)
        challenge = self.credential_repository.create_challenge(
            user_id=actor_id,
            provider_instance_id=str(provider["id"]),
            external_user_id=subject.external_user_id,
            display_name=subject.display_name,
            teams=[dict(team) for team in subject.teams],
            encrypted_token=encrypted,
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=self.challenge_ttl_seconds)
            ).isoformat(),
        )
        self.audit_service.record(
            "provider_credential.self_verification",
            status="SUCCEEDED",
            summary="ONES self verification challenge created",
            actor_id=actor_id,
            payload={
                "user_id": actor_id,
                "challenge_id": challenge["id"],
                "provider_instance_id": provider["id"],
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
        default_team_id: str,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        self._require_self_user(actor_id)
        provider = self.provider_instances.get_by_code(
            self.provider_instance_code,
            require_active=True,
        )
        credential: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                credential = self.credential_repository.consume_challenge(
                    challenge_id,
                    user_id=actor_id,
                    provider_instance_id=str(provider["id"]),
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
        self.audit_service.record(
            "provider_credential.bound",
            status="SUCCEEDED",
            summary="ONES identity and personal credential bound",
            actor_id=actor_id,
            payload={
                "user_id": actor_id,
                "identity_id": credential["external_identity_id"],
                "credential_revision": credential["revision"],
                "provider_instance_id": provider["id"],
                "default_team_id": default_team_id,
                "result": "succeeded",
            },
        )
        return self.self_status(actor_id=actor_id)

    def change_default_team(
        self,
        *,
        actor_id: str,
        default_team_id: str,
        expected_identity_revision: int,
    ) -> dict[str, Any]:
        self._require_self_user(actor_id)
        provider = self.provider_instances.get_by_code(
            self.provider_instance_code,
            require_active=True,
        )
        self.credential_repository.change_default_team(
            user_id=actor_id,
            provider_instance_id=str(provider["id"]),
            default_team_id=default_team_id,
            expected_identity_revision=expected_identity_revision,
        )
        self.audit_service.record(
            "provider_credential.default_team_changed",
            status="SUCCEEDED",
            summary="Default ONES Team changed",
            actor_id=actor_id,
            payload={
                "user_id": actor_id,
                "provider_instance_id": provider["id"],
                "default_team_id": default_team_id,
            },
        )
        return self.self_status(actor_id=actor_id)

    def begin_dingtalk_binding(self, *, actor_id: str) -> dict[str, str]:
        self._require_self_user(actor_id)
        challenge = self.dingtalk_challenges.create(
            user_id=actor_id,
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=self.dingtalk_challenge_ttl_seconds)
            ).isoformat(),
        )
        self.audit_service.record(
            "dingtalk_identity.self_challenge_created",
            status="SUCCEEDED",
            summary="DingTalk self-binding challenge created",
            actor_id=actor_id,
            payload={"user_id": actor_id, "challenge_id": challenge["id"]},
        )
        return challenge

    def consume_dingtalk_message(
        self,
        *,
        content: str,
        dingtalk_enterprise_id: str,
        external_subject_id: str,
        display_name: str,
        connector_id: str,
        trusted_event_id: str,
        occurred_at: str,
    ) -> dict[str, Any] | None:
        code = content.strip()
        if not _DINGTALK_CODE.fullmatch(code):
            return None
        result = self.dingtalk_challenges.consume_trusted_event(
            code=code,
            dingtalk_enterprise_id=dingtalk_enterprise_id,
            external_subject_id=external_subject_id,
            display_name=display_name,
            connector_id=connector_id,
            trusted_event_id=trusted_event_id,
            occurred_at=occurred_at,
        )
        self.audit_service.record(
            "dingtalk_identity.self_bound",
            status="SUCCEEDED",
            summary="DingTalk identity self-bound from trusted event",
            actor_id=str(result["user_id"]),
            payload={
                "user_id": result["user_id"],
                "identity_id": result["identity_id"],
                "connector_id": connector_id,
                "trusted_event_id": trusted_event_id,
            },
        )
        return result

    def self_unbind(self, *, actor_id: str) -> None:
        self._require_self_user(actor_id)
        provider = self.provider_instances.get_by_code(self.provider_instance_code)
        self.credential_repository.soft_unbind(
            user_id=actor_id,
            provider_instance_id=str(provider["id"]),
        )
        self.audit_service.record(
            "provider_credential.self_unbound",
            status="SUCCEEDED",
            summary="User unbound own ONES identity and credential",
            actor_id=actor_id,
            payload={"user_id": actor_id, "result": "succeeded"},
        )

    def admin_overview(self, *, user_id: str) -> dict[str, Any]:
        self.identity_repository.get_user(user_id)
        identities = self.identity_repository.list_external_identities(user_id)
        latest = self.credential_repository.get_latest_public(user_id=user_id)
        current: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []
        for identity in identities:
            projected = (
                self._admin_dingtalk_identity(identity)
                if identity["provider"] == "dingtalk"
                else self._admin_ones_identity_summary(
                    identity,
                    latest
                    if latest and str(latest["external_identity_id"]) == str(identity["id"])
                    else None,
                )
            )
            (history if identity["status"] == "unbound" else current).append(projected)
        return {"user_id": user_id, "current": current, "history": history}

    def admin_status(self, *, actor_id: str, user_id: str) -> dict[str, Any]:
        self._require_admin(actor_id, "read", user_id)
        identities, credential = self._current_binding_snapshot(user_id)
        identity = next(
            (item for item in identities if item["provider"] == "ones"),
            None,
        )
        return {
            "user_id": user_id,
            "ones": self._admin_ones_technical(identity, credential),
        }

    def admin_disable(self, *, actor_id: str, user_id: str) -> dict[str, Any]:
        self._require_admin(actor_id, "disable", user_id)
        self.credential_repository.set_status(
            user_id=user_id,
            status="DISABLED",
            error_code="disabled_by_admin",
        )
        self.audit_service.record(
            "provider_credential.disabled",
            status="SUCCEEDED",
            summary="Personal ONES credential disabled by administrator",
            actor_id=actor_id,
            payload={"actor_id": actor_id, "user_id": user_id},
        )
        return self.admin_status(actor_id=actor_id, user_id=user_id)

    def admin_unbind(self, *, actor_id: str, user_id: str) -> None:
        self._require_admin(actor_id, "unbind", user_id)
        self.credential_repository.soft_unbind(user_id=user_id)
        self.audit_service.record(
            "provider_credential.unbound",
            status="SUCCEEDED",
            summary="ONES identity and credential unbound",
            actor_id=actor_id,
            payload={"actor_id": actor_id, "user_id": user_id},
        )

    def apply_http_status(self, *, user_id: str, status: int) -> None:
        if status == 401:
            self.credential_repository.set_status(
                user_id=user_id,
                status="INVALID",
                error_code="ones_unauthorized",
            )
        elif status == 403:
            self.credential_repository.get_current_public(user_id=user_id)

    def _require_self_user(self, actor_id: str) -> dict[str, Any]:
        user = self.identity_repository.get_user(actor_id)
        if str(user["status"]) != "enabled" or str(user.get("account_type") or "human") != "human":
            raise NonRetryableExecutionError(
                "Current user cannot bind external credentials",
                safe_message="当前账号不能绑定 ONES",
                error_code="provider_credential_self_manage_forbidden",
            )
        return user

    def _current_binding_snapshot(
        self, user_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        identities = self.identity_repository.list_external_identities(user_id)
        current = [
            item
            for item in identities
            if item["status"] in {"enabled", "disabled", "REVERIFICATION_REQUIRED"}
        ]
        ones = [item for item in current if item["provider"] == "ones"]
        if len(ones) > 1:
            raise self._identity_state_inconsistent()
        credential = self.credential_repository.get_latest_public(user_id=user_id)
        if not ones:
            if credential and credential["status"] in {"ACTIVE", "INVALID"}:
                raise self._identity_state_inconsistent()
            credential = None
        elif credential and str(credential["external_identity_id"]) != str(ones[0]["id"]):
            raise self._identity_state_inconsistent()
        return identities, credential

    def _self_dingtalk_identity(self, identity: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": "dingtalk",
            "nickname": str(identity.get("display_name") or ""),
            "status": str(identity["status"]),
            "enterprise": self._dingtalk_enterprise(identity),
            "last_used_at": identity.get("last_seen_at"),
            "staff_id": str(identity["external_subject_id"]),
        }

    def _admin_dingtalk_identity(self, identity: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._self_dingtalk_identity(identity),
            "identity_id": str(identity["id"]),
            "revision": int(identity["revision"]),
            "binding_confirmed_at": identity.get("verified_at"),
            "observations": [
                {
                    "application_name": str(item["application_name"]),
                    "first_observed_at": item.get("first_observed_at"),
                    "last_observed_at": item.get("last_observed_at"),
                }
                for item in self.identity_repository.list_dingtalk_application_observations(
                    str(identity["id"])
                )
            ],
        }

    def _dingtalk_enterprise(self, identity: dict[str, Any]) -> dict[str, str] | None:
        enterprise_id = str(identity.get("dingtalk_enterprise_id") or "")
        if not enterprise_id:
            return None
        row = self.identity_repository.database.execute_one(
            "select name, corp_id from dingtalk_enterprise where id = ?",
            (enterprise_id,),
        )
        return (
            {"name": str(row.get("name") or ""), "corp_id": str(row.get("corp_id") or "")}
            if row
            else None
        )

    @staticmethod
    def _team_summaries(identity: dict[str, Any]) -> list[dict[str, str]]:
        teams = (identity.get("metadata") or {}).get("teams") or []
        return [
            {"id": str(team.get("id") or ""), "name": str(team.get("name") or "")}
            for team in teams
            if isinstance(team, dict) and str(team.get("id") or "")
        ]

    @classmethod
    def _default_team(cls, identity: dict[str, Any]) -> dict[str, str] | None:
        default_id = str((identity.get("metadata") or {}).get("default_team_id") or "")
        if not default_id:
            return None
        return next(
            (team for team in cls._team_summaries(identity) if team["id"] == default_id),
            {"id": default_id, "name": ""},
        )

    @staticmethod
    def _ones_availability(
        identity: dict[str, Any] | None,
        credential: dict[str, Any] | None,
    ) -> str:
        if identity is None or str(identity.get("status") or "") == "unbound":
            return "UNBOUND"
        if (
            str(identity.get("status") or "") == "disabled"
            or str((credential or {}).get("status") or "") == "DISABLED"
        ):
            return "ADMIN_DISABLED"
        if (
            str(identity.get("status") or "") == "enabled"
            and credential
            and str(credential.get("status") or "") == "ACTIVE"
        ):
            return "AVAILABLE"
        return "REVERIFY_REQUIRED"

    @classmethod
    def _self_ones_identity(
        cls,
        identity: dict[str, Any] | None,
        credential: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if identity is None:
            return None
        return {
            "provider": "ones",
            "user_name": str(identity.get("display_name") or "ONES 未返回用户名称"),
            "availability": cls._ones_availability(identity, credential),
            "default_team": cls._default_team(identity),
            "verified_at": (credential or {}).get("verified_at") or identity.get("verified_at"),
            "last_success_at": (credential or {}).get("last_success_at"),
            "user_id": str(identity["external_subject_id"]),
            "teams": cls._team_summaries(identity),
            "identity_revision": int(identity["revision"]),
        }

    @classmethod
    def _admin_ones_identity_summary(
        cls,
        identity: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            **(cls._self_ones_identity(identity, credential) or {}),
            "identity_id": str(identity["id"]),
            "identity_status": str(identity["status"]),
            "identity_revision": int(identity["revision"]),
        }

    def _admin_ones_technical(
        self,
        identity: dict[str, Any] | None,
        credential: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if identity is None:
            return None
        summary = self._admin_ones_identity_summary(identity, credential)
        if credential is None:
            return {**summary, "credential": None, "provider_instance": None}
        provider = self.provider_instances.get(str(credential["provider_instance_id"]))
        return {
            **summary,
            "credential": {
                "status": str(credential["status"]),
                "revision": int(credential["revision"]),
                "last_attempt_at": credential.get("last_attempt_at"),
                "last_success_at": credential.get("last_success_at"),
                "last_error_code": str(credential.get("last_error_code") or ""),
                "last_error_at": credential.get("last_error_at"),
            },
            "provider_instance": {
                "code": str(provider["code"]),
                "name": str(provider["display_name"]),
                "revision": int(provider["revision"]),
                "status": str(provider["status"]),
            },
        }

    def _require_admin(self, actor_id: str, action: str, user_id: str) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="external_credential",
            resource_code=user_id,
            action=action,
        )

    def _require_cipher(self) -> ProviderCredentialCipher:
        if self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "Provider credential encryption is unavailable",
                safe_message="尚未配置个人凭据加密",
                error_code="provider_credential_encryption_unavailable",
            )
        return self.credential_cipher

    @staticmethod
    def _identity_state_inconsistent() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "External identity and credential state are inconsistent",
            safe_message="ONES 身份与个人凭据状态不一致，请重新验证或联系管理员",
            error_code="external_identity_state_inconsistent",
        )
