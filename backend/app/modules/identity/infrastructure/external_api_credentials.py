from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


_AAD = b"enterprise-agent:external-api-credential:v1"


@dataclass(frozen=True)
class EncryptedExternalApiToken:
    ciphertext: str
    key_id: str


class ExternalApiCredentialCipher:
    """Purpose-separated encryption for personal external API tokens."""

    def __init__(self, master_key: str) -> None:
        material = str(master_key or "").strip()
        if not material or material in {"change-me", "<your-master-key>"}:
            raise NonRetryableExecutionError(
                "Master Key is required for external API credentials",
                safe_message="尚未配置外部 API 凭据加密",
                error_code="external_credential_encryption_unavailable",
            )
        self._key = hashlib.sha256(f"external-api-credential:v1:{material}".encode()).digest()
        self.key_id = hashlib.sha256(self._key).hexdigest()[:16]

    def encrypt(self, token: str) -> EncryptedExternalApiToken:
        if not token:
            raise NonRetryableExecutionError(
                "External API token is empty",
                safe_message="外部 API 凭据无效",
                error_code="external_credential_invalid",
            )
        nonce = os.urandom(12)
        encrypted = AESGCM(self._key).encrypt(nonce, token.encode(), _AAD)
        return EncryptedExternalApiToken(
            ciphertext=_encode(nonce + encrypted),
            key_id=self.key_id,
        )

    def decrypt(self, *, ciphertext: str, key_id: str) -> str:
        if key_id != self.key_id:
            raise NonRetryableExecutionError(
                "External API credential key is unavailable",
                safe_message="外部 API 凭据不可用，请重新绑定",
                error_code="external_credential_key_unavailable",
            )
        try:
            raw = _decode(ciphertext)
            return (
                AESGCM(self._key)
                .decrypt(
                    raw[:12],
                    raw[12:],
                    _AAD,
                )
                .decode()
            )
        except Exception as exc:
            raise NonRetryableExecutionError(
                "External API credential decrypt failed",
                safe_message="外部 API 凭据不可用，请重新绑定",
                error_code="external_credential_decrypt_failed",
            ) from exc


class ExternalApiCredentialRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_challenge(
        self,
        *,
        user_id: str,
        connection_revision_id: str,
        external_user_id: str,
        display_name: str,
        encrypted_token: EncryptedExternalApiToken,
        expires_at: str,
        team_ids: list[str] | None = None,
        teams: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        normalized_candidates = _team_candidates(
            teams if teams is not None else [{"id": item, "name": ""} for item in (team_ids or [])]
        )
        normalized_teams = [item["id"] for item in normalized_candidates]
        if not normalized_teams:
            raise NonRetryableExecutionError(
                "ONES account has no available Teams",
                safe_message="该 ONES 账号没有可用 Team",
                error_code="ones_team_missing",
            )
        challenge_id = new_id("external_api_challenge")
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                update external_api_verification_challenge
                   set status = 'EXPIRED'
                 where user_id = ? and provider = 'ones'
                   and status = 'PENDING'
                """,
                (user_id,),
            )
            self.database.execute(
                """
                insert into external_api_verification_challenge
                  (id, user_id, provider, connection_revision_id,
                   external_user_id, display_name, team_ids_json,
                   token_ciphertext, encryption_key_id, expires_at,
                   status, created_at)
                values (?, ?, 'ones', ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    challenge_id,
                    user_id,
                    connection_revision_id,
                    external_user_id,
                    display_name,
                    json.dumps(
                        normalized_candidates,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    encrypted_token.ciphertext,
                    encrypted_token.key_id,
                    expires_at,
                    timestamp,
                ),
            )
        return self.get_challenge_public(challenge_id, user_id=user_id)

    def get_challenge_public(
        self,
        challenge_id: str,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        row = self._challenge(challenge_id, user_id=user_id)
        return {
            "id": row["id"],
            "provider": row["provider"],
            "connection_revision_id": row["connection_revision_id"],
            "external_user_id": row["external_user_id"],
            "display_name": row["display_name"],
            "teams": _json_team_candidates(row["team_ids_json"]),
            "team_ids": [item["id"] for item in _json_team_candidates(row["team_ids_json"])],
            "expires_at": row["expires_at"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    def consume_challenge(
        self,
        challenge_id: str,
        *,
        user_id: str,
        connection_revision_id: str,
        default_team_id: str,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        expired = False
        with self.database.unit_of_work():
            challenge = self._challenge(challenge_id, user_id=user_id)
            if str(challenge["connection_revision_id"]) != connection_revision_id:
                raise self._challenge_invalid()
            if str(challenge["status"]) != "PENDING":
                raise self._challenge_invalid()
            if _parse_time(str(challenge["expires_at"])) <= datetime.now(UTC):
                self.database.execute(
                    """
                    update external_api_verification_challenge
                       set status = 'EXPIRED'
                     where id = ? and status = 'PENDING'
                    """,
                    (challenge_id,),
                )
                expired = True
            candidates = _json_team_candidates(challenge["team_ids_json"])
            teams = [item["id"] for item in candidates]
            if not expired and default_team_id not in teams:
                raise NonRetryableExecutionError(
                    "Default Team is not a verified challenge candidate",
                    safe_message="所选默认 Team 不在本次验证结果中",
                    error_code="ones_team_not_verified",
                )
            consumed = (
                []
                if expired
                else self.database.execute(
                    """
                update external_api_verification_challenge
                   set status = 'CONSUMED', consumed_at = ?
                 where id = ? and user_id = ? and status = 'PENDING'
                returning id
                """,
                    (timestamp, challenge_id, user_id),
                )
            )
            if not expired and not consumed:
                raise self._challenge_invalid()
            current_identity = (
                None
                if expired
                else self.database.execute_one(
                    """
                    select * from user_external_identity
                     where user_id = ? and provider = 'ones'
                       and status in ('enabled', 'disabled')
                     order by revision desc limit 1
                    """,
                    (user_id,),
                )
            )
            changing_subject = bool(
                current_identity
                and str(current_identity["external_subject_id"])
                != str(challenge["external_user_id"])
            )
            if changing_subject and not replace_existing:
                raise NonRetryableExecutionError(
                    "Explicit confirmation is required to replace ONES identity",
                    safe_message="当前用户已绑定其他 ONES 账号，请确认换绑",
                    error_code="ones_rebind_confirmation_required",
                )
            if changing_subject:
                self.database.execute(
                    """
                    update user_external_identity
                       set status = 'unbound', revision = revision + 1,
                           updated_at = ?
                     where user_id = ? and provider = 'ones'
                       and status in ('enabled', 'disabled')
                    """,
                    (timestamp, user_id),
                )
            identity = (
                None
                if expired
                else self._upsert_identity(
                    user_id=user_id,
                    external_user_id=str(challenge["external_user_id"]),
                    display_name=str(challenge["display_name"]),
                    teams=candidates,
                    default_team_id=default_team_id,
                    timestamp=timestamp,
                )
            )
            if not expired:
                self.database.execute(
                    """
                update external_api_credential
                   set status = 'DISABLED', updated_at = ?
                 where user_id = ? and provider = 'ones'
                   and status in ('ACTIVE', 'INVALID')
                """,
                    (timestamp, user_id),
                )
            revision_row = (
                None
                if expired
                else self.database.execute_one(
                    """
                select coalesce(max(revision), 0) + 1 as revision
                  from external_api_credential
                 where user_id = ? and provider = 'ones'
                """,
                    (user_id,),
                )
            )
            credential_id = new_id("external_api_credential")
            if not expired:
                assert identity is not None
                self.database.execute(
                    """
                insert into external_api_credential
                  (id, user_id, external_identity_id, provider,
                   connection_revision_id, token_ciphertext,
                   encryption_key_id, status, revision, last_error_code,
                   verified_at, created_at, updated_at)
                values (?, ?, ?, 'ones', ?, ?, ?, 'ACTIVE', ?, '', ?, ?, ?)
                """,
                    (
                        credential_id,
                        user_id,
                        identity["id"],
                        connection_revision_id,
                        challenge["token_ciphertext"],
                        challenge["encryption_key_id"],
                        int(revision_row["revision"]) if revision_row else 1,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
        if expired:
            raise self._challenge_invalid()
        return self.get_current_public(user_id=user_id)

    def get_current_public(self, *, user_id: str) -> dict[str, Any]:
        row = self._current(user_id=user_id)
        return self._public_credential(row)

    def get_latest_public(self, *, user_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from external_api_credential
             where user_id = ? and provider = 'ones'
             order by revision desc limit 1
            """,
            (user_id,),
        )
        return self._public_credential(row) if row else None

    @staticmethod
    def _public_credential(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "external_identity_id": row["external_identity_id"],
            "provider": row["provider"],
            "connection_revision_id": row["connection_revision_id"],
            "status": row["status"],
            "revision": int(row["revision"]),
            "last_error_code": row["last_error_code"],
            "last_attempt_at": row.get("last_attempt_at"),
            "last_success_at": row.get("last_success_at"),
            "last_error_at": row.get("last_error_at"),
            "verified_at": row["verified_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_current_encrypted(
        self,
        *,
        user_id: str,
    ) -> EncryptedExternalApiToken:
        row = self._current(user_id=user_id)
        if str(row["status"]) != "ACTIVE":
            raise NonRetryableExecutionError(
                "External API credential is not active",
                safe_message="ONES 凭据无效，请重新绑定",
                error_code="external_credential_invalid",
            )
        return EncryptedExternalApiToken(
            ciphertext=str(row["token_ciphertext"]),
            key_id=str(row["encryption_key_id"]),
        )

    def record_usage_attempt(self, *, credential_id: str) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update external_api_credential
               set last_attempt_at = ?, updated_at = ?
             where id = ? and provider = 'ones'
            returning *
            """,
            (now_iso(), now_iso(), credential_id),
        )
        if not rows:
            raise NotFound(
                "External API credential not found",
                safe_message="未找到 ONES 凭据",
            )
        return self._public_credential(rows[0])

    def record_usage_success(self, *, credential_id: str) -> dict[str, Any]:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update external_api_credential
               set last_success_at = ?, updated_at = ?
             where id = ? and provider = 'ones'
            returning *
            """,
            (timestamp, timestamp, credential_id),
        )
        if not rows:
            raise NotFound(
                "External API credential not found",
                safe_message="未找到 ONES 凭据",
            )
        return self._public_credential(rows[0])

    def record_usage_failure(
        self,
        *,
        credential_id: str,
        error_code: str,
        invalidate: bool = False,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update external_api_credential
               set status = case
                     when ? = 1 and status = 'ACTIVE' then 'INVALID'
                     else status
                   end,
                   last_error_code = ?, last_error_at = ?, updated_at = ?
             where id = ? and provider = 'ones'
            returning *
            """,
            (
                1 if invalidate else 0,
                str(error_code or "external_api_failed"),
                timestamp,
                timestamp,
                credential_id,
            ),
        )
        if not rows:
            raise NotFound(
                "External API credential not found",
                safe_message="未找到 ONES 凭据",
            )
        return self._public_credential(rows[0])

    def set_status(
        self,
        *,
        user_id: str,
        status: str,
        error_code: str = "",
    ) -> dict[str, Any]:
        if status not in {"ACTIVE", "INVALID", "DISABLED"}:
            raise ValueError("Unsupported credential status")
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update external_api_credential
               set status = ?, last_error_code = ?,
                   last_error_at = case when ? <> '' then ? else last_error_at end,
                   updated_at = ?
             where user_id = ? and provider = 'ones'
               and status in ('ACTIVE', 'INVALID')
            returning id
            """,
            (status, error_code, error_code, timestamp, timestamp, user_id),
        )
        if not rows:
            raise NotFound(
                "External API credential not found",
                safe_message="未找到 ONES 凭据",
            )
        if status == "DISABLED":
            return {"user_id": user_id, "status": "DISABLED"}
        return self.get_current_public(user_id=user_id)

    def soft_unbind(self, *, user_id: str) -> None:
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                update external_api_credential
                   set status = 'DISABLED', updated_at = ?
                 where user_id = ? and provider = 'ones'
                   and status in ('ACTIVE', 'INVALID')
                """,
                (timestamp, user_id),
            )
            self.database.execute(
                """
                update user_external_identity
                   set status = 'unbound', revision = revision + 1,
                       updated_at = ?
                 where user_id = ? and provider = 'ones'
                   and status != 'unbound'
                """,
                (timestamp, user_id),
            )

    def _upsert_identity(
        self,
        *,
        user_id: str,
        external_user_id: str,
        display_name: str,
        teams: list[dict[str, str]],
        default_team_id: str,
        timestamp: str,
    ) -> dict[str, Any]:
        identity = self.database.execute_one(
            """
            select * from user_external_identity
             where provider = 'ones' and tenant_code = 'ones'
               and external_subject_id = ?
            """,
            (external_user_id,),
        )
        normalized_teams = _team_candidates(teams)
        metadata = json.dumps(
            {
                "default_team_id": default_team_id,
                "team_uuids": [item["id"] for item in normalized_teams],
                "teams": normalized_teams,
                "verification_method": "credentials",
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if identity and str(identity["user_id"]) != user_id:
            raise NonRetryableExecutionError(
                "ONES identity belongs to another user",
                safe_message="该 ONES 账号已绑定其他用户",
                error_code="identity_conflict",
            )
        if identity:
            self.database.execute(
                """
                update user_external_identity
                   set display_name = ?, metadata_json = ?, status = 'enabled',
                       verified_at = ?, revision = revision + 1, updated_at = ?
                 where id = ?
                """,
                (
                    display_name,
                    metadata,
                    timestamp,
                    timestamp,
                    identity["id"],
                ),
            )
            return {"id": str(identity["id"])}
        identity_id = new_id("identity")
        self.database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               connector_id, union_id, open_id, display_name, status,
               verified_at, last_seen_at, metadata_json, revision,
               created_at, updated_at)
            values (?, ?, 'ones', 'ones', ?, '', '', '', ?, 'enabled',
                    ?, null, ?, 1, ?, ?)
            """,
            (
                identity_id,
                user_id,
                external_user_id,
                display_name,
                timestamp,
                metadata,
                timestamp,
                timestamp,
            ),
        )
        return {"id": identity_id}

    def _challenge(
        self,
        challenge_id: str,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select * from external_api_verification_challenge
             where id = ? and user_id = ?
            """,
            (challenge_id, user_id),
        )
        if row is None:
            raise self._challenge_invalid()
        return row

    def _current(self, *, user_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select * from external_api_credential
             where user_id = ? and provider = 'ones'
               and status in ('ACTIVE', 'INVALID')
             order by revision desc limit 1
            """,
            (user_id,),
        )
        if row is None:
            raise NotFound(
                "External API credential not found",
                safe_message="尚未绑定 ONES 凭据",
            )
        return row

    @staticmethod
    def _challenge_invalid() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "External API verification challenge is invalid",
            safe_message="验证已失效，请重新登录 ONES",
            error_code="external_challenge_invalid",
        )


def _unique_non_empty(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return _unique_non_empty([str(item) for item in parsed])


def _json_team_candidates(value: Any) -> list[dict[str, str]]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    if all(isinstance(item, str) for item in parsed):
        return [{"id": item, "name": ""} for item in _unique_non_empty(parsed)]
    return _team_candidates([item for item in parsed if isinstance(item, dict)])


def _team_candidates(values: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        team_id = str(value.get("id") or "").strip()
        if not team_id or team_id in seen:
            continue
        seen.add(team_id)
        result.append(
            {
                "id": team_id,
                "name": str(value.get("name") or "").strip(),
            }
        )
    return result


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode())
