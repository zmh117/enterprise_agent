from __future__ import annotations

import base64
import hashlib
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.shared.exceptions import NonRetryableExecutionError, NotFound

from ..infrastructure.repository import PlatformConfigRepository
from .validation import PlatformConfigValidationError, validate_code, validate_secret_ref


class SecretProviderPort(Protocol):
    def resolve(self, ref: str) -> str: ...

    def create_secret(
        self,
        *,
        code: str,
        value: str,
        purpose: str = "",
        actor_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]: ...

    def rotate_secret(self, *, code: str, value: str, actor_id: str = "") -> dict[str, object]: ...

    def disable_secret(self, *, code: str, actor_id: str = "") -> dict[str, object]: ...


class EncryptedDbSecretProvider:
    algorithm = "AES-256-GCM"

    def __init__(
        self,
        repository: PlatformConfigRepository,
        *,
        master_key: str | None = None,
    ) -> None:
        self.repository = repository
        self.master_key = _normalize_master_key(
            master_key if master_key is not None else os.getenv("APP_CONFIG_MASTER_KEY", "")
        )
        self.key_id = hashlib.sha256(self.master_key).hexdigest()[:16]

    def resolve(self, ref: str) -> str:
        ref = validate_secret_ref(ref)
        if not ref.startswith("secret://platform/"):
            raise PlatformConfigValidationError(
                "Unsupported platform secret provider",
                safe_message="Unsupported platform secret provider",
            )
        secret = self.repository.get_platform_secret_by_ref(ref)
        if not secret or secret["status"] != "enabled":
            raise NonRetryableExecutionError(
                f"Platform secret is disabled or missing: {ref}",
                safe_message="Platform secret is disabled or missing",
            )
        version = self.repository.get_active_secret_version(str(secret["id"]))
        if not version:
            raise NonRetryableExecutionError(
                f"Platform secret active version is missing: {ref}",
                safe_message="Platform secret active version is missing",
            )
        return self._decrypt(
            ciphertext=str(version["ciphertext"]),
            nonce=str(version["nonce"]),
        )

    def create_secret(
        self,
        *,
        code: str,
        value: str,
        purpose: str = "",
        actor_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        code = validate_code(code)
        self._require_value(value)
        ref = f"secret://platform/{code}"
        existing = self.repository.get_platform_secret_by_code(code)
        if existing:
            return self.rotate_secret(code=code, value=value, actor_id=actor_id)
        secret = self.repository.upsert_platform_secret(
            code=code,
            provider="encrypted_db",
            ref=ref,
            purpose=purpose,
            status="enabled",
            active_version=0,
            masked_summary=mask_secret(value),
            metadata=metadata or {},
        )
        encrypted = self._encrypt(value)
        self.repository.insert_secret_version(
            secret_id=str(secret["id"]),
            version=1,
            ciphertext=encrypted["ciphertext"],
            nonce=encrypted["nonce"],
            key_id=self.key_id,
            algorithm=self.algorithm,
            status="active",
            created_by=actor_id,
        )
        return self.repository.set_secret_active_version(
            secret_id=str(secret["id"]),
            active_version=1,
            masked_summary=mask_secret(value),
        )

    def rotate_secret(self, *, code: str, value: str, actor_id: str = "") -> dict[str, object]:
        code = validate_code(code)
        self._require_value(value)
        secret = self.repository.get_platform_secret_by_code(code)
        if not secret:
            raise NotFound(f"Platform secret not found: {code}")
        next_version = int(secret.get("active_version") or 0) + 1
        encrypted = self._encrypt(value)
        self.repository.insert_secret_version(
            secret_id=str(secret["id"]),
            version=next_version,
            ciphertext=encrypted["ciphertext"],
            nonce=encrypted["nonce"],
            key_id=self.key_id,
            algorithm=self.algorithm,
            status="active",
            created_by=actor_id,
        )
        return self.repository.set_secret_active_version(
            secret_id=str(secret["id"]),
            active_version=next_version,
            masked_summary=mask_secret(value),
        )

    def disable_secret(self, *, code: str, actor_id: str = "") -> dict[str, object]:
        del actor_id
        return self.repository.set_platform_secret_status(validate_code(code), "disabled")

    def _encrypt(self, value: str) -> dict[str, str]:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.master_key).encrypt(nonce, value.encode("utf-8"), None)
        return {
            "ciphertext": _b64(ciphertext),
            "nonce": _b64(nonce),
        }

    def _decrypt(self, *, ciphertext: str, nonce: str) -> str:
        try:
            plaintext = AESGCM(self.master_key).decrypt(_unb64(nonce), _unb64(ciphertext), None)
        except Exception as exc:
            raise NonRetryableExecutionError(
                "Platform secret decrypt failed",
                safe_message="Platform secret decrypt failed",
            ) from exc
        return plaintext.decode("utf-8")

    def _require_value(self, value: str) -> None:
        if not str(value or ""):
            raise PlatformConfigValidationError(
                "Secret value is required", safe_message="Secret value is required"
            )


def mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:3]}****{text[-4:]}"


def _normalize_master_key(value: str) -> bytes:
    text = str(value or "").strip()
    if not text or text in {"change-me", "<your-master-key>"}:
        raise NonRetryableExecutionError(
            "APP_CONFIG_MASTER_KEY is required for encrypted DB secrets",
            safe_message="APP_CONFIG_MASTER_KEY is required for encrypted DB secrets",
        )
    for candidate in (text, text + "=" * (-len(text) % 4)):
        try:
            decoded = base64.urlsafe_b64decode(candidate.encode("utf-8"))
        except Exception:
            continue
        if len(decoded) == 32:
            return decoded
    return hashlib.sha256(text.encode("utf-8")).digest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
