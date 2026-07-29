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
                "Master Key file is required for attachment credentials",
                safe_message="尚未配置附件凭据加密",
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
                safe_message="附件来源凭据不可用",
            ) from exc


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode())
