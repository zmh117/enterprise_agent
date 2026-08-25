from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jwt

from app.modules.agent.infrastructure.generated_runtime_contracts_v1_4 import validate_contract


class RuntimeGrantError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RuntimeGrantVerifier:
    def __init__(
        self,
        public_key: bytes,
        *,
        now: Callable[[], int] | None = None,
    ) -> None:
        if not public_key.startswith(b"-----BEGIN PUBLIC KEY-----"):
            raise RuntimeGrantError(
                "runtime_grant_key_invalid",
                "Runtime Grant public key must be PEM",
            )
        self._public_key = public_key
        self._now = now or (lambda: int(time.time()))
        self._used_jti: dict[str, tuple[str, str, int]] = {}

    @classmethod
    def from_file(cls, path: str) -> RuntimeGrantVerifier:
        configured = path.strip()
        if not configured:
            raise RuntimeGrantError(
                "runtime_grant_key_invalid",
                "RUNTIME_GRANT_PUBLIC_KEY_FILE is required",
            )
        key_path = Path(configured)
        try:
            if not 64 <= key_path.stat().st_size <= 16_384:
                raise RuntimeGrantError(
                    "runtime_grant_key_invalid",
                    "Runtime Grant public key size is invalid",
                )
            return cls(key_path.read_bytes())
        except OSError as exc:
            raise RuntimeGrantError(
                "runtime_grant_key_invalid",
                "Runtime Grant public key is unreadable",
            ) from exc

    def verify(self, token: str, request: dict[str, Any]) -> dict[str, Any]:
        if not token or len(token) > 16_384:
            raise RuntimeGrantError("runtime_grant_invalid", "Runtime Grant is missing")
        try:
            claims = dict(
                jwt.decode(
                    token,
                    self._public_key,
                    algorithms=["EdDSA"],
                    audience="agent-runtime",
                    issuer="enterprise-agent-worker",
                    leeway=5,
                    options={"require": ["exp", "iat", "nbf", "jti"]},
                )
            )
            validate_contract("RuntimeGrantClaims", claims)
        except Exception as exc:
            raise RuntimeGrantError(
                "runtime_grant_invalid",
                "Runtime Grant signature or claims are invalid",
            ) from exc
        bindings = {
            "azp": "agent-worker",
            "runtime_kind": request["runtime_kind"],
            "sub": request["app_user_id"],
            "job_id": request["job_id"],
            "invocation_id": request["invocation_id"],
            "agent_publication_id": request["agent_publication_id"],
            "application_publication_id": request["application_publication_id"],
            "request_digest": request["request_digest"],
        }
        if any(claims.get(key) != value for key, value in bindings.items()):
            raise RuntimeGrantError(
                "runtime_grant_binding_mismatch",
                "Runtime Grant is not bound to this execution request",
            )
        if int(claims["exp"]) - int(claims["iat"]) > min(
            int(request["limits"]["timeout_seconds"]) + 60,
            15 * 60,
        ):
            raise RuntimeGrantError(
                "runtime_grant_ttl_invalid",
                "Runtime Grant lifetime exceeds the execution boundary",
            )
        self._prune()
        jti = str(claims["jti"])
        previous = self._used_jti.get(jti)
        current = (
            str(request["invocation_id"]),
            str(request["request_digest"]),
            int(claims["exp"]),
        )
        if previous and previous[:2] != current[:2]:
            raise RuntimeGrantError(
                "runtime_grant_replayed",
                "Runtime Grant JTI was already used by another execution",
            )
        self._used_jti[jti] = current
        return claims

    def _prune(self) -> None:
        cutoff = self._now() - 5
        self._used_jti = {
            jti: binding for jti, binding in self._used_jti.items() if binding[2] >= cutoff
        }
