from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


_AAD = b"enterprise-agent:provider-credential:v1"


@dataclass(frozen=True, slots=True)
class EncryptedProviderToken:
    ciphertext: str
    key_id: str


class ProviderCredentialCipher:
    """Purpose-separated encryption for personal provider tokens."""

    def __init__(self, master_key: str) -> None:
        material = str(master_key or "").strip()
        if not material or material in {"change-me", "<your-master-key>"}:
            raise NonRetryableExecutionError(
                "Master Key is required for provider credentials",
                safe_message="尚未配置个人凭据加密",
                error_code="provider_credential_encryption_unavailable",
            )
        self._key = hashlib.sha256(f"provider-credential:v1:{material}".encode()).digest()
        self.key_id = hashlib.sha256(self._key).hexdigest()[:16]

    def encrypt(self, token: str) -> EncryptedProviderToken:
        if not token:
            raise NonRetryableExecutionError(
                "Provider token is empty",
                safe_message="ONES 凭据无效",
                error_code="provider_credential_invalid",
            )
        nonce = os.urandom(12)
        encrypted = AESGCM(self._key).encrypt(nonce, token.encode(), _AAD)
        return EncryptedProviderToken(
            ciphertext=_encode(nonce + encrypted),
            key_id=self.key_id,
        )

    def decrypt(self, *, ciphertext: str, key_id: str) -> str:
        if key_id != self.key_id:
            raise NonRetryableExecutionError(
                "Provider credential key is unavailable",
                safe_message="ONES 凭据不可用，请重新验证",
                error_code="provider_credential_key_unavailable",
            )
        try:
            raw = _decode(ciphertext)
            return AESGCM(self._key).decrypt(raw[:12], raw[12:], _AAD).decode()
        except Exception as exc:
            raise NonRetryableExecutionError(
                "Provider credential decrypt failed",
                safe_message="ONES 凭据不可用，请重新验证",
                error_code="provider_credential_decrypt_failed",
            ) from exc


class ProviderInstanceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def ensure_trusted_ones(
        self,
        *,
        code: str,
        display_name: str,
        base_url: str,
        allowed_hosts: tuple[str, ...],
    ) -> dict[str, Any]:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("Provider instance code is required")
        hosts = sorted({value.strip().lower() for value in allowed_hosts if value.strip()})
        timestamp = now_iso()
        status = "ACTIVE" if base_url.strip() and hosts else "DISABLED"
        hosts_json = json.dumps(hosts, separators=(",", ":"))
        with self.database.unit_of_work():
            current = self.database.execute_one(
                "select * from provider_instance where code = ?",
                (normalized_code,),
            )
            if current is None:
                self.database.execute(
                    """
                    insert into provider_instance
                      (id, code, provider, display_name, base_url,
                       allowed_hosts_json, status, revision, created_at, updated_at)
                    values (?, ?, 'ones', ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        new_id("provider_instance"),
                        normalized_code,
                        display_name.strip() or "ONES",
                        base_url.strip(),
                        hosts_json,
                        status,
                        timestamp,
                        timestamp,
                    ),
                )
            elif any(
                (
                    str(current["display_name"]) != (display_name.strip() or "ONES"),
                    str(current["base_url"]) != base_url.strip(),
                    str(current["allowed_hosts_json"]) != hosts_json,
                    str(current["status"]) != status,
                )
            ):
                self.database.execute(
                    """
                    update provider_instance
                       set display_name = ?, base_url = ?, allowed_hosts_json = ?,
                           status = ?, revision = revision + 1, updated_at = ?
                     where id = ?
                    """,
                    (
                        display_name.strip() or "ONES",
                        base_url.strip(),
                        hosts_json,
                        status,
                        timestamp,
                        current["id"],
                    ),
                )
        return self.get_by_code(normalized_code)

    def get(self, instance_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from provider_instance where id = ?",
            (instance_id,),
        )
        if row is None:
            raise NotFound("Provider instance not found", safe_message="ONES 实例不存在")
        return self._project(row)

    def get_by_code(self, code: str, *, require_active: bool = False) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from provider_instance where code = ? and provider = 'ones'",
            (code,),
        )
        if row is None:
            raise NotFound("Provider instance not found", safe_message="ONES 实例不存在")
        if require_active and str(row["status"]) != "ACTIVE":
            raise NonRetryableExecutionError(
                "Provider instance is unavailable",
                safe_message="ONES 身份验证不可用",
                error_code="provider_instance_unavailable",
            )
        return self._project(row)

    @staticmethod
    def _project(row: dict[str, Any]) -> dict[str, Any]:
        try:
            hosts = json.loads(str(row.get("allowed_hosts_json") or "[]"))
        except json.JSONDecodeError:
            hosts = []
        return {
            **row,
            "allowed_hosts": tuple(
                str(value) for value in hosts if isinstance(value, str) and value
            ),
        }


class ProviderCredentialRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_challenge(
        self,
        *,
        user_id: str,
        provider_instance_id: str,
        external_user_id: str,
        display_name: str,
        teams: list[dict[str, str]],
        encrypted_token: EncryptedProviderToken,
        expires_at: str,
    ) -> dict[str, Any]:
        normalized_teams = _team_candidates(teams)
        if not normalized_teams:
            raise NonRetryableExecutionError(
                "ONES account has no available Teams",
                safe_message="该 ONES 账号没有可用 Team",
                error_code="ones_team_missing",
            )
        challenge_id = new_id("provider_challenge")
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                update provider_verification_challenge
                   set status = 'EXPIRED', token_ciphertext = '', encryption_key_id = ''
                 where user_id = ? and provider_instance_id = ?
                   and status = 'PENDING'
                """,
                (user_id, provider_instance_id),
            )
            self.database.execute(
                """
                insert into provider_verification_challenge
                  (id, user_id, provider_instance_id, external_user_id,
                   display_name, teams_json, token_ciphertext, encryption_key_id,
                   expires_at, status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    challenge_id,
                    user_id,
                    provider_instance_id,
                    external_user_id,
                    display_name,
                    json.dumps(
                        normalized_teams,
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

    def get_challenge_public(self, challenge_id: str, *, user_id: str) -> dict[str, Any]:
        row = self._challenge(challenge_id, user_id=user_id)
        teams = _json_team_candidates(row["teams_json"])
        return {
            "id": row["id"],
            "provider_instance_id": row["provider_instance_id"],
            "external_user_id": row["external_user_id"],
            "display_name": row["display_name"],
            "teams": teams,
            "team_ids": [item["id"] for item in teams],
            "expires_at": row["expires_at"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    def consume_challenge(
        self,
        challenge_id: str,
        *,
        user_id: str,
        provider_instance_id: str,
        default_team_id: str,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.database.unit_of_work():
            challenge = self._challenge(challenge_id, user_id=user_id)
            if (
                str(challenge["provider_instance_id"]) != provider_instance_id
                or str(challenge["status"]) != "PENDING"
            ):
                raise self._challenge_invalid()
            if _parse_time(str(challenge["expires_at"])) <= datetime.now(UTC):
                self.database.execute(
                    """
                    update provider_verification_challenge
                       set status = 'EXPIRED', token_ciphertext = '', encryption_key_id = ''
                     where id = ? and status = 'PENDING'
                    """,
                    (challenge_id,),
                )
                raise self._challenge_invalid()
            teams = _json_team_candidates(challenge["teams_json"])
            if default_team_id not in {item["id"] for item in teams}:
                raise NonRetryableExecutionError(
                    "Default Team is not a verified challenge candidate",
                    safe_message="所选默认 Team 不在本次验证结果中",
                    error_code="ones_team_not_verified",
                )
            provider = self.database.execute_one(
                "select * from provider_instance where id = ? and status = 'ACTIVE'",
                (provider_instance_id,),
            )
            if provider is None:
                raise NonRetryableExecutionError(
                    "Provider instance is unavailable",
                    safe_message="ONES 身份验证不可用",
                    error_code="provider_instance_unavailable",
                )
            identity = self._bind_identity(
                user_id=user_id,
                provider_instance=provider,
                external_user_id=str(challenge["external_user_id"]),
                display_name=str(challenge["display_name"]),
                teams=teams,
                default_team_id=default_team_id,
                replace_existing=replace_existing,
                timestamp=timestamp,
            )
            self.database.execute(
                """
                update provider_credential
                   set status = 'DISABLED', updated_at = ?
                 where user_id = ? and provider_instance_id = ?
                   and status in ('ACTIVE', 'INVALID')
                """,
                (timestamp, user_id, provider_instance_id),
            )
            revision_row = self.database.execute_one(
                """
                select coalesce(max(revision), 0) + 1 as revision
                  from provider_credential
                 where user_id = ? and provider_instance_id = ?
                """,
                (user_id, provider_instance_id),
            )
            credential_id = new_id("provider_credential")
            self.database.execute(
                """
                insert into provider_credential
                  (id, user_id, external_identity_id, provider_instance_id,
                   token_ciphertext, encryption_key_id, status, revision,
                   last_error_code, verified_at, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, '', ?, ?, ?)
                """,
                (
                    credential_id,
                    user_id,
                    identity["id"],
                    provider_instance_id,
                    challenge["token_ciphertext"],
                    challenge["encryption_key_id"],
                    int(revision_row["revision"]) if revision_row else 1,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            consumed = self.database.execute(
                """
                update provider_verification_challenge
                   set status = 'CONSUMED', consumed_at = ?,
                       token_ciphertext = '', encryption_key_id = ''
                 where id = ? and user_id = ? and status = 'PENDING'
                returning id
                """,
                (timestamp, challenge_id, user_id),
            )
            if not consumed:
                raise self._challenge_invalid()
        return self.get_current_public(
            user_id=user_id,
            provider_instance_id=provider_instance_id,
        )

    def get_current_public(
        self, *, user_id: str, provider_instance_id: str | None = None
    ) -> dict[str, Any]:
        return self._public_credential(
            self._current(user_id=user_id, provider_instance_id=provider_instance_id)
        )

    def get_latest_public(
        self, *, user_id: str, provider_instance_id: str | None = None
    ) -> dict[str, Any] | None:
        clause = "and provider_instance_id = ?" if provider_instance_id else ""
        params: tuple[Any, ...] = (
            (user_id, provider_instance_id) if provider_instance_id else (user_id,)
        )
        row = self.database.execute_one(
            f"""
            select * from provider_credential
             where user_id = ? {clause}
             order by revision desc limit 1
            """,
            params,
        )
        return self._public_credential(row) if row else None

    def get_current_encrypted(
        self, *, user_id: str, provider_instance_id: str | None = None
    ) -> EncryptedProviderToken:
        row = self._current(
            user_id=user_id,
            provider_instance_id=provider_instance_id,
        )
        if str(row["status"]) != "ACTIVE":
            raise NonRetryableExecutionError(
                "Provider credential is not active",
                safe_message="ONES 凭据无效，请重新验证",
                error_code="provider_credential_invalid",
            )
        return EncryptedProviderToken(
            ciphertext=str(row["token_ciphertext"]),
            key_id=str(row["encryption_key_id"]),
        )

    def record_usage_attempt(self, *, credential_id: str) -> dict[str, Any]:
        timestamp = now_iso()
        return self._update_usage(
            credential_id,
            "last_attempt_at = ?, updated_at = ?",
            (timestamp, timestamp),
        )

    def record_usage_success(self, *, credential_id: str) -> dict[str, Any]:
        timestamp = now_iso()
        return self._update_usage(
            credential_id,
            "last_success_at = ?, last_error_code = '', updated_at = ?",
            (timestamp, timestamp),
        )

    def record_usage_failure(
        self,
        *,
        credential_id: str,
        error_code: str,
        invalidate: bool = False,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        return self._update_usage(
            credential_id,
            """
            status = case when ? = 1 and status = 'ACTIVE' then 'INVALID' else status end,
            last_error_code = ?, last_error_at = ?, updated_at = ?
            """,
            (1 if invalidate else 0, error_code, timestamp, timestamp),
        )

    def set_status(
        self,
        *,
        user_id: str,
        status: str,
        error_code: str = "",
        provider_instance_id: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"ACTIVE", "INVALID", "DISABLED"}:
            raise ValueError("Unsupported credential status")
        current = self._current(
            user_id=user_id,
            provider_instance_id=provider_instance_id,
        )
        timestamp = now_iso()
        self.database.execute(
            """
            update provider_credential
               set status = ?, last_error_code = ?,
                   last_error_at = case when ? <> '' then ? else last_error_at end,
                   updated_at = ?
             where id = ?
            """,
            (status, error_code, error_code, timestamp, timestamp, current["id"]),
        )
        return self._public_credential(
            self.database.execute_one(
                "select * from provider_credential where id = ?",
                (current["id"],),
            )
        )

    def change_default_team(
        self,
        *,
        user_id: str,
        provider_instance_id: str,
        default_team_id: str,
        expected_identity_revision: int,
    ) -> dict[str, Any]:
        credential = self._current(
            user_id=user_id,
            provider_instance_id=provider_instance_id,
        )
        identity = self.database.execute_one(
            "select * from user_external_identity where id = ?",
            (credential["external_identity_id"],),
        )
        if identity is None or int(identity["revision"]) != expected_identity_revision:
            raise NonRetryableExecutionError(
                "Identity revision conflict",
                safe_message="身份信息已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        metadata = _json_object(identity.get("metadata_json"))
        teams = _team_candidates(
            [value for value in metadata.get("teams", []) if isinstance(value, dict)]
        )
        if default_team_id not in {item["id"] for item in teams}:
            raise NonRetryableExecutionError(
                "Default Team is not verified",
                safe_message="默认 Team 不在已验证集合中",
                error_code="ones_team_not_verified",
            )
        metadata["default_team_id"] = default_team_id
        rows = self.database.execute(
            """
            update user_external_identity
               set metadata_json = ?, revision = revision + 1,
                   binding_revision = binding_revision + 1, updated_at = ?
             where id = ? and revision = ?
            returning id
            """,
            (
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                now_iso(),
                identity["id"],
                expected_identity_revision,
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Identity revision conflict",
                safe_message="身份信息已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return {"id": identity["id"], "default_team_id": default_team_id}

    def soft_unbind(self, *, user_id: str, provider_instance_id: str | None = None) -> None:
        current = self._current(
            user_id=user_id,
            provider_instance_id=provider_instance_id,
        )
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                "update provider_credential set status = 'DISABLED', updated_at = ? where id = ?",
                (timestamp, current["id"]),
            )
            self.database.execute(
                """
                update user_external_identity
                   set status = 'unbound', revision = revision + 1,
                       binding_revision = binding_revision + 1, updated_at = ?
                 where id = ? and status != 'unbound'
                """,
                (timestamp, current["external_identity_id"]),
            )

    def _bind_identity(
        self,
        *,
        user_id: str,
        provider_instance: dict[str, Any],
        external_user_id: str,
        display_name: str,
        teams: list[dict[str, str]],
        default_team_id: str,
        replace_existing: bool,
        timestamp: str,
    ) -> dict[str, Any]:
        provider_instance_id = str(provider_instance["id"])
        provider_code = str(provider_instance["code"])
        exact = self.database.execute_one(
            """
            select * from user_external_identity
             where provider = 'ones' and external_subject_id = ?
               and (provider_instance_id = ? or
                    (provider_instance_id is null and tenant_code = ?))
            """,
            (external_user_id, provider_instance_id, provider_code),
        )
        if exact is not None and str(exact["user_id"]) != user_id:
            raise NonRetryableExecutionError(
                "ONES identity belongs to another user",
                safe_message="该 ONES 账号已绑定其他用户",
                error_code="identity_conflict",
            )
        current = self.database.execute_one(
            """
            select * from user_external_identity
             where provider = 'ones' and user_id = ?
               and (provider_instance_id = ? or
                    (provider_instance_id is null and tenant_code = ?))
               and status in ('enabled', 'disabled', 'REVERIFICATION_REQUIRED')
             order by revision desc limit 1
            """,
            (user_id, provider_instance_id, provider_code),
        )
        changing_subject = bool(current and str(current["external_subject_id"]) != external_user_id)
        if changing_subject and not replace_existing:
            raise NonRetryableExecutionError(
                "Explicit confirmation is required to replace ONES identity",
                safe_message="当前用户已绑定其他 ONES 账号，请确认换绑",
                error_code="ones_rebind_confirmation_required",
            )
        if changing_subject and current:
            self.database.execute(
                """
                update user_external_identity
                   set status = 'unbound', revision = revision + 1, updated_at = ?
                 where id = ?
                """,
                (timestamp, current["id"]),
            )
        normalized_teams = _team_candidates(teams)
        metadata = json.dumps(
            {
                "default_team_id": default_team_id,
                "team_uuids": [item["id"] for item in normalized_teams],
                "teams": normalized_teams,
                "verification_method": "ones_provider_login",
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if exact is not None:
            existing_metadata = _json_object(exact.get("metadata_json"))
            scope_changed = str(existing_metadata.get("default_team_id") or "") != default_team_id
            self.database.execute(
                """
                update user_external_identity
                   set tenant_code = ?, provider_instance_id = ?, display_name = ?,
                       metadata_json = ?, status = 'enabled', verified_at = ?,
                       revision = revision + 1,
                       binding_revision = binding_revision + ?, updated_at = ?
                 where id = ?
                """,
                (
                    provider_code,
                    provider_instance_id,
                    display_name,
                    metadata,
                    timestamp,
                    1 if scope_changed else 0,
                    timestamp,
                    exact["id"],
                ),
            )
            return {"id": str(exact["id"])}
        identity_id = new_id("identity")
        self.database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               connector_id, union_id, open_id, display_name, status,
               verified_at, last_seen_at, metadata_json, revision,
               created_at, updated_at, provider_instance_id, binding_revision)
            values (?, ?, 'ones', ?, ?, '', '', '', ?, 'enabled',
                    ?, null, ?, 1, ?, ?, ?, 1)
            """,
            (
                identity_id,
                user_id,
                provider_code,
                external_user_id,
                display_name,
                timestamp,
                metadata,
                timestamp,
                timestamp,
                provider_instance_id,
            ),
        )
        return {"id": identity_id}

    def _challenge(self, challenge_id: str, *, user_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select * from provider_verification_challenge
             where id = ? and user_id = ?
            """,
            (challenge_id, user_id),
        )
        if row is None:
            raise self._challenge_invalid()
        return row

    def _current(self, *, user_id: str, provider_instance_id: str | None) -> dict[str, Any]:
        clause = "and provider_instance_id = ?" if provider_instance_id else ""
        params: tuple[Any, ...] = (
            (user_id, provider_instance_id) if provider_instance_id else (user_id,)
        )
        row = self.database.execute_one(
            f"""
            select * from provider_credential
             where user_id = ? {clause}
               and status in ('ACTIVE', 'INVALID')
             order by revision desc limit 1
            """,
            params,
        )
        if row is None:
            raise NotFound(
                "Provider credential not found",
                safe_message="尚未验证 ONES 凭据",
            )
        return row

    def _update_usage(
        self,
        credential_id: str,
        assignments: str,
        values: tuple[Any, ...],
    ) -> dict[str, Any]:
        rows = self.database.execute(
            f"update provider_credential set {assignments} where id = ? returning *",
            (*values, credential_id),
        )
        if not rows:
            raise NotFound("Provider credential not found", safe_message="未找到 ONES 凭据")
        return self._public_credential(rows[0])

    @staticmethod
    def _public_credential(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            raise NotFound("Provider credential not found", safe_message="未找到 ONES 凭据")
        return {
            key: row.get(key)
            for key in (
                "id",
                "user_id",
                "external_identity_id",
                "provider_instance_id",
                "status",
                "revision",
                "last_error_code",
                "last_attempt_at",
                "last_success_at",
                "last_error_at",
                "verified_at",
                "created_at",
                "updated_at",
            )
        }

    @staticmethod
    def _challenge_invalid() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Provider verification challenge is invalid",
            safe_message="验证已失效，请重新登录 ONES",
            error_code="provider_challenge_invalid",
        )


class DingTalkBindingChallengeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, *, user_id: str, expires_at: str) -> dict[str, str]:
        raw_code = f"EA-BIND-{secrets.token_urlsafe(18)}"
        code_hash = _sha256(raw_code)
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                update dingtalk_identity_binding_challenge
                   set status = 'CANCELLED'
                 where user_id = ? and status = 'PENDING'
                """,
                (user_id,),
            )
            challenge_id = new_id("dingtalk_binding_challenge")
            self.database.execute(
                """
                insert into dingtalk_identity_binding_challenge
                  (id, user_id, code_hash, expires_at, status, created_at)
                values (?, ?, ?, ?, 'PENDING', ?)
                """,
                (challenge_id, user_id, code_hash, expires_at, timestamp),
            )
        return {
            "id": challenge_id,
            "code": raw_code,
            "expires_at": expires_at,
            "status": "PENDING",
        }

    def consume_trusted_event(
        self,
        *,
        code: str,
        dingtalk_enterprise_id: str,
        external_subject_id: str,
        display_name: str,
        connector_id: str,
        trusted_event_id: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.database.unit_of_work():
            challenge = self.database.execute_one(
                """
                select * from dingtalk_identity_binding_challenge
                 where code_hash = ? and status = 'PENDING'
                """,
                (_sha256(code),),
            )
            if challenge is None:
                raise self._invalid()
            if _parse_time(str(challenge["expires_at"])) <= datetime.now(UTC):
                self.database.execute(
                    """
                    update dingtalk_identity_binding_challenge
                       set status = 'EXPIRED'
                     where id = ? and status = 'PENDING'
                    """,
                    (challenge["id"],),
                )
                raise self._invalid()
            trusted = self.database.execute_one(
                """
                select c.id, c.enabled, c.deleted, c.dingtalk_enterprise_id,
                       e.status as enterprise_status
                  from integration_connector c
                  join dingtalk_enterprise e on e.id = c.dingtalk_enterprise_id
                 where c.id = ? and c.connector_type = 'dingtalk_enterprise_stream'
                """,
                (connector_id,),
            )
            if (
                trusted is None
                or not bool(trusted["enabled"])
                or bool(trusted["deleted"])
                or str(trusted["enterprise_status"]) != "ACTIVE"
                or str(trusted["dingtalk_enterprise_id"]) != dingtalk_enterprise_id
            ):
                raise NonRetryableExecutionError(
                    "DingTalk trusted event source is unavailable",
                    safe_message="钉钉应用或企业当前不可用",
                    error_code="dingtalk_trusted_source_unavailable",
                )
            user_id = str(challenge["user_id"])
            exact = self.database.execute_one(
                """
                select * from user_external_identity
                 where provider = 'dingtalk' and dingtalk_enterprise_id = ?
                   and external_subject_id = ?
                """,
                (dingtalk_enterprise_id, external_subject_id),
            )
            if exact is not None and str(exact["user_id"]) != user_id:
                raise NonRetryableExecutionError(
                    "DingTalk identity belongs to another user",
                    safe_message="该钉钉身份已绑定其他用户",
                    error_code="identity_conflict",
                )
            current = self.database.execute_one(
                """
                select * from user_external_identity
                 where provider = 'dingtalk' and user_id = ?
                   and dingtalk_enterprise_id = ?
                   and status in ('enabled', 'disabled')
                """,
                (user_id, dingtalk_enterprise_id),
            )
            if current is not None and (exact is None or str(current["id"]) != str(exact["id"])):
                self.database.execute(
                    """
                    update user_external_identity
                       set status = 'unbound', revision = revision + 1, updated_at = ?
                     where id = ?
                    """,
                    (timestamp, current["id"]),
                )
            metadata = json.dumps(
                {
                    "verification_method": "trusted_dingtalk_challenge",
                    "trusted_event_id": trusted_event_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if exact is not None:
                identity_id = str(exact["id"])
                self.database.execute(
                    """
                    update user_external_identity
                       set display_name = ?, status = 'enabled', verified_at = ?,
                           last_seen_at = ?, metadata_json = ?, revision = revision + 1,
                           updated_at = ?, connector_id = ?
                     where id = ?
                    """,
                    (
                        display_name,
                        timestamp,
                        occurred_at or timestamp,
                        metadata,
                        timestamp,
                        connector_id,
                        identity_id,
                    ),
                )
            else:
                identity_id = new_id("identity")
                self.database.execute(
                    """
                    insert into user_external_identity
                      (id, user_id, provider, tenant_code, external_subject_id,
                       connector_id, union_id, open_id, display_name, status,
                       verified_at, last_seen_at, metadata_json, revision,
                       created_at, updated_at, dingtalk_enterprise_id,
                       display_name_observed_at, display_name_event_id,
                       display_name_source_connector_id)
                    values (?, ?, 'dingtalk', ?, ?, ?, '', '', ?, 'enabled',
                            ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identity_id,
                        user_id,
                        dingtalk_enterprise_id,
                        external_subject_id,
                        connector_id,
                        display_name,
                        timestamp,
                        occurred_at or timestamp,
                        metadata,
                        timestamp,
                        timestamp,
                        dingtalk_enterprise_id,
                        occurred_at or timestamp,
                        trusted_event_id,
                        connector_id,
                    ),
                )
            consumed = self.database.execute(
                """
                update dingtalk_identity_binding_challenge
                   set status = 'CONSUMED', consumed_at = ?,
                       consumed_external_identity_id = ?, trusted_connector_id = ?,
                       trusted_event_id = ?
                 where id = ? and status = 'PENDING'
                returning id
                """,
                (
                    timestamp,
                    identity_id,
                    connector_id,
                    trusted_event_id,
                    challenge["id"],
                ),
            )
            if not consumed:
                raise self._invalid()
        return {"user_id": user_id, "identity_id": identity_id}

    @staticmethod
    def _invalid() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "DingTalk binding challenge is invalid",
            safe_message="钉钉绑定码无效或已过期",
            error_code="dingtalk_binding_challenge_invalid",
        )


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_team_candidates(value: Any) -> list[dict[str, str]]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return _team_candidates([item for item in parsed if isinstance(item, dict)])


def _team_candidates(values: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        team_id = str(value.get("id") or value.get("uuid") or "").strip()
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


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode())
