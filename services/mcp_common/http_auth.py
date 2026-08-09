from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from services.mcp_common.auth import McpAuthenticationError, McpTokenVerifier
from services.mcp_common.platform_store import (
    McpRequestAuthorizer,
    RejectingRequestAuthorizer,
)


AsgiApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]]


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
        try:
            if not separator or scheme.lower() != "bearer":
                raise McpAuthenticationError("MCP Bearer token is required")
            claims = self._verifier.verify(token)
            job = self._authorizer.authorize_request(claims)
        except McpAuthenticationError:
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
