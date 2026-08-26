from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.ones_mcp_server.contracts import PROVIDER_HEADERS
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient


@dataclass(frozen=True, slots=True)
class RestExecution:
    request: dict[str, Any]
    response: dict[str, Any]
    output: Any


def request_headers(
    http: OnesProviderHttpClient,
    *,
    token: str,
    user_id: str,
) -> dict[str, str]:
    return {
        PROVIDER_HEADERS["token"]: token,
        PROVIDER_HEADERS["user"]: user_id,
        "Referer": http.target.base_url,
        "cache-control": "no-cache",
    }

