from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from services.mcp_common.auth import McpAuthenticationError, McpTokenVerifier
from services.mcp_common.platform_store import (
    McpRequestAuthorizer,
    RejectingRequestAuthorizer,
)


AsgiApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]
]
_MAX_DENIAL_BODY_BYTES = 256 * 1024
_MAX_DENIAL_BODY_CHUNKS = 32


class McpBearerAuthMiddleware:
    """Authenticate every MCP HTTP request while keeping health endpoints public."""

    def __init__(
        self,
        app: AsgiApp,
        verifier: McpTokenVerifier,
        authorizer: McpRequestAuthorizer | None = None,
    ) -> None:
        self._app = app
        self._verifier = verifier
        self._authorizer = authorizer or RejectingRequestAuthorizer()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not str(scope.get("path") or "").startswith("/mcp"):
            await self._app(scope, receive, send)
            return
        header_map = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }
        authorization = header_map.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        claims = None
        try:
            if not separator or scheme.lower() != "bearer":
                raise McpAuthenticationError("MCP Bearer token is required")
            claims = self._verifier.verify(token)
            job = self._authorizer.authorize_request(claims)
        except McpAuthenticationError as exc:
            if claims is None and exc.reason_code == "mcp_token_expired":
                try:
                    claims = self._verifier.inspect_signed(token)
                except McpAuthenticationError:
                    claims = None
            if claims is not None:
                tool_name = await _read_denied_tool_name(receive)
                recorder = getattr(self._authorizer, "try_record_denial", None)
                if tool_name and callable(recorder):
                    recorder(
                        claims=claims,
                        tool_name=tool_name,
                        correlation_id=header_map.get("x-correlation-id", "")[:128],
                        reason_code=exc.reason_code,
                    )
            payload = json.dumps(
                {"error": "mcp_authentication_failed"},
                separators=(",", ":"),
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(payload)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": payload})
            return
        scope.setdefault("state", {})["mcp_claims"] = claims.model_dump()
        scope.setdefault("state", {})["mcp_job"] = job.model_dump()
        await self._app(scope, receive, send)


async def _read_denied_tool_name(receive: Any) -> str:
    """Extract only the bounded Tool name; never retain denied arguments."""

    body = bytearray()
    for _ in range(_MAX_DENIAL_BODY_CHUNKS):
        event = await receive()
        if event.get("type") != "http.request":
            return ""
        chunk = event.get("body") or b""
        if not isinstance(chunk, bytes) or len(body) + len(chunk) > _MAX_DENIAL_BODY_BYTES:
            return ""
        body.extend(chunk)
        if not event.get("more_body", False):
            break
    else:
        return ""
    try:
        request = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(request, dict) or request.get("method") != "tools/call":
        return ""
    params = request.get("params")
    if not isinstance(params, dict):
        return ""
    tool_name = params.get("name")
    if not isinstance(tool_name, str) or not 1 <= len(tool_name) <= 128:
        return ""
    return tool_name
