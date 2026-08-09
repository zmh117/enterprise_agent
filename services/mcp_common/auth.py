from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Literal

import jwt
from pydantic import ValidationError

from services.mcp_common.contracts import McpAudience, McpTokenClaims


_ISSUER = "enterprise-agent"
_AUTHORIZED_PARTY: Literal["agent-worker"] = "agent-worker"
_MAX_TOKEN_SECONDS = 15 * 60
_MIN_KEY_BYTES = 32
_MAX_KEY_BYTES = 4096


class McpAuthenticationError(RuntimeError):
    """Stable authentication failure that never includes token material."""


def load_signing_key(path: str) -> bytes:
    configured = path.strip()
    if not configured:
        raise McpAuthenticationError("MCP token signing key file is required")
    key_path = Path(configured)
    try:
        size = key_path.stat().st_size
        key = key_path.read_bytes()
    except OSError as exc:
        raise McpAuthenticationError("MCP token signing key file is unreadable") from exc
    if size != len(key) or not _MIN_KEY_BYTES <= len(key) <= _MAX_KEY_BYTES:
        raise McpAuthenticationError("MCP token signing key has an invalid size")
    if key.endswith(b"\n"):
        key = key.rstrip(b"\r\n")
    if len(key) < _MIN_KEY_BYTES:
        raise McpAuthenticationError("MCP token signing key is too short")
    return key


class McpTokenIssuer:
    def __init__(self, key: bytes) -> None:
        if len(key) < _MIN_KEY_BYTES:
            raise ValueError("MCP signing key must contain at least 32 bytes")
        self._key = key

    @classmethod
    def from_file(cls, path: str) -> McpTokenIssuer:
        return cls(load_signing_key(path))

    def issue(
        self,
        *,
        audience: McpAudience,
        app_user_id: str,
        job_id: str,
        application_publication_id: str,
        scopes: Iterable[str],
        job_timeout_seconds: int,
        now: datetime | None = None,
    ) -> str:
        issued_at = now or datetime.now(UTC)
        ttl_seconds = min(max(1, int(job_timeout_seconds) + 60), _MAX_TOKEN_SECONDS)
        ordered_scopes = tuple(dict.fromkeys(str(scope) for scope in scopes))
        claims = McpTokenClaims(
            iss=_ISSUER,
            aud=audience,
            sub=app_user_id,
            azp=_AUTHORIZED_PARTY,
            job_id=job_id,
            application_publication_id=application_publication_id,
            scopes=ordered_scopes,
            iat=int(issued_at.timestamp()),
            exp=int((issued_at + timedelta(seconds=ttl_seconds)).timestamp()),
            jti=secrets.token_urlsafe(24),
        )
        return str(jwt.encode(claims.model_dump(), self._key, algorithm="HS256"))


class McpTokenVerifier:
    def __init__(self, key: bytes, *, audience: McpAudience) -> None:
        if len(key) < _MIN_KEY_BYTES:
            raise ValueError("MCP signing key must contain at least 32 bytes")
        self._key = key
        self._audience = audience

    @classmethod
    def from_file(cls, path: str, *, audience: McpAudience) -> McpTokenVerifier:
        return cls(load_signing_key(path), audience=audience)

    def verify(self, token: str, *, required_scope: str | None = None) -> McpTokenClaims:
        if not token or len(token) > 8192:
            raise McpAuthenticationError("MCP access token is missing or invalid")
        try:
            payload = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=_ISSUER,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "azp",
                        "job_id",
                        "application_publication_id",
                        "scopes",
                        "iat",
                        "exp",
                        "jti",
                    ]
                },
            )
            claims = McpTokenClaims.model_validate(payload)
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError) as exc:
            raise McpAuthenticationError("MCP access token is invalid") from exc
        if claims.aud != self._audience or claims.azp != _AUTHORIZED_PARTY:
            raise McpAuthenticationError("MCP access token is not valid for this service")
        if claims.exp - claims.iat > _MAX_TOKEN_SECONDS:
            raise McpAuthenticationError("MCP access token lifetime exceeds policy")
        if required_scope and required_scope not in claims.scopes:
            raise McpAuthenticationError("MCP access token scope is insufficient")
        return claims


def signing_key_path_from_environment() -> str:
    return os.environ.get("MCP_TOKEN_SIGNING_KEY_FILE", "").strip()
