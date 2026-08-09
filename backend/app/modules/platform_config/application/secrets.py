from __future__ import annotations

import base64
import hashlib
import json
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

    def rotate_secret(
        self,
        *,
        code: str,
        value: str,
        actor_id: str = "",
        expected_revision: int | None = None,
    ) -> dict[str, object]: ...

    def disable_secret(
        self, *, code: str, actor_id: str = "", expected_revision: int | None = None
    ) -> dict[str, object]: ...


class EncryptedDbSecretProvider:
    algorithm = "AES-256-GCM-AAD-V1"
    legacy_algorithm = "AES-256-GCM"
    max_secret_bytes = 65_536

    def __init__(
        self,
        repository: PlatformConfigRepository,
        *,
        master_key: str | None = None,
    ) -> None:
        self.repository = repository
        self.master_key = _normalize_master_key(master_key if master_key is not None else "")
        self.key_id = hashlib.sha256(self.master_key).hexdigest()[:16]

    def resolve(self, ref: str) -> str:
        ref = validate_secret_ref(ref)
        if not ref.startswith("secret://platform/"):
            raise PlatformConfigValidationError(
                "Unsupported platform secret provider",
                safe_message="不支持此平台凭据提供方",
            )
        secret = self.repository.get_platform_secret_by_ref(ref)
        if not secret or secret["status"] != "enabled":
            raise NonRetryableExecutionError(
                f"Platform secret is disabled or missing: {ref}",
                safe_message="平台凭据缺失或已停用",
            )
        version = self.repository.get_active_secret_version(str(secret["id"]))
        if not version:
            raise NonRetryableExecutionError(
                f"Platform secret active version is missing: {ref}",
                safe_message="平台凭据缺少活动版本",
            )
        return self._decrypt(
            ciphertext=str(version["ciphertext"]),
            nonce=str(version["nonce"]),
            algorithm=str(version["algorithm"]),
            secret_id=str(secret["id"]),
            version=int(version["version"]),
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
        metadata = metadata or {}
        self._require_safe_metadata(
            value=value,
            purpose=purpose,
            metadata=metadata,
        )
        existing = self.repository.get_platform_secret_by_code(code)
        if existing:
            raise PlatformConfigValidationError(
                f"Platform secret already exists: {code}",
                safe_message="凭据已存在，请使用轮换操作",
            )
        secret = self.repository.upsert_platform_secret(
            code=code,
            provider="encrypted_db",
            ref=ref,
            purpose=purpose,
            status="enabled",
            active_version=0,
            masked_summary=mask_secret(value),
            metadata=metadata,
        )
        encrypted = self._encrypt(
            value,
            secret_id=str(secret["id"]),
            version=1,
        )
        self._insert_version(
            secret_id=str(secret["id"]),
            version=1,
            encrypted=encrypted,
            actor_id=actor_id,
        )
        activated = self.repository.set_secret_active_version(
            secret_id=str(secret["id"]),
            active_version=1,
            masked_summary=mask_secret(value),
        )
        self._notify_change(activated, action="create")
        return activated

    def rotate_secret(
        self,
        *,
        code: str,
        value: str,
        actor_id: str = "",
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        code = validate_code(code)
        self._require_value(value)
        secret = self.repository.get_platform_secret_by_code(code)
        if not secret:
            raise NotFound(f"Platform secret not found: {code}")
        next_version = int(secret.get("active_version") or 0) + 1
        encrypted = self._encrypt(
            value,
            secret_id=str(secret["id"]),
            version=next_version,
        )
        self._insert_version(
            secret_id=str(secret["id"]),
            version=next_version,
            encrypted=encrypted,
            actor_id=actor_id,
        )
        activated = self.repository.set_secret_active_version(
            secret_id=str(secret["id"]),
            active_version=next_version,
            masked_summary=mask_secret(value),
            expected_revision=expected_revision,
        )
        self._notify_change(activated, action="rotate")
        return activated

    def disable_secret(
        self, *, code: str, actor_id: str = "", expected_revision: int | None = None
    ) -> dict[str, object]:
        del actor_id
        disabled = self.repository.set_platform_secret_status(
            validate_code(code),
            "disabled",
            expected_revision=expected_revision,
        )
        self._notify_change(disabled, action="disable")
        return disabled

    def _notify_change(
        self,
        secret: dict[str, object],
        *,
        action: str,
    ) -> None:
        self.repository.insert_secret_change_event(
            secret_id=str(secret["id"]),
            secret_revision=int(str(secret["revision"])),
            action=action,
        )

    def _insert_version(
        self,
        *,
        secret_id: str,
        version: int,
        encrypted: dict[str, str],
        actor_id: str,
    ) -> None:
        try:
            self.repository.insert_secret_version(
                secret_id=secret_id,
                version=version,
                ciphertext=encrypted["ciphertext"],
                nonce=encrypted["nonce"],
                key_id=self.key_id,
                algorithm=self.algorithm,
                status="staged",
                created_by=actor_id,
            )
        except Exception:
            raise NonRetryableExecutionError(
                "Platform secret persistence failed",
                safe_message="平台凭据保存失败",
            ) from None

    def _encrypt(
        self,
        value: str,
        *,
        secret_id: str,
        version: int,
    ) -> dict[str, str]:
        nonce = os.urandom(12)
        plaintext = bytearray(value.encode("utf-8"))
        try:
            ciphertext = AESGCM(self.master_key).encrypt(
                nonce,
                plaintext,
                _aad(secret_id=secret_id, version=version),
            )
            return {
                "ciphertext": _b64(ciphertext),
                "nonce": _b64(nonce),
            }
        finally:
            _zero(plaintext)

    def _decrypt(
        self,
        *,
        ciphertext: str,
        nonce: str,
        algorithm: str,
        secret_id: str,
        version: int,
    ) -> str:
        plaintext: bytearray | None = None
        aad = _aad(secret_id=secret_id, version=version) if algorithm == self.algorithm else None
        if algorithm not in {self.algorithm, self.legacy_algorithm}:
            raise NonRetryableExecutionError(
                "Unsupported platform secret encryption algorithm",
                safe_message="平台凭据加密格式不受支持",
            )
        try:
            plaintext = bytearray(
                AESGCM(self.master_key).decrypt(
                    _unb64(nonce),
                    _unb64(ciphertext),
                    aad,
                )
            )
            return plaintext.decode("utf-8")
        except Exception:
            raise NonRetryableExecutionError(
                "Platform secret decrypt failed",
                safe_message="平台凭据解密失败",
            ) from None
        finally:
            if plaintext is not None:
                _zero(plaintext)
        return plaintext.decode("utf-8")

    def _require_value(self, value: str) -> None:
        if not str(value or ""):
            raise PlatformConfigValidationError(
                "Secret value is required", safe_message="必须填写凭据值"
            )
        if len(value.encode("utf-8")) > self.max_secret_bytes:
            raise PlatformConfigValidationError(
                "Secret value is too large",
                safe_message="凭据值超过允许长度",
            )

    @staticmethod
    def _require_safe_metadata(
        *,
        value: str,
        purpose: str,
        metadata: dict[str, object],
    ) -> None:
        metadata_text = json.dumps(
            {"purpose": purpose, "metadata": metadata},
            ensure_ascii=False,
            sort_keys=True,
        )
        if value and value in metadata_text:
            raise PlatformConfigValidationError(
                "Secret plaintext must not be copied into metadata",
                safe_message="凭据明文不得写入用途或元数据",
            )


def mask_secret(value: str) -> str:
    return "********" if str(value or "") else ""


def _normalize_master_key(value: str) -> bytes:
    text = str(value or "").strip()
    if not text or text in {"change-me", "<your-master-key>"}:
        raise NonRetryableExecutionError(
            "Master Key file is required for encrypted DB secrets",
            safe_message="加密数据库凭据需要配置 Master Key 文件",
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


def _aad(*, secret_id: str, version: int) -> bytes:
    return f"platform-secret|v1|{secret_id}|{version}".encode("utf-8")


def _zero(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
