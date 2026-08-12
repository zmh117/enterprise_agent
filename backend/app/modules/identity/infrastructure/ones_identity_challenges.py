from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any, cast

from app.modules.identity.application.ones_identity import VerifiedOnesIdentity
from app.modules.identity.infrastructure.external_identity_credentials import (
    CredentialSecretBundle,
    EncryptedCredentialValue,
    ExternalIdentityCredentialCipher,
)
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


class OnesIdentityChallengeRepository:
    """Short-lived ONES facts with purpose-bound encrypted login evidence."""

    def __init__(
        self,
        database: Database,
        cipher: ExternalIdentityCredentialCipher | None = None,
    ) -> None:
        self.database = database
        self.cipher = cipher

    def create(
        self,
        *,
        user_id: str,
        verified: VerifiedOnesIdentity,
        email: str,
        password: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=max(60, min(ttl_seconds, 1800)))
        ).isoformat()
        challenge_id = new_id("ones_identity_challenge")
        if self.cipher is None:
            raise NonRetryableExecutionError(
                "ONES challenge encryption is unavailable",
                safe_message="ONES 身份验证暂时不可用",
                error_code="ones_credential_encryption_unavailable",
            )
        encrypted_login = self.cipher.encrypt_login_material(
            email=email,
            password=password,
            context="challenge",
            context_id=challenge_id,
        )
        encrypted_token = self.cipher.encrypt(
            verified.token,
            context="challenge",
            context_id=challenge_id,
            purpose="provider-token",
        )
        teams = [{"id": team.id, "name": team.name} for team in verified.teams]
        with self.database.unit_of_work():
            self.database.execute(
                """
                update ones_identity_verification_challenge
                   set status = 'EXPIRED',
                       login_material_ciphertext = null,
                       login_material_nonce = null,
                       token_ciphertext = null,
                       token_nonce = null,
                       credential_key_id = null,
                       credential_algorithm = null
                 where user_id = ? and status = 'PENDING'
                """,
                (user_id,),
            )
            self.database.execute(
                """
                insert into ones_identity_verification_challenge
                  (id, user_id, external_user_id, display_name, teams_json,
                   verified_at, expires_at, status, created_at, consumed_at,
                   login_material_ciphertext, login_material_nonce,
                   token_ciphertext, token_nonce, credential_key_id,
                   credential_algorithm)
                values (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, null, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    user_id,
                    verified.user_uuid,
                    verified.display_name,
                    json.dumps(teams, ensure_ascii=False, sort_keys=True),
                    verified.verified_at,
                    expires_at,
                    timestamp,
                    encrypted_login.ciphertext,
                    encrypted_login.nonce,
                    encrypted_token.ciphertext,
                    encrypted_token.nonce,
                    encrypted_login.key_id,
                    encrypted_login.algorithm,
                ),
            )
        return self.get_public(challenge_id, user_id=user_id)

    def get_public(self, challenge_id: str, *, user_id: str) -> dict[str, Any]:
        row = self._get(challenge_id, user_id=user_id)
        return self._public(row)

    def prepare(
        self,
        challenge_id: str,
        *,
        user_id: str,
        default_team_id: str,
    ) -> CredentialSecretBundle:
        """Validate and decrypt before the binding transaction starts.

        This makes an expired or cryptographically invalid challenge revocable
        in its own committed operation instead of rolling the secret cleanup
        back with a later binding failure.
        """

        row = self._validated_pending(
            challenge_id,
            user_id=user_id,
            default_team_id=default_team_id,
        )
        try:
            return self._decrypt_secrets(row)
        except NonRetryableExecutionError:
            self.invalidate(challenge_id, user_id=user_id)
            raise

    def consume(
        self,
        challenge_id: str,
        *,
        user_id: str,
        default_team_id: str,
        prepared_secrets: CredentialSecretBundle | None = None,
    ) -> tuple[dict[str, Any], CredentialSecretBundle]:
        row = self._validated_pending(
            challenge_id,
            user_id=user_id,
            default_team_id=default_team_id,
        )
        secrets = prepared_secrets or self._decrypt_secrets(row)
        consumed = self.database.execute_one(
            """
            update ones_identity_verification_challenge
               set status = 'CONSUMED', consumed_at = ?,
                   login_material_ciphertext = null,
                   login_material_nonce = null,
                   token_ciphertext = null,
                   token_nonce = null,
                   credential_key_id = null,
                   credential_algorithm = null
             where id = ? and user_id = ? and status = 'PENDING'
            returning *
            """,
            (now_iso(), challenge_id, user_id),
        )
        if consumed is None:
            raise NonRetryableExecutionError(
                "ONES identity challenge was already consumed",
                safe_message="本次 ONES 验证已失效，请重新验证",
                error_code="ones_identity_challenge_invalid",
            )
        return ({**self._public(consumed), "user_id": user_id}, secrets)

    def _validated_pending(
        self,
        challenge_id: str,
        *,
        user_id: str,
        default_team_id: str,
    ) -> dict[str, Any]:
        row = self._get(challenge_id, user_id=user_id)
        if str(row["status"]) != "PENDING":
            raise NonRetryableExecutionError(
                "ONES identity challenge is no longer pending",
                safe_message="本次 ONES 验证已失效，请重新验证",
                error_code="ones_identity_challenge_invalid",
            )
        expires_at = _parse_time(str(row["expires_at"]))
        if expires_at is None or expires_at <= datetime.now(UTC):
            self.database.execute(
                """
                update ones_identity_verification_challenge
                   set status = 'EXPIRED',
                       login_material_ciphertext = null,
                       login_material_nonce = null,
                       token_ciphertext = null,
                       token_nonce = null,
                       credential_key_id = null,
                       credential_algorithm = null
                 where id = ? and status = 'PENDING'
                """,
                (challenge_id,),
            )
            raise NonRetryableExecutionError(
                "ONES identity challenge expired",
                safe_message="本次 ONES 验证已过期，请重新验证",
                error_code="ones_identity_challenge_expired",
            )
        teams = _teams(row.get("teams_json"))
        normalized_default = default_team_id.strip()
        if normalized_default not in {team["id"] for team in teams}:
            raise NonRetryableExecutionError(
                "Default ONES team is not part of the verified challenge",
                safe_message="默认 Team 不属于本次已验证候选",
                error_code="ones_default_team_invalid",
            )
        return row

    def invalidate(self, challenge_id: str, *, user_id: str) -> None:
        self.database.execute(
            """
            update ones_identity_verification_challenge
               set status = 'EXPIRED',
                   login_material_ciphertext = null,
                   login_material_nonce = null,
                   token_ciphertext = null,
                   token_nonce = null,
                   credential_key_id = null,
                   credential_algorithm = null
             where id = ? and user_id = ? and status = 'PENDING'
            """,
            (challenge_id, user_id),
        )

    def _decrypt_secrets(self, row: dict[str, Any]) -> CredentialSecretBundle:
        if self.cipher is None:
            raise NonRetryableExecutionError(
                "ONES challenge encryption is unavailable",
                safe_message="ONES 身份验证暂时不可用",
                error_code="ones_credential_encryption_unavailable",
            )
        encrypted_login = self._encrypted(row, prefix="login_material")
        encrypted_token = self._encrypted(row, prefix="token")
        email, password = self.cipher.decrypt_login_material(
            encrypted_login,
            context="challenge",
            context_id=str(row["id"]),
        )
        token = self.cipher.decrypt(
            encrypted_token,
            context="challenge",
            context_id=str(row["id"]),
            purpose="provider-token",
        )
        return CredentialSecretBundle(email=email, password=password, token=token)

    @staticmethod
    def _encrypted(row: dict[str, Any], *, prefix: str) -> EncryptedCredentialValue:
        ciphertext = row.get(f"{prefix}_ciphertext")
        nonce = row.get(f"{prefix}_nonce")
        key_id = row.get("credential_key_id")
        algorithm = row.get("credential_algorithm")
        values = (ciphertext, nonce, key_id, algorithm)
        if not all(isinstance(value, str) and value for value in values):
            raise NonRetryableExecutionError(
                "ONES challenge secret evidence is incomplete",
                safe_message="本次 ONES 验证已失效，请重新验证",
                error_code="ones_identity_challenge_invalid",
            )
        return EncryptedCredentialValue(
            ciphertext=cast(str, ciphertext),
            nonce=cast(str, nonce),
            key_id=cast(str, key_id),
            algorithm=cast(str, algorithm),
        )

    def _get(self, challenge_id: str, *, user_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select * from ones_identity_verification_challenge
             where id = ? and user_id = ?
            """,
            (challenge_id, user_id),
        )
        if row is None:
            raise NotFound(
                "ONES identity challenge not found",
                safe_message="本次 ONES 验证不存在或已失效",
                error_code="ones_identity_challenge_not_found",
            )
        return row

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        teams = _teams(row.get("teams_json"))
        return {
            "id": str(row["id"]),
            "provider": "ones",
            "external_user_id": str(row["external_user_id"]),
            "display_name": str(row.get("display_name") or ""),
            "teams": teams,
            "team_ids": [team["id"] for team in teams],
            "verified_at": str(row["verified_at"]),
            "expires_at": str(row["expires_at"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
        }


def _teams(raw: object) -> list[dict[str, str]]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        parsed = []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in parsed if isinstance(parsed, list) else []:
        if not isinstance(value, dict):
            continue
        team_id = str(value.get("id") or "").strip()
        if not team_id or team_id in seen:
            continue
        seen.add(team_id)
        result.append({"id": team_id, "name": str(value.get("name") or "").strip()})
    return result


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
