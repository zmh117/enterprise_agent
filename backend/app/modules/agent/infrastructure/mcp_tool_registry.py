from __future__ import annotations

from typing import Any

from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
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

    def __init__(
        self,
        tool_service: ReadOnlyToolService,
        *,
        handler_registry: HandlerRegistry | None = None,
    ) -> None:
        self.tool_service = tool_service
        self.handler_registry = (
            handler_registry or build_builtin_handler_registry()
        )

    def available_tools(self) -> list[str]:
        installed = {
            definition.handler_id
            for definition in self.handler_registry.definitions()
        }
        return sorted(self.READONLY_TOOLS.intersection(installed))

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
        try:
            self.handler_registry.require(tool_name, "1.0.0")
        except HandlerRegistryError as exc:
            raise ToolPolicyError(
                f"Tool Handler is not installed: {tool_name}",
                safe_message="工具 Handler 未安装",
            ) from exc
        return self.tool_service.call_tool(
            job_id=job_id,
            user_id=user_id,
            project_code=project_code,
            tool_name=tool_name,
            arguments=arguments,
            record_tool_call=record_tool_call,
        )
