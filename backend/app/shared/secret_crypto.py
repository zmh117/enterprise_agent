from __future__ import annotations

import base64
import hashlib

from app.shared.exceptions import NonRetryableExecutionError


def normalize_master_key(value: str) -> bytes:
    """Normalize the already-loaded platform Master Key without exposing it."""

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


def master_key_id(master_key: bytes) -> str:
    if len(master_key) != 32:
        raise ValueError("AES-256 Master Key must contain 32 bytes")
    return hashlib.sha256(master_key).hexdigest()[:16]


def encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_base64url(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def zero_bytes(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
