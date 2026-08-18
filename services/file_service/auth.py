from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Never

import jwt

from app.modules.identity.application.principal_jwt import (
    MAX_PRINCIPAL_TOKEN_BYTES,
    PrincipalJwks,
)
from app.modules.identity.application.service_principal import (
    DELIVERY_WORKER_AUTHORIZED_PARTY,
    DELIVERY_WORKER_SCOPES,
    FILE_PROCESSING_WORKER_AUTHORIZED_PARTY,
    FILE_PROCESSING_WORKER_SCOPES,
    FILE_SERVICE_INTERNAL_AUDIENCE,
    FILE_WORKER_AUTHORIZED_PARTY,
    FILE_WORKER_SCOPES,
    SERVICE_PRINCIPAL_ISSUER,
)
from app.shared.exceptions import NonRetryableExecutionError


FILE_PRINCIPAL_AUDIENCE = "file-service"
FILE_SERVICE_AUDIENCE = FILE_SERVICE_INTERNAL_AUDIENCE
PLATFORM_PRINCIPAL_ISSUER = "enterprise-agent-identity"
FILE_WORKER_ISSUER = SERVICE_PRINCIPAL_ISSUER
AGENT_RUNTIME_AUTHORIZED_PARTY = "agent-runtime"
MAX_TOKEN_TTL_SECONDS = 5 * 60


class FilePrincipalError(NonRetryableExecutionError):
    pass


class CachedPrincipalJwks:
    """Bounded file-backed JWKS cache with explicit refresh interval."""

    def __init__(
        self,
        path: str,
        *,
        refresh_seconds: int = 60,
        now: Callable[[], float] | None = None,
    ) -> None:
        if not path.strip() or not 1 <= refresh_seconds <= 3600:
            raise ValueError("File Service JWKS cache configuration is invalid")
        self.path = Path(path)
        self.refresh_seconds = refresh_seconds
        self._now = now or time.monotonic
        self._loaded_at = 0.0
        self._jwks: PrincipalJwks | None = None
        self._lock = threading.Lock()

    def get(self, kid: str) -> Any | None:
        return self.current().get(kid)

    def current(self) -> PrincipalJwks:
        now = self._now()
        with self._lock:
            if self._jwks is None or now - self._loaded_at >= self.refresh_seconds:
                self._jwks = PrincipalJwks.from_file(str(self.path))
                self._loaded_at = now
            return self._jwks


class FilePrincipalVerifier:
    _claims = frozenset(
        {
            "iss",
            "sub",
            "aud",
            "azp",
            "tenant_id",
            "job_id",
            "session_id",
            "agent_publication_id",
            "application_publication_id",
            "scope",
            "authorization_hash",
            "jti",
            "iat",
            "nbf",
            "exp",
        }
    )

    def __init__(
        self,
        jwks: PrincipalJwks | CachedPrincipalJwks,
        *,
        now: Callable[[], int] | None = None,
        leeway_seconds: int = 5,
    ) -> None:
        self.jwks = jwks
        self._now = now or (lambda: int(time.time()))
        self.leeway_seconds = leeway_seconds

    def verify(self, token: str, *, required_scopes: frozenset[str]) -> dict[str, Any]:
        return self._verify(
            token,
            issuer=PLATFORM_PRINCIPAL_ISSUER,
            audience=FILE_PRINCIPAL_AUDIENCE,
            authorized_party=AGENT_RUNTIME_AUTHORIZED_PARTY,
            allowed_claims=self._claims,
            required_scopes=required_scopes,
        )

    def _verify(
        self,
        token: str,
        *,
        issuer: str,
        audience: str,
        authorized_party: str,
        allowed_claims: frozenset[str],
        required_scopes: frozenset[str],
    ) -> dict[str, Any]:
        try:
            if not token or len(token.encode("ascii")) > MAX_PRINCIPAL_TOKEN_BYTES:
                self._deny("file_principal_token_invalid")
            header = jwt.get_unverified_header(token)
            if set(header) != {"alg", "kid", "typ"}:
                self._deny("file_principal_header_invalid")
            if header.get("alg") != "EdDSA" or header.get("typ") != "JWT":
                self._deny("file_principal_algorithm_invalid")
            key = self.jwks.get(str(header.get("kid") or ""))
            if key is None:
                self._deny("file_principal_kid_unknown")
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=["EdDSA"],
                audience=audience,
                issuer=issuer,
                options={
                    "require": sorted(allowed_claims),
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            if set(claims) != allowed_claims or claims.get("azp") != authorized_party:
                self._deny("file_principal_claims_invalid")
            self._validate_strings(claims, allowed_claims)
            scopes = claims.get("scope")
            if (
                not isinstance(scopes, list)
                or not scopes
                or len(scopes) != len(set(scopes))
                or any(not isinstance(value, str) or len(value) > 200 for value in scopes)
                or frozenset(scopes) != required_scopes
            ):
                self._deny("file_principal_scope_invalid")
            authorization_hash = str(claims.get("authorization_hash") or "")
            if len(authorization_hash) != 64 or any(
                character not in "0123456789abcdef" for character in authorization_hash
            ):
                self._deny("file_principal_authorization_hash_invalid")
            self._validate_time(claims)
            return dict(claims)
        except FilePrincipalError:
            raise
        except (jwt.PyJWTError, UnicodeError, ValueError, TypeError) as exc:
            raise FilePrincipalError(
                "File Principal JWT validation failed",
                safe_message="平台文件身份凭证无效",
                error_code="file_principal_token_invalid",
            ) from exc

    def _validate_time(self, claims: Mapping[str, Any]) -> None:
        if any(type(claims.get(name)) is not int for name in ("iat", "nbf", "exp")):
            self._deny("file_principal_time_invalid")
        issued_at = int(claims["iat"])
        not_before = int(claims["nbf"])
        expires_at = int(claims["exp"])
        now = self._now()
        if (
            issued_at > now + self.leeway_seconds
            or not_before > now + self.leeway_seconds
            or not_before > issued_at
            or expires_at <= now - self.leeway_seconds
            or expires_at <= issued_at
            or expires_at - issued_at > MAX_TOKEN_TTL_SECONDS
        ):
            self._deny("file_principal_time_invalid")

    @staticmethod
    def _validate_strings(claims: Mapping[str, Any], fields: frozenset[str]) -> None:
        for name in fields - {"scope", "iat", "nbf", "exp"}:
            value = claims.get(name)
            if not isinstance(value, str) or not value or len(value) > 256:
                FilePrincipalVerifier._deny("file_principal_claims_invalid")

    @staticmethod
    def _deny(code: str) -> Never:
        raise FilePrincipalError(
            "File Principal JWT denied",
            safe_message="平台文件身份凭证无效",
            error_code=code,
        )


class FileWorkerPrincipalVerifier(FilePrincipalVerifier):
    _service_claims = frozenset(
        {
            "iss",
            "sub",
            "aud",
            "azp",
            "scope",
            "authorization_hash",
            "jti",
            "iat",
            "nbf",
            "exp",
        }
    )

    def verify_service(self, token: str, *, required_scope: str) -> dict[str, Any]:
        if required_scope not in FILE_WORKER_SCOPES:
            self._deny("file_worker_scope_invalid")
        claims = self._verify(
            token,
            issuer=FILE_WORKER_ISSUER,
            audience=FILE_SERVICE_AUDIENCE,
            authorized_party=FILE_WORKER_AUTHORIZED_PARTY,
            allowed_claims=self._service_claims,
            required_scopes=FILE_WORKER_SCOPES,
        )
        if claims["sub"] != FILE_WORKER_AUTHORIZED_PARTY:
            self._deny("file_worker_subject_invalid")
        return claims

    def verify_delivery(self, token: str, *, required_scope: str) -> dict[str, Any]:
        if required_scope not in DELIVERY_WORKER_SCOPES:
            self._deny("file_delivery_scope_invalid")
        claims = self._verify(
            token,
            issuer=FILE_WORKER_ISSUER,
            audience=FILE_SERVICE_AUDIENCE,
            authorized_party=DELIVERY_WORKER_AUTHORIZED_PARTY,
            allowed_claims=self._service_claims,
            required_scopes=DELIVERY_WORKER_SCOPES,
        )
        if claims["sub"] != DELIVERY_WORKER_AUTHORIZED_PARTY:
            self._deny("file_delivery_subject_invalid")
        return claims

    def verify_processing(self, token: str, *, required_scope: str) -> dict[str, Any]:
        if required_scope not in FILE_PROCESSING_WORKER_SCOPES:
            self._deny("file_processing_worker_scope_invalid")
        claims = self._verify(
            token,
            issuer=FILE_WORKER_ISSUER,
            audience=FILE_SERVICE_AUDIENCE,
            authorized_party=FILE_PROCESSING_WORKER_AUTHORIZED_PARTY,
            allowed_claims=self._service_claims,
            required_scopes=FILE_PROCESSING_WORKER_SCOPES,
        )
        if claims["sub"] != FILE_PROCESSING_WORKER_AUTHORIZED_PARTY:
            self._deny("file_processing_worker_subject_invalid")
        return claims


def safe_token_projection(token: str) -> dict[str, str]:
    """Return bounded non-secret diagnostics without exposing claims or JWT bytes."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return {"credential": "invalid"}
    return {
        "credential": "configured",
        "kid_summary": str(header.get("kid") or "")[:12],
    }
