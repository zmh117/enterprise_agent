from __future__ import annotations

from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.exceptions import NotFound, PermissionDenied, ToolPolicyError


DATA_SCOPED_TOOLS = {
    "get_schema_directory",
    "diagnose_loki_labels",
    "diagnose_loki_label_values",
    "diagnose_loki_probe",
    "query_loki",
    "query_database",
    "query_redis_get",
    "query_redis_scan",
}


class PermissionService:
    def __init__(
        self,
        config_repository: ConfigurationRepository,
        *,
        authorization_evaluator: AuthorizationEvaluator,
    ) -> None:
        self.config_repository = config_repository
        self.authorization_evaluator = authorization_evaluator
        self._mcp_tool_identifiers = frozenset(MCP_TOOL_MANIFEST)

    def assert_user_can_create_job(self, *, user_id: str, project_code: str) -> None:
        if not self._is_allowed(
            user_id=user_id,
            resource_type="project",
            resource_code=project_code,
            action="use",
        ):
            raise PermissionDenied(
                f"User {user_id} is not allowed for {project_code}",
                safe_message="当前用户无权在此范围内使用 Agent",
            )

    def assert_tool_allowed(
        self,
        *,
        user_id: str,
        tool_name: str,
        project_code: str,
        scope: dict[str, str] | None = None,
    ) -> None:
        self.assert_mcp_tool_allowed(
            user_id=user_id,
            tool_identifier=tool_name,
            project_code=project_code,
            scope=scope,
        )

    def assert_mcp_tool_allowed(
        self,
        *,
        user_id: str,
        tool_identifier: str,
        project_code: str,
        scope: dict[str, str] | None = None,
    ) -> None:
        self.assert_mcp_tool_use_grant(
            user_id=user_id,
            tool_identifier=tool_identifier,
            project_code=project_code,
        )
        if tool_identifier in DATA_SCOPED_TOOLS:
            scope = scope or {}
            decision = self.authorization_evaluator.decide_platform_scope(
                user_id=user_id,
                environment=scope.get("environment", ""),
                base=scope.get("base", ""),
                workshop=scope.get("workshop", ""),
                tool_name=tool_identifier,
            )
            if not decision.allowed:
                raise ToolPolicyError(
                    f"Platform scope denied: {decision.reason}",
                    safe_message="当前用户无权访问此数据范围",
                )

    def assert_mcp_tool_use_grant(
        self,
        *,
        user_id: str,
        tool_identifier: str,
        project_code: str,
    ) -> None:
        if tool_identifier not in self._mcp_tool_identifiers:
            raise ToolPolicyError(
                "Tool use Grant target is not a stable Identifier",
                safe_message="工具使用授权目标不是稳定的 MCP Tool Identifier",
                error_code="mcp_tool_use_denied",
            )
        self.assert_registered_readonly_tool(tool_identifier)
        if not self._is_allowed(
            user_id=user_id,
            resource_type="tool",
            resource_code=tool_identifier,
            action="use",
        ):
            raise ToolPolicyError(
                f"User {user_id} is not allowed to call {tool_identifier}",
                safe_message="当前用户无权调用此工具",
            )
        self.assert_user_can_create_job(user_id=user_id, project_code=project_code)

    def assert_registered_readonly_tool(self, tool_name: str) -> None:
        tool = MCP_TOOL_MANIFEST.get(tool_name)
        if tool is None:
            raise ToolPolicyError(
                f"MCP Tool {tool_name} is not installed",
                safe_message="MCP 工具未安装",
                error_code="mcp_tool_not_installed",
            )
        if not tool.read_only:
            raise ToolPolicyError(
                f"Tool {tool_name} is not read-only",
                safe_message="只允许使用只读工具",
                error_code="mcp_tool_not_readonly",
            )

    def require_action(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_code: str = "*",
        action: str = "manage",
    ) -> None:
        if not self._is_allowed(
            user_id=user_id,
            resource_type=resource_type,
            resource_code=resource_code,
            action=action,
        ):
            raise PermissionDenied(
                f"User {user_id} is not allowed to manage {resource_type}",
                safe_message="当前用户无权管理此配置",
            )

    def _is_allowed(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_code: str,
        action: str,
    ) -> bool:
        try:
            decision = self.authorization_evaluator.decide(
                user_id=user_id,
                resource_type=resource_type,
                resource_code=resource_code,
                action=action,
            )
        except NotFound:
            return False
        return decision.allowed
