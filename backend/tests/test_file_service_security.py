from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.modules.file_workspace.storage import (
    FileObjectStorageSettings,
    MinioFileObjectStorage,
)
from app.modules.file_workspace.safe_summary import safe_file_audit_summary
from app.modules.file_workspace.contracts import FILE_TOOL_MANIFEST
from app.modules.identity.application.principal_jwt import (
    PrincipalJwks,
    PrincipalSigningKey,
)
from app.shared.config import FileServiceSettings
from services.file_service.app import create_app
from services.file_service.auth import (
    FILE_PRINCIPAL_AUDIENCE,
    FILE_SERVICE_AUDIENCE,
    FILE_WORKER_AUTHORIZED_PARTY,
    FILE_WORKER_ISSUER,
    FILE_WORKER_SCOPES,
    PLATFORM_PRINCIPAL_ISSUER,
    FilePrincipalError,
    FilePrincipalVerifier,
    FileWorkerPrincipalVerifier,
)
from services.file_service.principal import FilePrincipalResolver, file_tool_scope


NOW = 1_786_667_200


def _signing() -> tuple[PrincipalSigningKey, PrincipalJwks]:
    private = Ed25519PrivateKey.generate()
    signing = PrincipalSigningKey.from_pem(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return signing, PrincipalJwks.from_dict(signing.public_jwks())


def _job_claims(scopes: list[str]) -> dict[str, Any]:
    return {
        "iss": PLATFORM_PRINCIPAL_ISSUER,
        "sub": "user-a",
        "aud": FILE_PRINCIPAL_AUDIENCE,
        "azp": "agent-runtime",
        "tenant_id": "tenant-a",
        "job_id": "job-a",
        "session_id": "session-a",
        "agent_publication_id": "agent-publication-a",
        "application_publication_id": "application-publication-a",
        "scope": scopes,
        "authorization_hash": "a" * 64,
        "jti": "jti-a",
        "iat": NOW,
        "nbf": NOW - 1,
        "exp": NOW + 60,
    }


def test_file_principal_verifies_exact_audience_party_time_tenant_and_scopes() -> None:
    signing, jwks = _signing()
    scopes = [
        file_tool_scope("task_workspace_get"),
        file_tool_scope("file_get_metadata"),
    ]
    verifier = FilePrincipalVerifier(jwks, now=lambda: NOW)
    token = signing.sign(_job_claims(scopes))
    claims = verifier.verify(token, required_scopes=frozenset(scopes))
    assert claims["tenant_id"] == "tenant-a"
    assert claims["job_id"] == "job-a"

    for mutation in (
        {"aud": "ones-mcp"},
        {"azp": "agent-worker"},
        {"tenant_id": ""},
        {"exp": NOW - 60},
        {"scope": [*scopes, file_tool_scope("file_deliver_version")]},
    ):
        invalid = {**_job_claims(scopes), **mutation}
        with pytest.raises(FilePrincipalError):
            verifier.verify(signing.sign(invalid), required_scopes=frozenset(scopes))


def test_file_worker_principal_is_separate_from_user_agent_and_shared_tokens() -> None:
    signing, jwks = _signing()
    verifier = FileWorkerPrincipalVerifier(jwks, now=lambda: NOW)
    scope = "internal:file-service:attachment:import"
    service_claims = {
        "iss": FILE_WORKER_ISSUER,
        "sub": FILE_WORKER_AUTHORIZED_PARTY,
        "aud": FILE_SERVICE_AUDIENCE,
        "azp": FILE_WORKER_AUTHORIZED_PARTY,
        "scope": sorted(FILE_WORKER_SCOPES),
        "authorization_hash": "b" * 64,
        "jti": "service-jti-a",
        "iat": NOW,
        "nbf": NOW - 1,
        "exp": NOW + 60,
    }
    assert (
        verifier.verify_service(signing.sign(service_claims), required_scope=scope)["sub"]
        == "file-worker"
    )

    with pytest.raises(FilePrincipalError):
        verifier.verify_service(
            signing.sign(_job_claims([file_tool_scope("task_workspace_get")])),
            required_scope=scope,
        )
    with pytest.raises(FilePrincipalError):
        verifier.verify_service("shared-internal-api-token", required_scope=scope)


class _Snapshot:
    def __init__(self, *, schema_hash: str, authorization_hash: str = "a" * 64) -> None:
        self.schema_hash = schema_hash
        self.authorization_hash = authorization_hash

    def verify(self, job_id: str) -> dict[str, Any]:
        assert job_id == "job-a"
        return {
            "authorization_hash": self.authorization_hash,
            "snapshot": {
                "job_id": job_id,
                "tools": [
                    {
                        "server_code": "file-service",
                        "tool_identifier": "task_workspace_get",
                        "schema_hash": self.schema_hash,
                    }
                ],
            },
        }


class _Authorization:
    def require_job(self, *, claims: dict[str, Any], tool_identifier: str) -> Any:
        assert claims["job_id"] == "job-a"
        assert tool_identifier == "task_workspace_get"
        return {"authorized": True}


def test_file_principal_resolver_rejects_schema_authorization_and_scope_drift() -> None:
    signing, jwks = _signing()
    scope = file_tool_scope("task_workspace_get")
    verifier = FilePrincipalVerifier(jwks, now=lambda: NOW)
    resolver = FilePrincipalResolver(
        verifier,
        _Snapshot(schema_hash=FILE_TOOL_MANIFEST["task_workspace_get"].schema_hash),
        _Authorization(),  # type: ignore[arg-type]
    )
    claims, authorization, visible = resolver.authenticate(signing.sign(_job_claims([scope])))
    assert claims["authorization_hash"] == "a" * 64
    assert authorization == {"authorized": True}
    assert visible == ("task_workspace_get",)

    drifted = FilePrincipalResolver(
        verifier,
        _Snapshot(schema_hash="f" * 64),
        _Authorization(),  # type: ignore[arg-type]
    )
    with pytest.raises(FilePrincipalError) as error:
        drifted.authenticate(signing.sign(_job_claims([scope])))
    assert error.value.error_code == "file_principal_schema_mismatch"

    changed_hash = FilePrincipalResolver(
        verifier,
        _Snapshot(
            schema_hash=FILE_TOOL_MANIFEST["task_workspace_get"].schema_hash,
            authorization_hash="c" * 64,
        ),
        _Authorization(),  # type: ignore[arg-type]
    )
    with pytest.raises(FilePrincipalError) as error:
        changed_hash.authenticate(signing.sign(_job_claims([scope])))
    assert error.value.error_code == "file_principal_snapshot_mismatch"


class _FakeS3:
    def __init__(self) -> None:
        self.put: dict[str, Any] | None = None
        self.ready = False

    def put_object(self, **kwargs: Any) -> None:
        self.put = kwargs

    def head_bucket(self, **kwargs: Any) -> None:
        assert kwargs["Bucket"] == "private-files"
        self.ready = True


def test_minio_adapter_only_resolves_platform_refs_and_generates_opaque_keys() -> None:
    resolved: list[str] = []

    def resolve(ref: str) -> str:
        resolved.append(ref)
        return "credential-value-never-returned"

    fake = _FakeS3()
    settings = FileObjectStorageSettings(
        endpoint_url="http://minio:9000",
        bucket="private-files",
        access_key_ref="secret://platform/minio-access",
        secret_key_ref="secret://platform/minio-secret",
    )
    storage = MinioFileObjectStorage(settings, resolve, client=fake)
    stored = storage.put_stream(
        io.BytesIO(b"hello"),
        kind="version",
        content_type="text/plain",
        content_sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        size_bytes=5,
    )
    assert resolved == [
        "secret://platform/minio-access",
        "secret://platform/minio-secret",
    ]
    assert fake.put is not None
    assert str(fake.put["Key"]).startswith("managed/version/")
    assert "credential-value-never-returned" not in repr(stored)
    assert "managed/version/" not in repr(stored)
    assert settings.safe_projection() == {
        "configured": True,
        "endpoint": "http://minio",
        "bucket": "configured",
        "credentials": "configured",
        "secure": False,
    }
    storage.assert_ready()
    assert fake.ready

    with pytest.raises(ValueError):
        FileObjectStorageSettings(
            endpoint_url="http://user:password@minio:9000/bucket",
            bucket="private-files",
            access_key_ref="raw-access-key",
            secret_key_ref="raw-secret-key",
        )


def test_file_service_requires_distinct_managed_and_legacy_private_buckets() -> None:
    with pytest.raises(ValueError, match="distinct buckets"):
        FileServiceSettings(
            bucket="same-private-bucket",
            legacy_attachment_bucket="same-private-bucket",
        )


class _Database:
    def execute_one(self, query: str) -> dict[str, Any]:
        if "schema_migration" in query:
            return {"version": "118"}
        return {"ready": 1}

    def execute(self, query: str) -> list[dict[str, Any]]:
        del query
        return []


class _Ready:
    def assert_ready(self) -> None:
        return None

    def current(self) -> object:
        return object()


class _NeverCalledPrincipal:
    def authenticate(self, token: str, *, tool_identifier: str = "task_workspace_get") -> Any:
        raise AssertionError((token, tool_identifier))


class _NeverCalledServicePrincipal:
    def verify_service(self, token: str, *, required_scope: str) -> dict[str, Any]:
        raise AssertionError((token, required_scope))


class _NeverCalledApplication:
    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(kwargs)


class _NeverCalledStreaming:
    async def download_transfer(
        self, *, transfer_id: str, token: str
    ) -> tuple[AsyncIterator[bytes], str]:
        raise AssertionError((transfer_id, token))


def test_file_service_health_readiness_and_transport_fail_closed_without_secrets() -> None:
    app = create_app(
        principal=_NeverCalledPrincipal(),  # type: ignore[arg-type]
        service_principal=_NeverCalledServicePrincipal(),  # type: ignore[arg-type]
        application=_NeverCalledApplication(),  # type: ignore[arg-type]
        streaming=_NeverCalledStreaming(),  # type: ignore[arg-type]
        database=_Database(),
        storage=_Ready(),
        jwks=_Ready(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "server_code": "file-service",
        }
        readiness = client.get("/ready")
        assert readiness.status_code == 200
        assert readiness.json()["streaming_api"] == "ready"
        assert readiness.json()["document_processing"] == "not_configured"
        denied = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert denied.status_code == 401
        assert "token" not in denied.text.lower()
        attachment = client.post(
            "/internal/v1/attachments/attachment-a/content",
            content=b"not persisted",
        )
        assert attachment.status_code == 403
        assert "not persisted" not in attachment.text


def test_file_service_readiness_fails_closed_when_document_processing_is_configured_but_absent() -> (
    None
):
    app = create_app(
        principal=_NeverCalledPrincipal(),  # type: ignore[arg-type]
        service_principal=_NeverCalledServicePrincipal(),  # type: ignore[arg-type]
        application=_NeverCalledApplication(),  # type: ignore[arg-type]
        streaming=_NeverCalledStreaming(),  # type: ignore[arg-type]
        document_processing=None,
        document_processing_expected=True,
        database=_Database(),
        storage=_Ready(),
        jwks=_Ready(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        readiness = client.get("/ready")

    assert readiness.status_code == 503
    assert readiness.json()["status"] == "degraded"
    assert "master" not in readiness.text.lower()


def test_file_config_exception_tool_and_audit_surfaces_drop_secrets_objects_and_body() -> None:
    secret = "jwt-or-minio-secret-must-not-survive"
    body = "confidential file body must not survive"
    projected = safe_file_audit_summary(
        {
            "operation": "file.materialization.prepare",
            "status": "DENIED",
            "error_code": "file_manifest_action_denied",
            "job_id": "job-a",
            "file_id": "file-a",
            "duration_ms": 8,
            "authorization": secret,
            "access_key": secret,
            "secret_key": secret,
            "object_key": "managed/version/internal",
            "bucket": "private-files",
            "body": body,
            "content": body,
        }
    )
    encoded = str(projected)
    assert projected == {
        "operation": "file.materialization.prepare",
        "status": "DENIED",
        "error_code": "file_manifest_action_denied",
        "job_id": "job-a",
        "file_id": "file-a",
        "duration_ms": 8,
    }
    assert secret not in encoded
    assert body not in encoded
    assert "managed/version/internal" not in encoded
