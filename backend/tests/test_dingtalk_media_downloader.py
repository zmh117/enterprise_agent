from __future__ import annotations

from typing import Any

from app.modules.attachments import dingtalk_downloader as downloader_module
from app.modules.attachments.dingtalk_downloader import DingTalkMediaDownloader


class _TokenClient:
    def access_token(self) -> str:
        return "test-only-access-token"


class _DownloadResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self) -> _DownloadResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        content, self._content = self._content, b""
        return content


class _DownloadApiTransport:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def post_json(
        self,
        _url: str,
        payload: dict[str, Any],
        _headers: dict[str, str],
        _timeout_seconds: int,
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        return {"downloadUrl": "https://download.dingtalk.invalid/file"}


def test_media_download_resolves_exact_source_connector_and_reuses_token_client(
    monkeypatch: Any,
) -> None:
    resolved: list[str] = []
    client_creations: list[tuple[str, str]] = []
    transport = _DownloadApiTransport()

    def resolve(connector_id: str) -> tuple[str, str, str]:
        resolved.append(connector_id)
        return "test-client-id", "test-client-secret", "connector-robot"

    def create_client(client_id: str, client_secret: str) -> Any:
        client_creations.append((client_id, client_secret))
        return _TokenClient()

    monkeypatch.setattr(
        downloader_module,
        "urlopen",
        lambda _request, timeout: _DownloadResponse(f"downloaded-{timeout}".encode("utf-8")),
    )
    downloader = DingTalkMediaDownloader(
        credential_resolver=resolve,
        token_client_factory=create_client,
        transport=transport,
        timeout_seconds=9,
    )

    assert (
        downloader.download(
            download_code="download-code-1",
            max_bytes=1024,
            connector_id="connector-source-1",
            robot_code="message-robot",
        )
        == b"downloaded-9"
    )
    assert (
        downloader.download(
            download_code="download-code-2",
            max_bytes=1024,
            connector_id="connector-source-1",
        )
        == b"downloaded-9"
    )

    assert resolved == ["connector-source-1", "connector-source-1"]
    assert client_creations == [("test-client-id", "test-client-secret")]
    assert transport.payloads == [
        {"robotCode": "message-robot", "downloadCode": "download-code-1"},
        {"robotCode": "connector-robot", "downloadCode": "download-code-2"},
    ]
