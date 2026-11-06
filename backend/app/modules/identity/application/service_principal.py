from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
import jwt
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.principal_jwt import (
    PrincipalJwks,
    PrincipalSigningKey,
)
from app.shared.principal_token_contract import MAX_PRINCIPAL_TOKEN_BYTES
from app.shared.service_identity_client import (
    ServicePrincipalTokenError as ServicePrincipalTokenError,
    AccessTokenProvider as AccessTokenProvider,
    ServicePrincipalTokenClient as ServicePrincipalTokenClient,
    ServiceIdentityExchangeTransport as ServiceIdentityExchangeTransport,
    UrllibServiceIdentityExchangeTransport as UrllibServiceIdentityExchangeTransport,
    MAX_SERVICE_PRINCIPAL_TTL_SECONDS as MAX_SERVICE_PRINCIPAL_TTL_SECONDS,
    SERVICE_PRINCIPAL_TOKEN_PATH as SERVICE_PRINCIPAL_TOKEN_PATH,
    _read_bootstrap_credential,
)


SERVICE_PRINCIPAL_ISSUER = "enterprise-agent-service-identity"
FILE_SERVICE_INTERNAL_AUDIENCE = "file-service-internal"
FILE_WORKER_AUTHORIZED_PARTY = "file-worker"
FILE_PROCESSING_WORKER_AUTHORIZED_PARTY = "file-processing-worker"
DELIVERY_WORKER_AUTHORIZED_PARTY = "delivery-worker"
FILE_WORKER_SCOPES = frozenset(
    {
        "internal:file-service:attachment:import",
        "internal:file-service:content:cleanup",
    }
)
FILE_PROCESSING_WORKER_SCOPES = frozenset(
    {
        "internal:file-service:document-processing:admission",
        "internal:file-service:document-processing:claim",
        "internal:file-service:document-processing:source:read",
        "internal:file-service:document-processing:representation:write",
        "internal:file-service:document-processing:complete",
        "internal:file-service:document-processing:heartbeat",
    }
)
DELIVERY_WORKER_SCOPES = frozenset({"internal:file-service:delivery:read"})
KNOWLEDGE_AUTHORIZED_PARTY = "knowledge-mcp"
KNOWLEDGE_BRIDGE_AUDIENCE = "knowledge-readability-bridge"
CODE_RUNTIME_AUTHORIZED_PARTY = "code-knowledge-runtime"
CODE_RUNTIME_AUDIENCE = "code-knowledge-control"
KNOWLEDGE_BRIDGE_SCOPES = frozenset(
    {
        "internal:knowledge:work-item:readability",
        "internal:knowledge:storage:connection",
        "internal:knowledge:principal:refresh",
    }
)


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
    FILE_PROCESSING_WORKER_AUTHORIZED_PARTY: ServicePrincipalGrant(
        subject=FILE_PROCESSING_WORKER_AUTHORIZED_PARTY,
        audience=FILE_SERVICE_INTERNAL_AUDIENCE,
        scopes=FILE_PROCESSING_WORKER_SCOPES,
    ),
    DELIVERY_WORKER_AUTHORIZED_PARTY: ServicePrincipalGrant(
        subject=DELIVERY_WORKER_AUTHORIZED_PARTY,
        audience=FILE_SERVICE_INTERNAL_AUDIENCE,
        scopes=DELIVERY_WORKER_SCOPES,
    ),
}
REQUIRED_SERVICE_PRINCIPAL_ROLES = frozenset(SERVICE_PRINCIPAL_GRANTS)
SERVICE_PRINCIPAL_GRANTS[KNOWLEDGE_AUTHORIZED_PARTY] = ServicePrincipalGrant(
    subject=KNOWLEDGE_AUTHORIZED_PARTY,
    audience=KNOWLEDGE_BRIDGE_AUDIENCE,
    scopes=KNOWLEDGE_BRIDGE_SCOPES,
)
SERVICE_PRINCIPAL_GRANTS[CODE_RUNTIME_AUTHORIZED_PARTY] = ServicePrincipalGrant(
    subject=CODE_RUNTIME_AUTHORIZED_PARTY,
    audience=CODE_RUNTIME_AUDIENCE,
    scopes=frozenset({"internal:code-knowledge:source-grant"}),
)


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
        if not (
            REQUIRED_SERVICE_PRINCIPAL_ROLES
            <= set(bootstrap_credentials)
            <= set(SERVICE_PRINCIPAL_GRANTS)
        ):
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
        file_processing_worker_bootstrap_file: str,
        delivery_worker_bootstrap_file: str,
        audit_service: AuditService,
        environment: str,
        ttl_seconds: int = MAX_SERVICE_PRINCIPAL_TTL_SECONDS,
        knowledge_bootstrap_file: str = "",
        code_runtime_bootstrap_file: str = "",
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
                FILE_PROCESSING_WORKER_AUTHORIZED_PARTY: _read_bootstrap_credential(
                    file_processing_worker_bootstrap_file,
                    label="File Processing Worker bootstrap credential",
                ),
                DELIVERY_WORKER_AUTHORIZED_PARTY: _read_bootstrap_credential(
                    delivery_worker_bootstrap_file,
                    label="Delivery Worker bootstrap credential",
                ),
                **(
                    {
                        KNOWLEDGE_AUTHORIZED_PARTY: _read_bootstrap_credential(
                            knowledge_bootstrap_file, label="Knowledge MCP bootstrap credential"
                        )
                    }
                    if knowledge_bootstrap_file
                    else {}
                ),
                **(
                    {
                        CODE_RUNTIME_AUTHORIZED_PARTY: _read_bootstrap_credential(
                            code_runtime_bootstrap_file, label="Code Runtime bootstrap credential"
                        )
                    }
                    if code_runtime_bootstrap_file
                    else {}
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


class _FixedServicePrincipalVerifier:
    authorized_party: str
    error_code: str

    def __init__(self, jwks: PrincipalJwks, *, now: Callable[[], int] | None = None) -> None:
        self.jwks = jwks
        self._now = now or (lambda: int(time.time()))

    def verify(self, token: str) -> None:
        grant = SERVICE_PRINCIPAL_GRANTS[self.authorized_party]
        try:
            if not 1 <= len(token.encode("ascii")) <= MAX_PRINCIPAL_TOKEN_BYTES:
                raise ValueError
            header = jwt.get_unverified_header(token)
            if (
                set(header) != {"alg", "kid", "typ"}
                or header.get("alg") != "EdDSA"
                or header.get("typ") != "JWT"
                or not isinstance(header.get("kid"), str)
            ):
                raise ValueError
            key = self.jwks.get(header["kid"])
            if key is None:
                raise ValueError
            fields = {
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
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=["EdDSA"],
                audience=grant.audience,
                issuer=SERVICE_PRINCIPAL_ISSUER,
                options={
                    "require": sorted(fields),
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            if (
                set(claims) != fields
                or claims["sub"] != grant.subject
                or claims["azp"] != grant.subject
                or claims["aud"] != grant.audience
                or claims["scope"] != sorted(grant.scopes)
                or claims["authorization_hash"] != _authorization_hash(grant)
                or not isinstance(claims["jti"], str)
                or not 1 <= len(claims["jti"]) <= 128
                or any(type(claims[name]) is not int for name in ("iat", "nbf", "exp"))
            ):
                raise ValueError
            now = self._now()
            if (
                claims["iat"] > now
                or claims["nbf"] > now
                or claims["nbf"] > claims["iat"]
                or claims["exp"] <= now
                or not 1 <= claims["exp"] - claims["iat"] <= MAX_SERVICE_PRINCIPAL_TTL_SECONDS
            ):
                raise ValueError
        except (jwt.PyJWTError, UnicodeError, ValueError, TypeError, KeyError):
            raise ServicePrincipalTokenError(
                "Internal service identity rejected",
                safe_message="内部服务身份无效",
                error_code=self.error_code,
            ) from None


class KnowledgeServicePrincipalVerifier(_FixedServicePrincipalVerifier):
    """Fixed knowledge service identity; grants no user or business-data permissions."""

    authorized_party = KNOWLEDGE_AUTHORIZED_PARTY
    error_code = "knowledge_service_identity_invalid"


class CodeRuntimeServicePrincipalVerifier(_FixedServicePrincipalVerifier):
    """Fixed Runtime control identity; source access still requires a bound live Job."""

    authorized_party = CODE_RUNTIME_AUTHORIZED_PARTY
    error_code = "code_runtime_identity_invalid"
