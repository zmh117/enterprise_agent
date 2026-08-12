from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PROBE_ENVELOPE_ALGORITHM = "AES-256-GCM-DERIVED-PROBE-V1"
_DERIVATION_LABEL = b"enterprise-agent:model-probe-envelope:v1"
_MAX_ENVELOPE_LIFETIME_SECONDS = 90
_MAX_PLAINTEXT_BYTES = 12_272
_MAX_CIPHERTEXT_BYTES = 12_288
_MAX_CONSUMED_PROBES = 4096


class ModelProbeEnvelopeError(RuntimeError):
    error_code = "model_connection_probe_envelope_invalid"
    safe_message = "模型连接测试凭据无效或已过期"


@dataclass(frozen=True)
class DecryptedModelProbeEnvelope:
    config: dict[str, Any]
    api_key: str


class ModelProbeEnvelopeCipher:
    """Process-local cipher for one-use draft model probe credentials."""

    def __init__(
        self,
        master_key: str,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        material = bytearray(_normalize_master_key(master_key))
        try:
            self._key = hmac.new(material, _DERIVATION_LABEL, hashlib.sha256).digest()
        finally:
            _zero(material)
        self._now = now
        self._consumed: dict[str, int] = {}
        self._lock = threading.Lock()

    def encrypt(
        self,
        *,
        probe_id: str,
        runtime_kind: str,
        config_hash: str,
        config: dict[str, Any],
        api_key: str,
        lifetime_seconds: int,
    ) -> dict[str, object]:
        lifetime = max(10, min(int(lifetime_seconds), 60))
        expires_at = int(self._now()) + lifetime
        payload = {
            "schema_version": 1,
            "config": config,
            "api_key": api_key,
        }
        plaintext = bytearray(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if len(plaintext) > _MAX_PLAINTEXT_BYTES:
            _zero(plaintext)
            raise ModelProbeEnvelopeError("Draft model probe envelope is too large")
        nonce = os.urandom(12)
        try:
            ciphertext = AESGCM(self._key).encrypt(
                nonce,
                plaintext,
                _aad(
                    probe_id=probe_id,
                    runtime_kind=runtime_kind,
                    config_hash=config_hash,
                    expires_at=expires_at,
                ),
            )
        finally:
            _zero(plaintext)
        return {
            "algorithm": PROBE_ENVELOPE_ALGORITHM,
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
            "expires_at": expires_at,
        }

    def decrypt(
        self,
        request: dict[str, Any],
        *,
        expected_runtime_kind: str,
    ) -> DecryptedModelProbeEnvelope:
        try:
            probe_id = str(request["probe_id"])
            runtime_kind = str(request["runtime_kind"])
            config_hash = str(request["config_hash"])
            envelope = request["credential_envelope"]
            if not isinstance(envelope, dict):
                raise ValueError("credential envelope is not an object")
            if runtime_kind != expected_runtime_kind:
                raise ValueError("credential envelope targets another Runtime")
            if envelope.get("algorithm") != PROBE_ENVELOPE_ALGORITHM:
                raise ValueError("credential envelope algorithm is unsupported")
            expires_at = int(envelope["expires_at"])
            now = int(self._now())
            if expires_at <= now or expires_at > now + _MAX_ENVELOPE_LIFETIME_SECONDS:
                raise ValueError("credential envelope is expired or outside its lifetime")
            nonce = _unb64(str(envelope["nonce"]), maximum_bytes=12)
            ciphertext = _unb64(
                str(envelope["ciphertext"]),
                maximum_bytes=_MAX_CIPHERTEXT_BYTES,
            )
            if len(nonce) != 12 or len(ciphertext) <= 16:
                raise ValueError("credential envelope payload length is invalid")
            plaintext = bytearray(
                AESGCM(self._key).decrypt(
                    nonce,
                    ciphertext,
                    _aad(
                        probe_id=probe_id,
                        runtime_kind=runtime_kind,
                        config_hash=config_hash,
                        expires_at=expires_at,
                    ),
                )
            )
            try:
                payload = json.loads(plaintext.decode("utf-8"))
            finally:
                _zero(plaintext)
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "config",
                "api_key",
            }:
                raise ValueError("credential envelope plaintext shape is invalid")
            if payload["schema_version"] != 1 or not isinstance(payload["config"], dict):
                raise ValueError("credential envelope plaintext version is invalid")
            api_key = payload["api_key"]
            if not isinstance(api_key, str) or not api_key or len(api_key.encode("utf-8")) > 4000:
                raise ValueError("credential envelope API Key is invalid")
            config = dict(payload["config"])
            if _config_hash(config) != config_hash:
                raise ValueError("credential envelope config hash mismatch")
            self._consume_once(probe_id, expires_at, now)
            return DecryptedModelProbeEnvelope(config=config, api_key=api_key)
        except ModelProbeEnvelopeError:
            raise
        except Exception as exc:
            raise ModelProbeEnvelopeError(
                "Draft model probe envelope authentication failed"
            ) from exc

    def _consume_once(self, probe_id: str, expires_at: int, now: int) -> None:
        with self._lock:
            self._consumed = {
                item: expiry for item, expiry in self._consumed.items() if expiry > now
            }
            if probe_id in self._consumed:
                raise ModelProbeEnvelopeError("Draft model probe envelope was already consumed")
            if len(self._consumed) >= _MAX_CONSUMED_PROBES:
                raise ModelProbeEnvelopeError("Draft model probe replay ledger is full")
            self._consumed[probe_id] = expires_at


def _normalize_master_key(value: str) -> bytes:
    text = str(value or "").strip()
    if text.startswith("EA_MASTER_KEY_V1:"):
        text = text.removeprefix("EA_MASTER_KEY_V1:")
    if not text or text in {"change-me", "<your-master-key>"}:
        raise ModelProbeEnvelopeError("Master Key is unavailable for draft model probes")
    try:
        decoded = _unb64(text, maximum_bytes=32)
        if len(decoded) == 32:
            return decoded
    except ValueError:
        pass
    # Programmatic non-versioned keys are retained for isolated tests only.
    return hashlib.sha256(text.encode("utf-8")).digest()


def _config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _aad(*, probe_id: str, runtime_kind: str, config_hash: str, expires_at: int) -> bytes:
    return (f"model-probe-envelope|v1|{probe_id}|{runtime_kind}|{config_hash}|{expires_at}").encode(
        "utf-8"
    )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str, *, maximum_bytes: int) -> bytes:
    if not value or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in value
    ):
        raise ValueError("base64url value is invalid")
    decoded = base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))
    if len(decoded) > maximum_bytes or _b64(decoded) != value:
        raise ValueError("base64url value is not canonical")
    return decoded


def _zero(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
