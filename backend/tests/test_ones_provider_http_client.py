from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler

import pytest

from app.shared.exceptions import AppError
from services.ones_mcp_server.provider.http_client import (
    OnesProviderHttpClient,
    _NoRedirectHandler,
)
from services.ones_mcp_server.provider.target import validate_provider_target


@dataclass
class _Response:
    status: int
    content: bytes

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.content[:limit]


def _client(open_response: Any, *, maximum: int = 4096) -> OnesProviderHttpClient:
    return OnesProviderHttpClient(
        validate_provider_target(
            "http://ones-mock:8001",
            allowed_hosts=("ones-mock",),
            app_env="test",
            allow_insecure_local=True,
        ),
        timeout_seconds=5,
        max_response_bytes=maximum,
        open_response=open_response,
    )


def test_http_client_sends_exact_get_and_post_json_requests() -> None:
    calls: list[tuple[Any, float]] = []

    def open_response(request: Any, timeout: float) -> _Response:
        calls.append((request, timeout))
        return _Response(200, b'{"ok":true}')

    client = _client(open_response)
    headers = {
        "Ones-Auth-Token": "synthetic-token",
        "Ones-User-Id": "synthetic-user",
        "Referer": "http://ones-mock:8001",
        "cache-control": "no-cache",
    }

    assert client.get_json("/fixed/get", {}, headers=headers) == {"ok": True}
    assert client.post_json("/fixed/post", {"uuids": ["U1"]}, headers=headers) == {
        "ok": True
    }

    get_request, get_timeout = calls[0]
    post_request, post_timeout = calls[1]
    assert get_request.get_method() == "GET"
    assert get_request.full_url == "http://ones-mock:8001/fixed/get"
    assert bytes(get_request.data) == b"{}"
    assert post_request.get_method() == "POST"
    assert post_request.full_url == "http://ones-mock:8001/fixed/post"
    assert json.loads(bytes(post_request.data)) == {"uuids": ["U1"]}
    assert get_timeout == post_timeout == 5.0
    sent_headers = {key.lower(): value for key, value in get_request.header_items()}
    assert sent_headers == {
        "accept": "application/json",
        "content-type": "application/json",
        "ones-auth-token": "synthetic-token",
        "ones-user-id": "synthetic-user",
        "referer": "http://ones-mock:8001",
        "cache-control": "no-cache",
    }


def test_http_client_keeps_proxy_and_redirect_handlers_closed() -> None:
    client = _client(lambda *_args: _Response(200, b"{}"))

    assert not any(isinstance(handler, ProxyHandler) for handler in client._opener.handlers)
    assert any(isinstance(handler, _NoRedirectHandler) for handler in client._opener.handlers)


@pytest.mark.parametrize(
    "path",
    ["relative", "https://other.example/path", "/path?query=1", "/path#fragment"],
)
def test_http_client_rejects_non_fixed_paths(path: str) -> None:
    client = _client(lambda *_args: _Response(200, b"{}"))

    with pytest.raises(ValueError):
        client.get_json(path, {}, headers={})


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        (401, "ones_provider_unauthorized"),
        (403, "ones_provider_forbidden"),
        (429, "ones_provider_rate_limited"),
        (500, "ones_provider_unavailable"),
        (307, "ones_provider_redirect_rejected"),
        (404, "ones_provider_response_invalid"),
    ],
)
def test_http_client_maps_http_status_without_exposing_bodies(
    status: int,
    error_code: str,
) -> None:
    def reject(request: Any, _timeout: float) -> _Response:
        raise HTTPError(request.full_url, status, "fixed", {}, None)

    client = _client(reject)
    with pytest.raises(AppError) as raised:
        client.get_json("/fixed/get", {}, headers={})
    assert raised.value.error_code == error_code


def test_http_client_rejects_invalid_or_oversized_json() -> None:
    invalid = _client(lambda *_args: _Response(200, b"not-json"))
    with pytest.raises(AppError) as malformed:
        invalid.get_json("/fixed/get", {}, headers={})
    assert malformed.value.error_code == "ones_provider_response_invalid"

    oversized = _client(lambda *_args: _Response(200, b'{' + b"x" * 5000), maximum=1024)
    with pytest.raises(AppError) as too_large:
        oversized.get_json("/fixed/get", {}, headers={})
    assert too_large.value.error_code == "ones_provider_response_too_large"
