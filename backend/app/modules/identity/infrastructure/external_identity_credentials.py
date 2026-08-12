from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound
from app.shared.secret_crypto import (
    decode_base64url,
    encode_base64url,
    master_key_id,
    normalize_master_key,
    zero_bytes,
)


CredentialContext = Literal["credential", "challenge"]
CredentialPurpose = Literal["login-material", "provider-token"]


@dataclass(frozen=True)
class EncryptedCredentialValue:
    ciphertext: str = field(repr=False)
    nonce: str = field(repr=False)
    key_id: str
    algorithm: str

    def __repr__(self) -> str:
        return f"EncryptedCredentialValue(key_id={self.key_id!r}, algorithm={self.algorithm!r})"


@dataclass(frozen=True)
class CredentialSecretBundle:
    email: str = field(repr=False)
    password: str = field(repr=False)
    token: str = field(repr=False)

    def __repr__(self) -> str:
        return "CredentialSecretBundle(email=<hidden>, password=<hidden>, token=<hidden>)"


@dataclass(frozen=True)
class ResolvedExternalCredential:
    id: str
    external_identity_id: str
    provider: str
    revision: int
    secrets: CredentialSecretBundle = field(repr=False)

    def __repr__(self) -> str:
        return (
            "ResolvedExternalCredential("
            f"id={self.id!r}, external_identity_id={self.external_identity_id!r}, "
            f"provider={self.provider!r}, revision={self.revision}, secrets=<hidden>)"
        )


class ExternalIdentityCredentialCipher:
    algorithm = "AES-256-GCM"
    max_plaintext_bytes = 65_536

    def __init__(self, master_key: str) -> None:
        self._master_key = normalize_master_key(master_key)
        self.key_id = master_key_id(self._master_key)

    def encrypt(
        self,
        value: str,
        *,
        context: CredentialContext,
        context_id: str,
        purpose: CredentialPurpose,
    ) -> EncryptedCredentialValue:
        plaintext = str(value or "")
        self._validate_context(context=context, context_id=context_id, purpose=purpose)
        if not plaintext or len(plaintext.encode("utf-8")) > self.max_plaintext_bytes:
            raise self._crypto_error()
        nonce = os.urandom(12)
        plaintext_bytes = bytearray(plaintext.encode("utf-8"))
        try:
            ciphertext = AESGCM(self._master_key).encrypt(
                nonce,
                plaintext_bytes,
                self._aad(context=context, context_id=context_id, purpose=purpose),
            )
            return EncryptedCredentialValue(
                ciphertext=encode_base64url(ciphertext),
                nonce=encode_base64url(nonce),
                key_id=self.key_id,
                algorithm=self.algorithm,
            )
        finally:
            zero_bytes(plaintext_bytes)

    def decrypt(
        self,
        encrypted: EncryptedCredentialValue,
        *,
        context: CredentialContext,
        context_id: str,
        purpose: CredentialPurpose,
    ) -> str:
        self._validate_context(context=context, context_id=context_id, purpose=purpose)
        if (
            not encrypted.ciphertext
            or not encrypted.nonce
            or encrypted.key_id != self.key_id
            or encrypted.algorithm != self.algorithm
        ):
            raise self._crypto_error()
        plaintext: bytearray | None = None
        try:
            nonce = decode_base64url(encrypted.nonce)
            if len(nonce) != 12:
                raise ValueError("invalid nonce")
            plaintext = bytearray(
                AESGCM(self._master_key).decrypt(
                    nonce,
                    decode_base64url(encrypted.ciphertext),
                    self._aad(context=context, context_id=context_id, purpose=purpose),
                )
            )
            if not plaintext or len(plaintext) > self.max_plaintext_bytes:
                raise ValueError("invalid plaintext length")
            return plaintext.decode("utf-8")
        except Exception:
            raise self._crypto_error() from None
        finally:
            if plaintext is not None:
                zero_bytes(plaintext)

    def encrypt_login_material(
        self,
        *,
        email: str,
        password: str,
        context: CredentialContext,
        context_id: str,
    ) -> EncryptedCredentialValue:
        normalized_email = str(email or "").strip()
        if not normalized_email or not password:
            raise self._crypto_error()
        return self.encrypt(
            json.dumps(
                {"email": normalized_email, "password": password},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            context=context,
            context_id=context_id,
            purpose="login-material",
        )

    def decrypt_login_material(
        self,
        encrypted: EncryptedCredentialValue,
        *,
        context: CredentialContext,
        context_id: str,
    ) -> tuple[str, str]:
        raw = self.decrypt(
            encrypted,
            context=context,
            context_id=context_id,
            purpose="login-material",
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise self._crypto_error() from None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"email", "password"}
            or not isinstance(payload.get("email"), str)
            or not payload["email"].strip()
            or not isinstance(payload.get("password"), str)
            or not payload["password"]
        ):
            raise self._crypto_error()
        return payload["email"].strip(), payload["password"]

    @staticmethod
    def _validate_context(*, context: str, context_id: str, purpose: str) -> None:
        if (
            context not in {"credential", "challenge"}
            or purpose not in {"login-material", "provider-token"}
            or not str(context_id or "").strip()
            or "|" in context_id
        ):
            raise ExternalIdentityCredentialCipher._crypto_error()

    @staticmethod
    def _aad(*, context: str, context_id: str, purpose: str) -> bytes:
        return (f"external-identity-credential|v1|{context}|{context_id}|{purpose}").encode("utf-8")

    @staticmethod
    def _crypto_error() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "External identity credential cryptographic operation failed",
            safe_message="外部身份凭据无法安全处理，请重新验证",
            error_code="external_identity_credential_invalid",
        )


class ExternalIdentityCredentialRepository:
    def __init__(
        self,
        database: Database,
        cipher: ExternalIdentityCredentialCipher,
    ) -> None:
        self.database = database
        self.cipher = cipher

    def upsert_active(
        self,
        *,
        external_identity_id: str,
        provider: str,
        secrets: CredentialSecretBundle,
        verified_at: str,
    ) -> dict[str, Any]:
        normalized_provider = provider.strip().lower()
        if not normalized_provider:
            raise self._state_error("external_identity_credential_provider_invalid")
        with self.database.unit_of_work():
            identity = self.database.execute_one(
                "select id, provider from user_external_identity where id = ?",
                (external_identity_id,),
            )
            if identity is None:
                raise NotFound(
                    "External identity not found for credential",
                    safe_message="外部身份不存在",
                    error_code="external_identity_not_found",
                )
            if str(identity["provider"]).strip().lower() != normalized_provider:
                raise self._state_error("external_identity_credential_provider_mismatch")
            existing = self.get_by_identity(external_identity_id)
            credential_id = (
                str(existing["id"])
                if existing is not None
                else new_id("external_identity_credential")
            )
            next_revision = int(existing["revision"]) + 1 if existing else 1
            login = self.cipher.encrypt_login_material(
                email=secrets.email,
                password=secrets.password,
                context="credential",
                context_id=credential_id,
            )
            token = self.cipher.encrypt(
                secrets.token,
                context="credential",
                context_id=credential_id,
                purpose="provider-token",
            )
            timestamp = now_iso()
            if existing is None:
                row = self.database.execute_one(
                    """
                    insert into external_identity_credential
                      (id, external_identity_id, provider, status, revision,
                       login_material_ciphertext, login_material_nonce,
                       token_ciphertext, token_nonce, key_id, algorithm,
                       verified_at, token_refreshed_at, last_used_at,
                       reauth_required_at, disabled_at, unbound_at,
                       last_error_code, created_at, updated_at)
                    values (?, ?, ?, 'ACTIVE', 1, ?, ?, ?, ?, ?, ?, ?, null,
                            null, null, null, null, '', ?, ?)
                    returning *
                    """,
                    (
                        credential_id,
                        external_identity_id,
                        normalized_provider,
                        login.ciphertext,
                        login.nonce,
                        token.ciphertext,
                        token.nonce,
                        login.key_id,
                        login.algorithm,
                        verified_at,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                row = self.database.execute_one(
                    """
                    update external_identity_credential
                       set provider = ?, status = 'ACTIVE', revision = ?,
                           login_material_ciphertext = ?, login_material_nonce = ?,
                           token_ciphertext = ?, token_nonce = ?, key_id = ?,
                           algorithm = ?, verified_at = ?, token_refreshed_at = null,
                           last_used_at = null, reauth_required_at = null,
                           disabled_at = null, unbound_at = null,
                           last_error_code = '', updated_at = ?
                     where id = ? and revision = ?
                    returning *
                    """,
                    (
                        normalized_provider,
                        next_revision,
                        login.ciphertext,
                        login.nonce,
                        token.ciphertext,
                        token.nonce,
                        login.key_id,
                        login.algorithm,
                        verified_at,
                        timestamp,
                        credential_id,
                        int(existing["revision"]),
                    ),
                )
            if row is None:
                raise self._state_error("external_identity_credential_revision_conflict")
            return self.project_safe(row)

    def rotate_token(
        self,
        *,
        credential_id: str,
        expected_revision: int,
        token: str,
    ) -> dict[str, Any]:
        encrypted = self.cipher.encrypt(
            token,
            context="credential",
            context_id=credential_id,
            purpose="provider-token",
        )
        timestamp = now_iso()
        row = self.database.execute_one(
            """
            update external_identity_credential
               set token_ciphertext = ?, token_nonce = ?,
                   key_id = ?, algorithm = ?, revision = revision + 1,
                   token_refreshed_at = ?, last_error_code = '', updated_at = ?
             where id = ? and revision = ? and status = 'ACTIVE'
            returning *
            """,
            (
                encrypted.ciphertext,
                encrypted.nonce,
                encrypted.key_id,
                encrypted.algorithm,
                timestamp,
                timestamp,
                credential_id,
                expected_revision,
            ),
        )
        if row is None:
            raise self._state_error("external_identity_credential_revision_conflict")
        return self.project_safe(row)

    def mark_used(self, *, credential_id: str, expected_revision: int) -> None:
        updated = self.database.execute(
            """
            update external_identity_credential
               set last_used_at = ?, updated_at = ?
             where id = ? and revision = ? and status = 'ACTIVE'
            returning id
            """,
            (now_iso(), now_iso(), credential_id, expected_revision),
        )
        if len(updated) != 1:
            raise self._state_error("external_identity_credential_revision_conflict")

    def mark_reauth_required(
        self,
        *,
        credential_id: str,
        expected_revision: int,
        error_code: str,
    ) -> dict[str, Any]:
        return self._transition(
            credential_id=credential_id,
            expected_revision=expected_revision,
            status="REAUTH_REQUIRED",
            time_column="reauth_required_at",
            error_code=error_code,
            clear_secrets=False,
        )

    def disable(
        self,
        *,
        credential_id: str,
        expected_revision: int,
        error_code: str = "external_identity_disabled",
    ) -> dict[str, Any]:
        return self._transition(
            credential_id=credential_id,
            expected_revision=expected_revision,
            status="DISABLED",
            time_column="disabled_at",
            error_code=error_code,
            clear_secrets=False,
        )

    def unbind(
        self,
        *,
        credential_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        return self._transition(
            credential_id=credential_id,
            expected_revision=expected_revision,
            status="UNBOUND",
            time_column="unbound_at",
            error_code="external_identity_unbound",
            clear_secrets=True,
        )

    def resolve_active(self, credential_id: str) -> ResolvedExternalCredential:
        row = self.get_by_id(credential_id)
        if str(row["status"]) != "ACTIVE":
            raise self._state_error("external_identity_credential_not_active")
        encrypted_login = self._encrypted(row, prefix="login_material")
        encrypted_token = self._encrypted(row, prefix="token")
        email, password = self.cipher.decrypt_login_material(
            encrypted_login,
            context="credential",
            context_id=str(row["id"]),
        )
        token = self.cipher.decrypt(
            encrypted_token,
            context="credential",
            context_id=str(row["id"]),
            purpose="provider-token",
        )
        return ResolvedExternalCredential(
            id=str(row["id"]),
            external_identity_id=str(row["external_identity_id"]),
            provider=str(row["provider"]),
            revision=int(row["revision"]),
            secrets=CredentialSecretBundle(email=email, password=password, token=token),
        )

    def get_by_identity(self, external_identity_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            "select * from external_identity_credential where external_identity_id = ?",
            (external_identity_id,),
        )

    def get_by_id(self, credential_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from external_identity_credential where id = ?",
            (credential_id,),
        )
        if row is None:
            raise NotFound(
                "External identity credential not found",
                safe_message="外部身份凭据不存在",
                error_code="external_identity_credential_not_found",
            )
        return row

    def safe_projection_for_identity(self, external_identity_id: str) -> dict[str, Any] | None:
        row = self.get_by_identity(external_identity_id)
        return self.project_safe(row) if row is not None else None

    @staticmethod
    def project_safe(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "configured": bool(
                row.get("login_material_ciphertext")
                and row.get("login_material_nonce")
                and row.get("token_ciphertext")
                and row.get("token_nonce")
            ),
            "status": str(row["status"]),
            "revision": int(row["revision"]),
            "verified_at": str(row["verified_at"]),
            "token_refreshed_at": row.get("token_refreshed_at"),
            "last_used_at": row.get("last_used_at"),
            "reauth_required_at": row.get("reauth_required_at"),
            "disabled_at": row.get("disabled_at"),
            "unbound_at": row.get("unbound_at"),
        }

    def _transition(
        self,
        *,
        credential_id: str,
        expected_revision: int,
        status: str,
        time_column: str,
        error_code: str,
        clear_secrets: bool,
    ) -> dict[str, Any]:
        if time_column not in {"reauth_required_at", "disabled_at", "unbound_at"}:
            raise ValueError("Unsupported credential lifecycle time column")
        clear_sql = (
            "login_material_ciphertext = null, login_material_nonce = null, "
            "token_ciphertext = null, token_nonce = null, "
            if clear_secrets
            else ""
        )
        timestamp = now_iso()
        row = self.database.execute_one(
            f"""
            update external_identity_credential
               set status = ?, revision = revision + 1, {clear_sql}
                   {time_column} = ?, last_error_code = ?, updated_at = ?
             where id = ? and revision = ?
            returning *
            """,
            (
                status,
                timestamp,
                error_code.strip()[:128],
                timestamp,
                credential_id,
                expected_revision,
            ),
        )
        if row is None:
            raise self._state_error("external_identity_credential_revision_conflict")
        return self.project_safe(row)

    @staticmethod
    def _encrypted(row: dict[str, Any], *, prefix: str) -> EncryptedCredentialValue:
        ciphertext = row.get(f"{prefix}_ciphertext")
        nonce = row.get(f"{prefix}_nonce")
        if not isinstance(ciphertext, str) or not isinstance(nonce, str):
            raise ExternalIdentityCredentialRepository._state_error(
                "external_identity_credential_incomplete"
            )
        return EncryptedCredentialValue(
            ciphertext=ciphertext,
            nonce=nonce,
            key_id=str(row.get("key_id") or ""),
            algorithm=str(row.get("algorithm") or ""),
        )

    @staticmethod
    def _state_error(error_code: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "External identity credential state is invalid",
            safe_message="外部身份凭据状态无效，请重新验证",
            error_code=error_code,
        )
