from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient

from services.file_service.app import create_app


class _Database:
    def execute_one(self, query: str) -> dict[str, Any]:
        if "schema_migration" in query:
            return {"version": 113}
        return {"ready": 1}

    def execute(self, _: str) -> list[dict[str, Any]]:
        return []


class _Ready:
    def assert_ready(self) -> None:
        return None

    def current(self) -> object:
        return object()


class _Principal:
    def authenticate(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("MCP principal must not be used")


class _Application:
    def invoke(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("MCP application must not be used")


class _Streaming:
    async def download_transfer(
        self, *, transfer_id: str, token: str
    ) -> tuple[AsyncIterator[bytes], str]:
        raise AssertionError((transfer_id, token))


class _ServicePrincipal:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def verify_processing(self, token: str, *, required_scope: str) -> dict[str, Any]:
        assert token == "processing-worker-token"
        self.scopes.append(required_scope)
        return {"sub": "file-processing-worker"}


class _DocumentProcessing:
    def __init__(self) -> None:
        self.claim_message: dict[str, Any] = {}

    def claim(self, *, message: dict[str, Any], service_principal_id: str) -> dict[str, Any]:
        assert service_principal_id == "file-processing-worker"
        self.claim_message = message
        return {
            "run_id": "run-1",
            "tenant_id": "tenant-1",
            "source_version_id": "version-1",
            "profile_hash": "a" * 64,
            "status": "RUNNING",
            "attempt": 1,
            "claimed": True,
            "external_task_id": "",
            "display_name": "sample.pdf",
            "media_type": "application/pdf",
            "format_code": "PDF",
            "size_bytes": 9,
            "content_sha256": "b" * 64,
        }

    def prepare_source_stream(self, **values: Any) -> dict[str, str]:
        assert values == {
            "run_id": "run-1",
            "tenant_id": "tenant-1",
            "service_principal_id": "file-processing-worker",
        }
        return {
            "run_id": "run-1",
            "source_version_id": "version-1",
            "grant": "bounded-source-grant",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }

    def open_source_stream(self, **values: Any) -> io.BytesIO:
        assert values == {
            "grant": "bounded-source-grant",
            "service_principal_id": "file-processing-worker",
        }
        return io.BytesIO(b"%PDF-1.7\n")


def _client() -> tuple[TestClient, _ServicePrincipal, _DocumentProcessing]:
    service_principal = _ServicePrincipal()
    processing = _DocumentProcessing()
    app = create_app(
        principal=_Principal(),  # type: ignore[arg-type]
        service_principal=service_principal,  # type: ignore[arg-type]
        application=_Application(),  # type: ignore[arg-type]
        streaming=_Streaming(),  # type: ignore[arg-type]
        document_processing=processing,  # type: ignore[arg-type]
        database=_Database(),
        storage=_Ready(),
        jwks=_Ready(),  # type: ignore[arg-type]
    )
    return TestClient(app), service_principal, processing


def test_processing_worker_claim_and_source_stream_are_principal_and_purpose_bound() -> None:
    client, principal, processing = _client()
    headers = {
        "Authorization": "Bearer processing-worker-token",
        "Content-Type": "application/json",
    }
    message = {
        "contract_version": "file-processing/v1",
        "run_id": "run-1",
        "source_version_id": "version-1",
        "profile_hash": "a" * 64,
        "attempt": 0,
        "correlation_id": "correlation-1",
    }
    with client:
        claimed = client.post(
            "/internal/v1/document-processing/runs/run-1/claim",
            headers=headers,
            json=message,
        )
        assert claimed.status_code == 200
        assert processing.claim_message == message
        grant = client.post(
            "/internal/v1/document-processing/runs/run-1/source-grant",
            headers=headers,
            json={"tenant_id": "tenant-1"},
        )
        assert grant.status_code == 200
        source = client.get(
            "/internal/v1/document-processing/runs/run-1/source",
            headers={
                "Authorization": "Bearer processing-worker-token",
                "X-Document-Source-Grant": grant.json()["grant"],
            },
        )
        assert source.status_code == 200
        assert source.content == b"%PDF-1.7\n"
    assert principal.scopes == [
        "internal:file-service:document-processing:claim",
        "internal:file-service:document-processing:source:read",
        "internal:file-service:document-processing:source:read",
    ]


def test_processing_claim_rejects_path_message_identity_mismatch_before_domain_call() -> None:
    client, _, processing = _client()
    with client:
        response = client.post(
            "/internal/v1/document-processing/runs/run-2/claim",
            headers={"Authorization": "Bearer processing-worker-token"},
            json={
                "contract_version": "file-processing/v1",
                "run_id": "run-1",
                "source_version_id": "version-1",
                "profile_hash": "a" * 64,
                "attempt": 0,
                "correlation_id": "correlation-1",
            },
        )
    assert response.status_code == 403
    assert response.json()["error_code"] == "document_processing_message_mismatch"
    assert processing.claim_message == {}
