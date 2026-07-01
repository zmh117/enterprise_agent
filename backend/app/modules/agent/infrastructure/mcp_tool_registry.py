from __future__ import annotations

from typing import Any

from app.modules.internal_tools.application.tools import ReadOnlyToolService
from app.modules.internal_tools.infrastructure.internal_api_client import ToolResult
from app.shared.exceptions import ToolPolicyError


class ToolRegistry:
    READONLY_TOOLS = {
        "get_er_context",
        "get_business_flow_context",
        "get_schema_directory",
        "diagnose_loki_labels",
        "diagnose_loki_label_values",
        "diagnose_loki_probe",
        "query_loki",
        "query_database",
        "query_redis_get",
        "query_redis_scan",
    }

    def __init__(self, tool_service: ReadOnlyToolService) -> None:
        self.tool_service = tool_service

    def available_tools(self) -> list[str]:
        return sorted(self.READONLY_TOOLS)

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
        return self.tool_service.call_tool(
            job_id=job_id,
            user_id=user_id,
            project_code=project_code,
            tool_name=tool_name,
            arguments=arguments,
            record_tool_call=record_tool_call,
        )
