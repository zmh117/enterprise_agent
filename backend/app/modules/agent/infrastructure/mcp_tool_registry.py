from __future__ import annotations

from typing import Any

from app.modules.mcp_tool_runtime.service import ReadOnlyToolService
from app.modules.mcp_tool_runtime.contracts import ToolResult
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.exceptions import ToolPolicyError


class ToolRegistry:
    READONLY_TOOLS = frozenset(MCP_TOOL_MANIFEST)

    def __init__(
        self,
        tool_service: ReadOnlyToolService,
    ) -> None:
        self.tool_service = tool_service

    def available_tools(self) -> list[str]:
        return sorted(self.READONLY_TOOLS.intersection(MCP_TOOL_MANIFEST))

    def call(
        self,
        *,
        job_id: str,
        user_id: str,
        project_code: str,
        tool_name: str,
        arguments: dict[str, Any],
        record_tool_call: bool = True,
    ) -> ToolResult:
        if tool_name not in self.READONLY_TOOLS:
            raise ToolPolicyError(f"Tool {tool_name} is not registered for MVP")
        if tool_name not in MCP_TOOL_MANIFEST:
            raise ToolPolicyError(
                f"MCP Tool is not installed: {tool_name}",
                safe_message="MCP 工具未安装",
                error_code="mcp_tool_not_installed",
            )
        return self.tool_service.call_tool(
            job_id=job_id,
            user_id=user_id,
            project_code=project_code,
            tool_name=tool_name,
            arguments=arguments,
            record_tool_call=record_tool_call,
        )
