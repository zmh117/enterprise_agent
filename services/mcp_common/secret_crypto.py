from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.mcp_common.auth import McpAuthenticationError


_PROVIDER_AAD = b"enterprise-agent:provider-credential:v1"


class ProviderTokenDecryptor:
    """Read-only decryptor shared by the trusted ONES MCP process only."""

    def __init__(self, master_key: str) -> None:
        material = master_key.strip()
        if not material or material in {"change-me", "<your-master-key>"}:
            raise McpAuthenticationError("Provider credential Master Key is unavailable")
        self._key = hashlib.sha256(f"provider-credential:v1:{material}".encode()).digest()
        self.key_id = hashlib.sha256(self._key).hexdigest()[:16]

    @classmethod
    def from_file(cls, path: str) -> ProviderTokenDecryptor:
        configured = path.strip()
        if not configured:
            raise McpAuthenticationError("APP_CONFIG_MASTER_KEY_FILE is required")
        try:
            material = Path(configured).read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise McpAuthenticationError("Provider credential Master Key is unreadable") from exc
        return cls(material)

    def decrypt(self, *, ciphertext: str, key_id: str) -> str:
        if key_id != self.key_id:
            raise McpAuthenticationError("Provider credential key is unavailable")
        try:
            padded = ciphertext + "=" * (-len(ciphertext) % 4)
            raw = base64.urlsafe_b64decode(padded.encode())
            return AESGCM(self._key).decrypt(raw[:12], raw[12:], _PROVIDER_AAD).decode()
        except Exception as exc:
            raise McpAuthenticationError("Provider credential cannot be decrypted") from exc


class PlatformSecretDecryptor:
    def __init__(self, master_key: str) -> None:
        material = master_key.strip()
        if not material or material in {"change-me", "<your-master-key>"}:
            raise McpAuthenticationError("Platform Secret Master Key is unavailable")
        padded = material + "=" * (-len(material) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded.encode())
        except Exception:
            decoded = b""
        self._key = decoded if len(decoded) == 32 else hashlib.sha256(material.encode()).digest()

    @classmethod
    def from_file(cls, path: str) -> PlatformSecretDecryptor:
        configured = path.strip()
        if not configured:
            raise McpAuthenticationError("APP_CONFIG_MASTER_KEY_FILE is required")
        try:
            material = Path(configured).read_text(encoding="ascii").rstrip("\r\n")
        except (OSError, UnicodeError) as exc:
            raise McpAuthenticationError("Platform Secret Master Key is unreadable") from exc
        if material.startswith("EA_MASTER_KEY_V1:"):
            material = material.removeprefix("EA_MASTER_KEY_V1:")
        return cls(material)

    def decrypt(
        self,
        *,
        secret_id: str,
        version: int,
        ciphertext: str,
        nonce: str,
        algorithm: str,
    ) -> str:
        if algorithm not in {"AES-256-GCM-AAD-V1", "AES-256-GCM"}:
            raise McpAuthenticationError("Platform Secret algorithm is unsupported")
        try:
            encrypted = _unb64(ciphertext)
            nonce_bytes = _unb64(nonce)
            aad = (
                f"platform-secret|v1|{secret_id}|{version}".encode()
                if algorithm == "AES-256-GCM-AAD-V1"
                else None
            )
            return AESGCM(self._key).decrypt(nonce_bytes, encrypted, aad).decode()
        except Exception as exc:
            raise McpAuthenticationError("Platform Secret cannot be decrypted") from exc


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode())
