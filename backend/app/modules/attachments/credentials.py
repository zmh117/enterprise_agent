from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.shared.exceptions import NonRetryableExecutionError


class AttachmentCredentialCipher:
    """Encrypt short-lived media source credentials with the bootstrap master key."""

    def __init__(self, master_key: str) -> None:
        value = str(master_key or "").strip()
        if not value or value in {"change-me", "<your-master-key>"}:
            raise NonRetryableExecutionError(
                "APP_CONFIG_MASTER_KEY is required for attachment credentials",
                safe_message="Attachment credential encryption is not configured",
            )
        self.key = hashlib.sha256(value.encode()).digest()

    def encrypt(self, value: str) -> str:
        nonce = os.urandom(12)
        encrypted = AESGCM(self.key).encrypt(nonce, value.encode(), b"attachment-source")
        return _encode(nonce + encrypted)

    def decrypt(self, value: str) -> str:
        try:
            raw = _decode(value)
            return AESGCM(self.key).decrypt(
                raw[:12], raw[12:], b"attachment-source"
            ).decode()
        except Exception as exc:
            raise NonRetryableExecutionError(
                "Attachment credential decrypt failed",
                safe_message="Attachment source credential is unavailable",
            ) from exc


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode())
