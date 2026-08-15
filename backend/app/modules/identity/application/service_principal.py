from __future__ import annotations

import hashlib
import hmac
import json
import stat
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.principal_jwt import (
    MAX_PRINCIPAL_TOKEN_BYTES,
    PrincipalSigningKey,
)
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


SERVICE_PRINCIPAL_ISSUER = "enterprise-agent-service-identity"
FILE_SERVICE_INTERNAL_AUDIENCE = "file-service-internal"
FILE_WORKER_AUTHORIZED_PARTY = "file-worker"
DELIVERY_WORKER_AUTHORIZED_PARTY = "delivery-worker"
FILE_WORKER_SCOPES = frozenset(
    {
        "internal:file-service:attachment:import",
        "internal:file-service:content:cleanup",
    }
)
DELIVERY_WORKER_SCOPES = frozenset(
    {"internal:file-service:delivery:read"}
)
MAX_SERVICE_PRINCIPAL_TTL_SECONDS = 5 * 60
SERVICE_PRINCIPAL_TOKEN_PATH = "/api/internal/service-principal/token"


class ServicePrincipalTokenError(NonRetryableExecutionError):
    """Fail-closed service identity error without credential disclosure."""


class AccessTokenProvider(Protocol):
    def access_token(self) -> str: ...


@dataclass(frozen=True)
class ServicePrincipalGrant:
    subject: str
    audience: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class IssuedServicePrincipalToken:
    access_token: str
    token_type: str
    expires_in: int


SERVICE_PRINCIPAL_GRANTS = {
    FILE_WORKER_AUTHORIZED_PARTY: ServicePrincipalGrant(
        subject=FILE_WORKER_AUTHORIZED_PARTY,
        audience=FILE_SERVICE_INTERNAL_AUDIENCE,
        scopes=FILE_WORKER_SCOPES,
    ),
    DELIVERY_WORKER_AUTHORIZED_PARTY: ServicePrincipalGrant(
        subject=DELIVERY_WORKER_AUTHORIZED_PARTY,
        audience=FILE_SERVICE_INTERNAL_AUDIENCE,
        scopes=DELIVERY_WORKER_SCOPES,
    ),
}


def _read_bootstrap_credential(path: str, *, label: str) -> str:
    configured = path.strip()
    if not configured:
        raise ValueError(f"{label} file is required")
    file_path = Path(configured)
    try:
        metadata = file_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} file must be a regular non-symlink file")
        if not 32 <= metadata.st_size <= 4096:
            raise ValueError(f"{label} file size is invalid")
        mode = stat.S_IMODE(metadata.st_mode)
        if str(file_path).startswith("/run/secrets/"):
            if mode & 0o222:
                raise ValueError(f"{label} container file must be read-only")
        elif mode & 0o077:
            raise ValueError(f"{label} file permissions must be owner-only")
        raw = file_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} file is unreadable") from exc
    try:
        credential = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be ASCII") from exc
    if credential != credential.strip() or any(character.isspace() for character in credential):
        raise ValueError(f"{label} format is invalid")
    return credential


def _authorization_hash(grant: ServicePrincipalGrant) -> str:
    canonical = json.dumps(
        {
            "audience": grant.audience,
            "scopes": sorted(grant.scopes),
            "subject": grant.subject,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ServicePrincipalTokenIssuer:
    def __init__(
        self,
        *,
        signing_key: PrincipalSigningKey,
        bootstrap_credentials: Mapping[str, str],
        audit_service: AuditService,
        ttl_seconds: int = MAX_SERVICE_PRINCIPAL_TTL_SECONDS,
        now: Callable[[], int] | None = None,
        jti_factory: Callable[[], str] | None = None,
    ) -> None:
        if not 1 <= ttl_seconds <= MAX_SERVICE_PRINCIPAL_TTL_SECONDS:
            raise ValueError("Service Principal TTL is invalid")
        if set(bootstrap_credentials) != set(SERVICE_PRINCIPAL_GRANTS):
            raise ValueError("Service Principal bootstrap roles are incomplete")
        values = tuple(bootstrap_credentials.values())
        if len(values) != len(set(values)) or any(not value for value in values):
            raise ValueError("Service Principal bootstrap credentials must be distinct")
        self.signing_key = signing_key
        self._bootstrap_credentials = dict(bootstrap_credentials)
        self.audit_service = audit_service
        self.ttl_seconds = ttl_seconds
        self._now = now or (lambda: int(time.time()))
        self._jti_factory = jti_factory or (lambda: str(uuid.uuid4()))

    @classmethod
    def from_files(
        cls,
        *,
        signing_private_key_file: str,
        file_worker_bootstrap_file: str,
        delivery_worker_bootstrap_file: str,
        audit_service: AuditService,
        environment: str,
        ttl_seconds: int = MAX_SERVICE_PRINCIPAL_TTL_SECONDS,
    ) -> ServicePrincipalTokenIssuer:
        return cls(
            signing_key=PrincipalSigningKey.from_file(
                signing_private_key_file,
                environment=environment,
            ),
            bootstrap_credentials={
                FILE_WORKER_AUTHORIZED_PARTY: _read_bootstrap_credential(
                    file_worker_bootstrap_file,
                    label="File Worker bootstrap credential",
                ),
                DELIVERY_WORKER_AUTHORIZED_PARTY: _read_bootstrap_credential(
                    delivery_worker_bootstrap_file,
                    label="Delivery Worker bootstrap credential",
                ),
            },
            audit_service=audit_service,
            ttl_seconds=ttl_seconds,
        )

    def issue(self, bootstrap_credential: str) -> IssuedServicePrincipalToken:
        matched_role: str | None = None
        supplied = bootstrap_credential.encode("utf-8")
        for role, expected in self._bootstrap_credentials.items():
            if hmac.compare_digest(supplied, expected.encode("utf-8")):
                matched_role = role
        if matched_role is None:
            self.audit_service.record(
                "service_principal_token_denied",
                status="denied",
                summary="Service Principal bootstrap credential was rejected",
                payload={"reason": "credential_invalid"},
            )
            raise ServicePrincipalTokenError(
                "Service Principal bootstrap credential was rejected",
                safe_message="内部服务身份凭证无效",
                error_code="service_principal_bootstrap_invalid",
            )

        grant = SERVICE_PRINCIPAL_GRANTS[matched_role]
        issued_at = self._now()
        jti = self._jti_factory()
        claims = {
            "iss": SERVICE_PRINCIPAL_ISSUER,
            "sub": grant.subject,
            "aud": grant.audience,
            "azp": grant.subject,
            "scope": sorted(grant.scopes),
            "authorization_hash": _authorization_hash(grant),
            "jti": jti,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": issued_at + self.ttl_seconds,
        }
        token = self.signing_key.sign(claims)
        self.audit_service.record(
            "service_principal_token_issued",
            status="success",
            summary=f"Issued short-lived Service Principal token for {matched_role}",
            actor_id=matched_role,
            payload={
                "audience": grant.audience,
                "authorized_party": matched_role,
                "jti": jti,
                "kid": self.signing_key.kid,
                "scopes": sorted(grant.scopes),
                "ttl_seconds": self.ttl_seconds,
            },
        )
        return IssuedServicePrincipalToken(
            access_token=token,
            token_type="Bearer",
            expires_in=self.ttl_seconds,
        )


class ServiceIdentityExchangeTransport(Protocol):
    def exchange(
        self,
        *,
        url: str,
        bootstrap_credential: str,
        timeout_seconds: int,
    ) -> Mapping[str, Any]: ...


class UrllibServiceIdentityExchangeTransport:
    def exchange(
        self,
        *,
        url: str,
        bootstrap_credential: str,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        request = urllib.request.Request(
            url,
            data=b"",
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bootstrap_credential}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read(64 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise ServicePrincipalTokenError(
                    "Service identity exchange was rejected",
                    safe_message="内部服务身份凭证无效",
                    error_code="service_principal_exchange_denied",
                ) from exc
            raise RetryableExecutionError(
                "Service identity exchange failed",
                safe_message="内部身份服务暂时不可用",
                error_code="service_identity_unavailable",
            ) from exc
        except (OSError, TimeoutError) as exc:
            raise RetryableExecutionError(
                "Service identity exchange failed",
                safe_message="内部身份服务暂时不可用",
                error_code="service_identity_unavailable",
            ) from exc
        if len(payload) > 64 * 1024:
            raise RetryableExecutionError(
                "Service identity response exceeded its bound",
                safe_message="内部身份服务响应无效",
                error_code="service_identity_response_invalid",
            )
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RetryableExecutionError(
                "Service identity response is invalid",
                safe_message="内部身份服务响应无效",
                error_code="service_identity_response_invalid",
            ) from exc
        if not isinstance(value, dict):
            raise RetryableExecutionError(
                "Service identity response is invalid",
                safe_message="内部身份服务响应无效",
                error_code="service_identity_response_invalid",
            )
        return value


class ServicePrincipalTokenClient:
    """Role-local bootstrap exchange with bounded short-token caching."""

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        bootstrap_credential_file: str,
        timeout_seconds: int = 5,
        refresh_skew_seconds: int = 60,
        transport: ServiceIdentityExchangeTransport | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Service identity endpoint is invalid")
        if not bootstrap_credential_file or not 1 <= timeout_seconds <= 120:
            raise ValueError("Service identity client settings are invalid")
        if not 0 <= refresh_skew_seconds < MAX_SERVICE_PRINCIPAL_TTL_SECONDS:
            raise ValueError("Service identity refresh skew is invalid")
        self.url = base_url.rstrip("/") + SERVICE_PRINCIPAL_TOKEN_PATH
        self.bootstrap_credential_file = bootstrap_credential_file
        self.timeout_seconds = timeout_seconds
        self.refresh_skew_seconds = refresh_skew_seconds
        self.transport = transport or UrllibServiceIdentityExchangeTransport()
        self._now = now or time.monotonic
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            "ServicePrincipalTokenClient("
            f"url={self.url!r}, credential=<hidden>, token=<hidden>)"
        )

    def access_token(self) -> str:
        now = self._now()
        if self._token and now < self._expires_at - self.refresh_skew_seconds:
            return self._token
        with self._lock:
            now = self._now()
            if self._token and now < self._expires_at - self.refresh_skew_seconds:
                return self._token
            try:
                response = self.transport.exchange(
                    url=self.url,
                    bootstrap_credential=_read_bootstrap_credential(
                        self.bootstrap_credential_file,
                        label="Service bootstrap credential",
                    ),
                    timeout_seconds=self.timeout_seconds,
                )
                token = response.get("access_token")
                token_type = response.get("token_type")
                expires_in = response.get("expires_in")
                if (
                    not isinstance(token, str)
                    or not token
                    or len(token.encode("ascii")) > MAX_PRINCIPAL_TOKEN_BYTES
                    or token_type != "Bearer"
                    or type(expires_in) is not int
                    or not 1 <= expires_in <= MAX_SERVICE_PRINCIPAL_TTL_SECONDS
                ):
                    raise ValueError("Service identity token response is invalid")
            except RetryableExecutionError:
                if self._token and self._now() < self._expires_at - 5:
                    return self._token
                raise
            except (UnicodeError, ValueError) as exc:
                raise RetryableExecutionError(
                    "Service identity response is invalid",
                    safe_message="内部身份服务响应无效",
                    error_code="service_identity_response_invalid",
                ) from exc
            self._token = token
            self._expires_at = now + expires_in
            return token
