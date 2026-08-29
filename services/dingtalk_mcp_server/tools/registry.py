from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.exceptions import AppError
from services.dingtalk_mcp_server.errors import DingTalkMcpError


class DingTalkToolHandler(Protocol):
    tool_identifier: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool

    def authenticate(self, token: str) -> dict[str, Any]: ...
    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> dict[str, Any]: ...


class DingTalkToolRegistry:
    def __init__(
        self,
        *,
        authenticate: Callable[[str], dict[str, Any]],
        tools: tuple[DingTalkToolHandler, ...],
        audit: McpAuditCoordinator,
    ) -> None:
        self._authenticate = authenticate
        self._tools = {tool.tool_identifier: tool for tool in tools}
        if len(self._tools) != len(tools) or not self._tools:
            raise ValueError("DingTalk MCP Tool registry is invalid")
        self.audit = audit

    def authenticate(self, token: str, *, tool_identifier: str | None = None) -> dict[str, Any]:
        if tool_identifier is None:
            return self._authenticate(token)
        return self.require(tool_identifier).authenticate(token)

    def authorized_tools(self, token: str) -> tuple[DingTalkToolHandler, ...]:
        authorized: list[DingTalkToolHandler] = []
        first_error: AppError | None = None
        for tool in self.tools:
            try:
                tool.authenticate(token)
                authorized.append(tool)
            except AppError as exc:
                first_error = first_error or exc
        if not authorized:
            if first_error is not None:
                raise first_error
            raise DingTalkMcpError(
                "DingTalk MCP has no authorized Tool",
                safe_message="当前任务没有可用的钉钉工具",
                error_code="dingtalk_mcp_tool_denied",
            )
        return tuple(authorized)

    def require(self, identifier: str) -> DingTalkToolHandler:
        try:
            return self._tools[identifier]
        except KeyError as exc:
            raise DingTalkMcpError(
                "DingTalk MCP Tool is not published",
                safe_message="当前钉钉工具未发布",
                error_code="dingtalk_mcp_tool_denied",
            ) from exc

    @property
    def tools(self) -> tuple[DingTalkToolHandler, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))
