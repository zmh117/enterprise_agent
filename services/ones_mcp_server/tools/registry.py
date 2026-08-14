from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.modules.mcp_audit import McpAuditCoordinator
from services.ones_mcp_server.errors import OnesMcpError


class OnesToolHandler(Protocol):
    tool_identifier: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> dict[str, Any]: ...


class OnesToolRegistry:
    """Code-owned MCP Tool catalog and dispatch boundary."""

    def __init__(
        self,
        *,
        authenticate: Callable[[str], dict[str, Any]],
        tools: tuple[OnesToolHandler, ...],
        audit: McpAuditCoordinator,
    ) -> None:
        registered: dict[str, OnesToolHandler] = {}
        for tool in tools:
            if not tool.tool_identifier or tool.tool_identifier in registered:
                raise ValueError("ONES MCP Tool registry is invalid")
            registered[tool.tool_identifier] = tool
        if not registered:
            raise ValueError("At least one ONES MCP Tool is required")
        self._authenticate = authenticate
        self._tools = registered
        self.audit = audit

    def authenticate(self, token: str) -> dict[str, Any]:
        return self._authenticate(token)

    def require(self, tool_identifier: str) -> OnesToolHandler:
        try:
            return self._tools[tool_identifier]
        except KeyError as exc:
            raise OnesMcpError(
                "ONES MCP Tool is not published",
                safe_message="当前 ONES 工具未发布",
                error_code="ones_mcp_tool_denied",
            ) from exc

    @property
    def tools(self) -> tuple[OnesToolHandler, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))
