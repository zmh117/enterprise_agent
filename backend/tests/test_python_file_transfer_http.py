from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any

import httpx

from app.python_runtime.file_transfer_http import HttpFileTransferPort


def test_python_runtime_http_transfer_port_streams_fixed_internal_paths() -> None:
    uploaded: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-principal"
        assert request.headers["x-job-id"] == "job-http-1"
        if request.method == "GET":
            assert request.url.path == "/internal/v1/file-transfers/transfer-http-1/content"
            return httpx.Response(
                200,
                headers={"Content-Type": "application/octet-stream"},
                content=b"downloaded TXT",
            )
        assert request.method == "PUT"
        assert request.url.path == "/internal/v1/file-commits/commit-http-1/content"
        body = request.read()
        uploaded.append(body)
        return httpx.Response(
            200,
            json={
                "file_id": "file-http-1",
                "version_id": "version-http-1",
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "status": "COMMITTED",
                "delivery_id": "delivery-http-1",
                "delivery_status": "PENDING",
            },
        )

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=transport, **kwargs)

    port = HttpFileTransferPort(
        "http://file-service:9105/mcp",
        timeout_seconds=5,
        client_factory=client_factory,
    )

    downloaded = b"".join(
        port.download(
            transfer_id="transfer-http-1",
            job_id="job-http-1",
            principal_token="test-principal",
        )
    )

    def content() -> Iterator[bytes]:
        yield b"uploaded "
        yield b"TXT"

    receipt = port.upload(
        commit_id="commit-http-1",
        job_id="job-http-1",
        principal_token="test-principal",
        content=content(),
    )

    assert downloaded == b"downloaded TXT"
    assert uploaded == [b"uploaded TXT"]
    assert receipt.file_id == "file-http-1"
    assert receipt.version_id == "version-http-1"
    assert receipt.size_bytes == len(b"uploaded TXT")
    assert receipt.delivery_id == "delivery-http-1"
    assert receipt.delivery_status == "PENDING"
