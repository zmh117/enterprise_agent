from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest
from pydantic import ValidationError

from services.mcp_common import (
    McpAuthenticationError,
    McpResourceDeployment,
    McpTokenClaims,
    McpTokenIssuer,
    McpTokenVerifier,
    schema_hash,
)


KEY = b"test-only-mcp-signing-key-32-bytes-minimum"


def test_contracts_reject_unknown_identity_fields() -> None:
    with pytest.raises(ValidationError):
        McpTokenClaims.model_validate(
            {
                "iss": "enterprise-agent",
                "aud": "ones-mcp",
                "sub": "user-1",
                "azp": "agent-worker",
                "job_id": "job-1",
                "application_publication_id": "publication-1",
                "scopes": ["ones.work_items.search"],
                "iat": 1,
                "exp": 2,
                "jti": "token-1",
                "team_id": "model-controlled",
            }
        )


def test_token_issuer_limits_lifetime_and_verifier_enforces_scope() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    token = McpTokenIssuer(KEY).issue(
        audience="ones-mcp",
        app_user_id="user-1",
        job_id="job-1",
        application_publication_id="publication-1",
        scopes=["ones.work_items.search"],
        job_timeout_seconds=10_000,
        now=now,
    )
    payload = jwt.decode(
        token,
        KEY,
        algorithms=["HS256"],
        options={"verify_aud": False, "verify_exp": False},
    )
    assert payload["exp"] - payload["iat"] == 900
    verifier = McpTokenVerifier(KEY, audience="ones-mcp")
    claims = verifier.verify(
        McpTokenIssuer(KEY).issue(
            audience="ones-mcp",
            app_user_id="user-1",
            job_id="job-1",
            application_publication_id="publication-1",
            scopes=["ones.work_items.search"],
            job_timeout_seconds=60,
        ),
        required_scope="ones.work_items.search",
    )
    assert claims.sub == "user-1"
    with pytest.raises(McpAuthenticationError, match="scope"):
        verifier.verify(
            McpTokenIssuer(KEY).issue(
                audience="ones-mcp",
                app_user_id="user-1",
                job_id="job-1",
                application_publication_id="publication-1",
                scopes=["ones.work_items.search"],
                job_timeout_seconds=60,
            ),
            required_scope="ones.work_items.get",
        )


def test_verifier_rejects_wrong_audience() -> None:
    token = McpTokenIssuer(KEY).issue(
        audience="ones-mcp",
        app_user_id="user-1",
        job_id="job-1",
        application_publication_id="publication-1",
        scopes=["ones.work_items.search"],
        job_timeout_seconds=60,
    )
    with pytest.raises(McpAuthenticationError):
        McpTokenVerifier(KEY, audience="data-mcp").verify(token)


def test_resource_deployment_is_exact_and_schema_hash_is_stable() -> None:
    deployment = McpResourceDeployment(
        id="deployment-1",
        server_code="data-mcp",
        resource_code="mes-db",
        active_resource_revision_id="resource-revision-7",
        status="ACTIVE",
        revision=3,
        updated_by="admin-1",
        updated_at=datetime.now(UTC),
    )
    assert deployment.active_resource_revision_id == "resource-revision-7"
    assert schema_hash({"b": 2, "a": 1}) == schema_hash({"a": 1, "b": 2})
