from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.identity.api import build_service_principal_router
from app.modules.identity.application.principal_jwt import PrincipalJwks, PrincipalSigningKey
from app.modules.identity.application.service_principal import (
    DELIVERY_WORKER_AUTHORIZED_PARTY,
    FILE_PROCESSING_WORKER_AUTHORIZED_PARTY,
    FILE_PROCESSING_WORKER_SCOPES,
    FILE_SERVICE_INTERNAL_AUDIENCE,
    FILE_WORKER_AUTHORIZED_PARTY,
    FILE_WORKER_SCOPES,
    SERVICE_PRINCIPAL_ISSUER,
    ServicePrincipalTokenClient,
    ServicePrincipalTokenError,
    ServicePrincipalTokenIssuer,
)
from app.shared.exceptions import RetryableExecutionError
from services.file_service.auth import (
    FilePrincipalError,
    FilePrincipalVerifier,
    FileWorkerPrincipalVerifier,
)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event_type: str, **values: object) -> str:
        self.events.append({"event_type": event_type, **values})
        return "audit-id"


def _signing_key() -> PrincipalSigningKey:
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return PrincipalSigningKey.from_pem(pem)


def _issuer(*, now: int = 1_900_000_000) -> tuple[ServicePrincipalTokenIssuer, _Audit]:
    audit = _Audit()
    issuer = ServicePrincipalTokenIssuer(
        signing_key=_signing_key(),
        bootstrap_credentials={
            FILE_WORKER_AUTHORIZED_PARTY: "f" * 48,
            FILE_PROCESSING_WORKER_AUTHORIZED_PARTY: "p" * 48,
            DELIVERY_WORKER_AUTHORIZED_PARTY: "d" * 48,
        },
        audit_service=audit,  # type: ignore[arg-type]
        now=lambda: now,
        jti_factory=lambda: "service-jti",
    )
    return issuer, audit


def test_issuer_produces_exact_role_bound_file_worker_token() -> None:
    issuer, audit = _issuer()
    issued = issuer.issue("f" * 48)
    public_key = PrincipalJwks.from_dict(issuer.signing_key.public_jwks()).get(
        issuer.signing_key.kid
    )
    assert public_key is not None
    claims = jwt.decode(
        issued.access_token,
        key=public_key.key,
        algorithms=["EdDSA"],
        audience=FILE_SERVICE_INTERNAL_AUDIENCE,
        issuer=SERVICE_PRINCIPAL_ISSUER,
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )

    assert claims["sub"] == FILE_WORKER_AUTHORIZED_PARTY
    assert claims["azp"] == FILE_WORKER_AUTHORIZED_PARTY
    assert frozenset(claims["scope"]) == FILE_WORKER_SCOPES
    assert claims["exp"] - claims["iat"] == 300
    assert issued.token_type == "Bearer"
    assert issued.expires_in == 300
    assert audit.events[-1]["event_type"] == "service_principal_token_issued"
    assert issued.access_token not in json.dumps(audit.events)


def test_bootstrap_credentials_cannot_cross_roles_or_appear_in_audit() -> None:
    issuer, audit = _issuer()
    with pytest.raises(ServicePrincipalTokenError):
        issuer.issue("x" * 48)
    assert "x" * 48 not in json.dumps(audit.events)


def test_file_worker_verifier_requires_full_fixed_role_scope_set() -> None:
    issuer, _ = _issuer()
    token = issuer.issue("f" * 48).access_token
    verifier = FileWorkerPrincipalVerifier(
        PrincipalJwks.from_dict(issuer.signing_key.public_jwks()),
        now=lambda: 1_900_000_001,
    )

    claims = verifier.verify_service(
        token,
        required_scope="internal:file-service:attachment:import",
    )
    assert frozenset(claims["scope"]) == FILE_WORKER_SCOPES

    wrong_scope_token = issuer.signing_key.sign(
        {
            **{key: value for key, value in claims.items() if key != "scope"},
            "scope": ["internal:file-service:attachment:import"],
        }
    )
    with pytest.raises(FilePrincipalError):
        verifier.verify_service(
            wrong_scope_token,
            required_scope="internal:file-service:attachment:import",
        )


def test_file_processing_worker_has_a_distinct_exact_scope_set() -> None:
    issuer, _ = _issuer()
    token = issuer.issue("p" * 48).access_token
    verifier = FileWorkerPrincipalVerifier(
        PrincipalJwks.from_dict(issuer.signing_key.public_jwks()),
        now=lambda: 1_900_000_001,
    )

    claims = verifier.verify_processing(
        token,
        required_scope="internal:file-service:document-processing:source:read",
    )
    assert claims["sub"] == FILE_PROCESSING_WORKER_AUTHORIZED_PARTY
    assert frozenset(claims["scope"]) == FILE_PROCESSING_WORKER_SCOPES
    with pytest.raises(FilePrincipalError):
        verifier.verify_service(
            token,
            required_scope="internal:file-service:attachment:import",
        )


def test_shared_principal_jwks_does_not_blur_job_and_service_token_domains() -> None:
    signing_key = _signing_key()
    jwks = PrincipalJwks.from_dict(signing_key.public_jwks())
    audit = _Audit()
    service_issuer = ServicePrincipalTokenIssuer(
        signing_key=signing_key,
        bootstrap_credentials={
            FILE_WORKER_AUTHORIZED_PARTY: "f" * 48,
            FILE_PROCESSING_WORKER_AUTHORIZED_PARTY: "p" * 48,
            DELIVERY_WORKER_AUTHORIZED_PARTY: "d" * 48,
        },
        audit_service=audit,  # type: ignore[arg-type]
        now=lambda: 1_900_000_000,
        jti_factory=lambda: "service-jti",
    )
    service_token = service_issuer.issue("f" * 48).access_token
    file_principal_verifier = FilePrincipalVerifier(
        jwks,
        now=lambda: 1_900_000_001,
    )
    with pytest.raises(FilePrincipalError):
        file_principal_verifier.verify(
            service_token,
            required_scopes=frozenset({"file:workspace:read"}),
        )

    job_token = signing_key.sign(
        {
            "iss": "enterprise-agent-identity",
            "sub": "user-a",
            "aud": "file-service",
            "azp": "agent-runtime",
            "tenant_id": "tenant-a",
            "job_id": "job-a",
            "session_id": "session-a",
            "agent_publication_id": "agent-publication-a",
            "application_publication_id": "application-publication-a",
            "scope": ["file:workspace:read"],
            "authorization_hash": "a" * 64,
            "jti": "job-jti",
            "iat": 1_900_000_000,
            "nbf": 1_900_000_000,
            "exp": 1_900_000_300,
        }
    )
    service_verifier = FileWorkerPrincipalVerifier(
        jwks,
        now=lambda: 1_900_000_001,
    )
    with pytest.raises(FilePrincipalError):
        service_verifier.verify_service(
            job_token,
            required_scope="internal:file-service:attachment:import",
        )


def test_internal_exchange_is_no_store_and_rejects_wrong_bootstrap() -> None:
    issuer, audit = _issuer()
    app = FastAPI()
    app.state.container = SimpleNamespace(
        service_principal_token_issuer=issuer,
        audit_service=audit,
    )
    app.include_router(build_service_principal_router())
    client = TestClient(app)

    response = client.post(
        "/api/internal/service-principal/token",
        headers={"Authorization": f"Bearer {'f' * 48}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}

    denied = client.post(
        "/api/internal/service-principal/token",
        headers={"Authorization": f"Bearer {'x' * 48}"},
    )
    assert denied.status_code == 401
    assert "x" * 48 not in json.dumps(audit.events)


class _Exchange:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def exchange(self, **values: object) -> dict[str, object]:
        del values
        self.calls += 1
        if self.fail:
            raise RetryableExecutionError("temporary")
        return {
            "access_token": f"token-{self.calls}",
            "token_type": "Bearer",
            "expires_in": 300,
        }


def test_worker_client_caches_refreshes_and_uses_still_valid_token_on_outage(
    tmp_path: Path,
) -> None:
    credential = tmp_path / "bootstrap"
    credential.write_text("b" * 48, encoding="ascii")
    credential.chmod(0o400)
    clock = [1000.0]
    exchange = _Exchange()
    client = ServicePrincipalTokenClient(
        base_url="http://api-server:8000",
        allowed_hosts=("api-server",),
        bootstrap_credential_file=str(credential),
        refresh_skew_seconds=60,
        transport=exchange,
        now=lambda: clock[0],
    )

    assert client.access_token() == "token-1"
    assert client.access_token() == "token-1"
    assert exchange.calls == 1

    clock[0] = 1241.0
    exchange.fail = True
    assert client.access_token() == "token-1"
    clock[0] = 1296.0
    with pytest.raises(RetryableExecutionError):
        client.access_token()
