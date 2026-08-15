from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.modules.identity.application.principal_jwt import (
    FILE_PRINCIPAL_AUDIENCE,
    ONES_SEARCH_SCOPE,
    PRINCIPAL_AUDIENCE,
    PRINCIPAL_AUTHORIZED_PARTY,
    PRINCIPAL_ISSUER,
    PrincipalJwks,
    PrincipalSigningKey,
    PrincipalTokenError,
    PrincipalTokenIssuer,
    PrincipalTokenVerifier,
    write_public_jwks_file,
)
from app.shared.exceptions import PermissionDenied


NOW = 1_786_400_000


def _key() -> tuple[PrincipalSigningKey, bytes]:
    raw = Ed25519PrivateKey.generate()
    pem = raw.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return PrincipalSigningKey.from_pem(pem), pem


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        event_type: str,
        *,
        status: str,
        summary: str,
        job_id: str | None = None,
        actor_id: str | None = None,
        payload: Any | None = None,
    ) -> str:
        self.events.append(
            {
                "event_type": event_type,
                "status": status,
                "summary": summary,
                "job_id": job_id,
                "actor_id": actor_id,
                "payload": payload,
            }
        )
        return f"audit-{len(self.events)}"


class _Database:
    def __init__(self, **overrides: str) -> None:
        self.row = {
            "id": "job-1",
            "status": "RUNNING",
            "session_id": "session-1",
            "project_code": "default",
            "internal_user_id": "user-1",
            "business_application_id": "application-1",
            "agent_publication_id": "agent-publication-1",
            "business_application_publication_id": "application-publication-1",
            "user_status": "enabled",
            "user_account_type": "human",
            "session_application_publication_id": "application-publication-1",
            **overrides,
        }

    def execute_one(self, query: str, parameters: object) -> dict[str, str] | None:
        del query, parameters
        return dict(self.row)


class _Snapshot:
    def __init__(self) -> None:
        self.value: dict[str, Any] = {
            "authorization_hash": "a" * 64,
            "snapshot": {
                "job_id": "job-1",
                "agent_publication_id": "agent-publication-1",
                "application_publication_id": "application-publication-1",
                "tools": [
                    {
                        "server_code": "ones-mcp",
                        "tool_identifier": "ones_work_item_search",
                        "schema_hash": "b" * 64,
                    }
                ],
            },
        }

    def verify(self, job_id: str) -> dict[str, Any]:
        assert job_id == "job-1"
        return self.value


class _BusinessAuthorization:
    def __init__(self, *, denied: bool = False) -> None:
        self.denied = denied
        self.calls: list[dict[str, str]] = []

    def require(self, **kwargs: str) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        if self.denied:
            raise PermissionDenied(
                "denied",
                safe_message="无权调用 ONES 查询",
                error_code="business_application_denied",
            )
        return {"allowed": True, **kwargs}


def _issuer(
    *,
    database: _Database | None = None,
    snapshot: _Snapshot | None = None,
    authorization: _BusinessAuthorization | None = None,
    audit: _Audit | None = None,
) -> tuple[PrincipalTokenIssuer, PrincipalSigningKey, _Audit, _BusinessAuthorization]:
    signing_key, _ = _key()
    audit = audit or _Audit()
    authorization = authorization or _BusinessAuthorization()
    issuer = PrincipalTokenIssuer(
        database or _Database(),  # type: ignore[arg-type]
        snapshot or _Snapshot(),  # type: ignore[arg-type]
        authorization,
        signing_key,
        audit,  # type: ignore[arg-type]
        now=lambda: NOW,
        jti_factory=lambda: "principal-jti-1",
    )
    return issuer, signing_key, audit, authorization


def _claims() -> dict[str, Any]:
    return {
        "iss": PRINCIPAL_ISSUER,
        "sub": "user-1",
        "aud": PRINCIPAL_AUDIENCE,
        "azp": PRINCIPAL_AUTHORIZED_PARTY,
        "job_id": "job-1",
        "session_id": "session-1",
        "agent_publication_id": "agent-publication-1",
        "application_publication_id": "application-publication-1",
        "scope": [ONES_SEARCH_SCOPE],
        "authorization_hash": "a" * 64,
        "jti": "principal-jti-1",
        "iat": NOW,
        "nbf": NOW - 1,
        "exp": NOW + 300,
    }


def _sign(pem: bytes, claims: dict[str, Any], *, kid: str, alg: str = "EdDSA") -> str:
    return str(
        jwt.encode(
            claims,
            pem if alg == "EdDSA" else b"test-hmac-key-that-is-not-a-public-key",
            algorithm=alg,
            headers={"alg": alg, "kid": kid, "typ": "JWT"},
        )
    )


def test_private_key_jwks_fingerprint_rotation_and_file_permissions(tmp_path: Path) -> None:
    active, active_pem = _key()
    previous, _ = _key()
    private_path = tmp_path / "principal-private.pem"
    private_path.write_bytes(active_pem)
    private_path.chmod(0o600)

    loaded = PrincipalSigningKey.from_file(str(private_path), environment="production")
    assert loaded.kid == active.kid
    assert "PRIVATE KEY" not in repr(loaded)
    assert "d" not in loaded.public_jwk()

    jwks_path = tmp_path / "principal-jwks.json"
    jwks_path.write_text(
        json.dumps({"keys": [active.public_jwk(), previous.public_jwk()]}),
        encoding="utf-8",
    )
    jwks = PrincipalJwks.from_file(str(jwks_path))
    assert jwks.get(active.kid) is not None
    assert jwks.get(previous.kid) is not None
    assert jwks.public_projection() == {
        "keys": sorted(
            [active.public_jwk(), previous.public_jwk()],
            key=lambda value: value["kid"],
        )
    }

    public_path = tmp_path / "published" / "principal-jwks.json"
    write_public_jwks_file(active, str(public_path))
    assert PrincipalJwks.from_file(str(public_path)).get(active.kid) is not None
    assert "PRIVATE" not in public_path.read_text(encoding="utf-8")

    private_path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        PrincipalSigningKey.from_file(str(private_path), environment="production")

    target = tmp_path / "real-private.pem"
    target.write_bytes(active_pem)
    target.chmod(0o600)
    symlink = tmp_path / "linked-private.pem"
    os.symlink(target, symlink)
    with pytest.raises(ValueError, match="non-symlink"):
        PrincipalSigningKey.from_file(str(symlink), environment="production")


def test_jwks_rejects_private_wrong_fingerprint_duplicate_and_non_ed25519() -> None:
    signing_key, _ = _key()
    valid = signing_key.public_jwk()
    with pytest.raises(ValueError, match="private or unsupported"):
        PrincipalJwks.from_dict({"keys": [{**valid, "d": "forbidden"}]})
    with pytest.raises(ValueError, match="fingerprint"):
        PrincipalJwks.from_dict({"keys": [{**valid, "kid": "wrong"}]})
    with pytest.raises(ValueError, match="unique"):
        PrincipalJwks.from_dict({"keys": [valid, valid]})
    with pytest.raises(ValueError, match="Ed25519"):
        PrincipalJwks.from_dict({"keys": [{**valid, "crv": "X25519"}]})


def test_issuer_derives_bounded_claims_from_snapshot_and_current_application_grant() -> None:
    issuer, signing_key, audit, authorization = _issuer()
    token = issuer.issue_for_job(job_id="job-1")
    claims = jwt.decode(token, options={"verify_signature": False})
    header = jwt.get_unverified_header(token)

    assert header == {"alg": "EdDSA", "kid": signing_key.kid, "typ": "JWT"}
    assert claims == _claims()
    assert claims["exp"] - claims["iat"] == 300
    assert authorization.calls == [
        {
            "user_id": "user-1",
            "application_id": "application-1",
            "tool_identifier": "ones_work_item_search",
            "stage": "principal_jwt_issue",
        }
    ]
    assert audit.events[-1]["event_type"] == "principal.jwt.issued"
    audit_text = json.dumps(audit.events, sort_keys=True)
    assert token not in audit_text
    for forbidden in ("identity_id", "credential", "email", "password", "team", "token"):
        assert forbidden not in claims
    verifier = PrincipalTokenVerifier(
        PrincipalJwks.from_dict(signing_key.public_jwks()),
        now=lambda: NOW,
    )
    assert verifier.verify(token) == claims


def test_issuer_creates_a_separate_audience_bound_file_principal() -> None:
    snapshot = _Snapshot()
    snapshot.value["snapshot"]["tools"] = [
        {
            "server_code": "file-service",
            "tool_identifier": "file_prepare_materialization",
            "schema_hash": "c" * 64,
        },
        {
            "server_code": "file-service",
            "tool_identifier": "file_create_commit_intent",
            "schema_hash": "d" * 64,
        },
    ]
    issuer, signing_key, audit, authorization = _issuer(
        database=_Database(
            task_workspace_id="workspace-1",
            workspace_tenant_id="tenant-1",
        ),
        snapshot=snapshot,
    )

    token = issuer.issue_file_for_job(job_id="job-1")
    claims = jwt.decode(token, options={"verify_signature": False})

    assert jwt.get_unverified_header(token) == {
        "alg": "EdDSA",
        "kid": signing_key.kid,
        "typ": "JWT",
    }
    assert claims["aud"] == FILE_PRINCIPAL_AUDIENCE
    assert claims["tenant_id"] == "tenant-1"
    assert claims["job_id"] == "job-1"
    assert claims["scope"] == [
        "mcp:file-service:file_create_commit_intent:invoke",
        "mcp:file-service:file_prepare_materialization:invoke",
    ]
    assert {call["tool_identifier"] for call in authorization.calls} == {
        "file_create_commit_intent",
        "file_prepare_materialization",
    }
    assert all(call["stage"] == "file_principal_jwt_issue" for call in authorization.calls)
    assert audit.events[-1]["summary"] == (
        "Principal JWT issued for frozen File MCP Tools"
    )
    assert token not in json.dumps(audit.events)


def test_file_principal_issuance_requires_a_job_bound_workspace() -> None:
    snapshot = _Snapshot()
    snapshot.value["snapshot"]["tools"] = [
        {
            "server_code": "file-service",
            "tool_identifier": "task_workspace_get",
            "schema_hash": "c" * 64,
        }
    ]
    issuer, _signing_key, audit, _authorization = _issuer(snapshot=snapshot)

    with pytest.raises(PrincipalTokenError) as captured:
        issuer.issue_file_for_job(job_id="job-1")

    assert captured.value.error_code == "file_principal_workspace_missing"
    assert audit.events[-1]["event_type"] == "principal.jwt.issue_denied"

@pytest.mark.parametrize(
    ("database", "mutate_snapshot", "denied", "error_code"),
    [
        (_Database(status="PENDING"), None, False, "principal_job_not_running"),
        (_Database(user_status="disabled"), None, False, "principal_user_inactive"),
        (_Database(user_account_type="service"), None, False, "principal_user_inactive"),
        (_Database(business_application_id=""), None, False, "principal_job_invalid"),
        (
            _Database(),
            lambda value: value["snapshot"].update({"application_publication_id": "wrong"}),
            False,
            "principal_snapshot_invalid",
        ),
        (_Database(), None, True, "business_application_denied"),
    ],
)
def test_issuer_fails_closed_and_audits_denial(
    database: _Database,
    mutate_snapshot: object,
    denied: bool,
    error_code: str,
) -> None:
    snapshot = _Snapshot()
    if callable(mutate_snapshot):
        mutate_snapshot(snapshot.value)
    audit = _Audit()
    issuer, _, _, _ = _issuer(
        database=database,
        snapshot=snapshot,
        authorization=_BusinessAuthorization(denied=denied),
        audit=audit,
    )

    with pytest.raises((PrincipalTokenError, PermissionDenied)) as rejected:
        issuer.issue_for_job(job_id="job-1")
    assert rejected.value.error_code == error_code
    assert audit.events[-1]["event_type"] == "principal.jwt.issue_denied"
    assert audit.events[-1]["payload"]["error_code"] == error_code


def test_verifier_rejects_forgery_hs256_none_unknown_kid_and_expanded_claims() -> None:
    active, active_pem = _key()
    other, other_pem = _key()
    audit = _Audit()
    verifier = PrincipalTokenVerifier(
        PrincipalJwks.from_dict(active.public_jwks()),
        audit_service=audit,  # type: ignore[arg-type]
        now=lambda: NOW,
        leeway_seconds=0,
    )
    base = _claims()
    invalid: list[tuple[str, str]] = [
        (_sign(other_pem, base, kid=active.kid), "principal_token_signature_invalid"),
        (_sign(active_pem, base, kid="unknown"), "principal_token_kid_unknown"),
        (
            _sign(active_pem, {**base, "iss": "wrong"}, kid=active.kid),
            "principal_token_issuer_invalid",
        ),
        (
            _sign(active_pem, {**base, "aud": "wrong"}, kid=active.kid),
            "principal_token_audience_invalid",
        ),
        (
            _sign(
                active_pem,
                {**base, "scope": [ONES_SEARCH_SCOPE, "mcp:ones-mcp:admin"]},
                kid=active.kid,
            ),
            "principal_token_scope_invalid",
        ),
        (
            _sign(
                active_pem,
                {**base, "iat": NOW - 400, "nbf": NOW - 401, "exp": NOW - 100},
                kid=active.kid,
            ),
            "principal_token_expired",
        ),
        (
            _sign(
                active_pem,
                {**base, "iat": NOW + 60, "nbf": NOW + 60, "exp": NOW + 120},
                kid=active.kid,
            ),
            "principal_token_not_yet_valid",
        ),
        (
            _sign(active_pem, {**base, "external_identity_id": "forbidden"}, kid=active.kid),
            "principal_token_claims_invalid",
        ),
    ]
    hmac_token = str(
        jwt.encode(
            base,
            b"test-hmac-key-that-is-long-enough",
            algorithm="HS256",
            headers={"alg": "HS256", "kid": active.kid, "typ": "JWT"},
        )
    )
    none_token = str(
        jwt.encode(
            base,
            key="",
            algorithm="none",
            headers={"alg": "none", "kid": active.kid, "typ": "JWT"},
        )
    )
    invalid.extend(
        [
            (hmac_token, "principal_token_algorithm_invalid"),
            (none_token, "principal_token_algorithm_invalid"),
        ]
    )

    for token, error_code in invalid:
        with pytest.raises(PrincipalTokenError) as rejected:
            verifier.verify(token)
        assert rejected.value.error_code == error_code

    assert len(audit.events) == len(invalid)
    serialized = json.dumps(audit.events, sort_keys=True)
    for token, _ in invalid:
        assert token not in serialized
    assert all(event["event_type"] == "principal.jwt.validation_denied" for event in audit.events)


def test_verifier_rechecks_running_job_user_and_user_status() -> None:
    issuer, signing_key, audit, _ = _issuer()
    token = issuer.issue_for_job(job_id="job-1")
    verifier = PrincipalTokenVerifier(
        PrincipalJwks.from_dict(signing_key.public_jwks()),
        audit_service=audit,  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    assert verifier.verify_for_running_job(token, _Database()) == _claims()  # type: ignore[arg-type]

    for database in (
        _Database(internal_user_id="user-2"),
        _Database(status="SUCCEEDED"),
        _Database(user_status="disabled"),
    ):
        with pytest.raises(PrincipalTokenError) as rejected:
            verifier.verify_for_running_job(token, database)  # type: ignore[arg-type]
        assert rejected.value.error_code == "principal_job_user_mismatch"

    assert [event["event_type"] for event in audit.events].count(
        "principal.jwt.validation_denied"
    ) == 3
