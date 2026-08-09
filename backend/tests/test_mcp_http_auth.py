from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from services.mcp_common import McpAuthenticationError, McpTokenIssuer, McpTokenVerifier
from services.mcp_common.http_auth import McpBearerAuthMiddleware


KEY = b"http-auth-signing-key-at-least-32-bytes"


class DenyingAuthorizer:
    def __init__(self, reason_code: str = "mcp_token_revoked") -> None:
        self.reason_code = reason_code
        self.denials: list[dict[str, Any]] = []

    def authorize_request(self, claims: Any) -> Any:
        del claims
        raise McpAuthenticationError("denied", reason_code=self.reason_code)

    def try_record_denial(self, **denial: Any) -> None:
        self.denials.append(denial)


def _token(*, expired: bool = False) -> str:
    now = datetime.now(UTC)
    if expired:
        now -= timedelta(minutes=3)
    return McpTokenIssuer(KEY).issue(
        audience="ones-mcp",
        app_user_id="user-1",
        job_id="job-1",
        application_publication_id="application-1",
        scopes=["ones.work_items.search"],
        job_timeout_seconds=1,
        now=now,
    )


async def _request(token: str, authorizer: DenyingAuthorizer) -> tuple[list[dict[str, Any]], bool]:
    app_called = False

    async def app(scope: Any, receive: Any, send: Any) -> None:
        del scope, receive, send
        nonlocal app_called
        app_called = True

    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ones_work_item_search",
                "arguments": {"secret": "must-not-be-recorded"},
            },
        }
    ).encode()
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": request, "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(event: dict[str, Any]) -> None:
        sent.append(event)

    middleware = McpBearerAuthMiddleware(
        app,
        McpTokenVerifier(KEY, audience="ones-mcp"),
        authorizer,
    )
    await middleware(
        {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-correlation-id", b"correlation-1"),
            ],
        },
        receive,
        send,
    )
    return sent, app_called


def test_expired_signed_token_records_only_denied_tool_provenance() -> None:
    authorizer = DenyingAuthorizer()

    sent, app_called = asyncio.run(_request(_token(expired=True), authorizer))

    assert app_called is False
    assert sent[0]["status"] == 401
    assert json.loads(sent[1]["body"]) == {"error": "mcp_authentication_failed"}
    assert len(authorizer.denials) == 1
    denial = authorizer.denials[0]
    assert denial["tool_name"] == "ones_work_item_search"
    assert denial["correlation_id"] == "correlation-1"
    assert denial["reason_code"] == "mcp_token_expired"
    assert denial["claims"].job_id == "job-1"
    assert "must-not-be-recorded" not in json.dumps(denial, default=str)


def test_authorizer_denial_records_stable_reason_without_request_arguments() -> None:
    authorizer = DenyingAuthorizer(reason_code="mcp_token_revoked")

    sent, app_called = asyncio.run(_request(_token(), authorizer))

    assert app_called is False
    assert sent[0]["status"] == 401
    assert authorizer.denials[0]["reason_code"] == "mcp_token_revoked"
    assert "must-not-be-recorded" not in json.dumps(authorizer.denials, default=str)


def test_invalid_unsigned_token_never_creates_denied_provenance() -> None:
    authorizer = DenyingAuthorizer()

    sent, app_called = asyncio.run(_request("not-a-signed-token", authorizer))

    assert app_called is False
    assert sent[0]["status"] == 401
    assert authorizer.denials == []
