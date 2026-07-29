from __future__ import annotations

from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.job.infrastructure.repositories import ConfigurationRepository
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
        self.assert_registered_readonly_tool(tool_name)
        if not self._is_allowed(
            user_id=user_id,
            resource_type="tool",
            resource_code=tool_name,
            action="use",
        ):
            raise ToolPolicyError(
                f"User {user_id} is not allowed to call {tool_name}",
                safe_message="当前用户无权调用此工具",
            )
        self.assert_user_can_create_job(user_id=user_id, project_code=project_code)
        if tool_name in DATA_SCOPED_TOOLS:
            scope = scope or {}
            decision = self.authorization_evaluator.decide_platform_scope(
                user_id=user_id,
                environment=scope.get("environment", ""),
                base=scope.get("base", ""),
                workshop=scope.get("workshop", ""),
                tool_name=tool_name,
            )
            if not decision.allowed:
                raise ToolPolicyError(
                    f"Platform scope denied: {decision.reason}",
                    safe_message="当前用户无权访问此数据范围",
                )

    def assert_registered_readonly_tool(self, tool_name: str) -> None:
        tool = self.config_repository.get_tool(tool_name)
        if not tool or int(tool["enabled"]) != 1:
            raise ToolPolicyError(
                f"Tool {tool_name} is disabled",
                safe_message="工具已停用",
            )
        if int(tool["read_only"]) != 1:
            raise ToolPolicyError(
                f"Tool {tool_name} is not read-only",
                safe_message="只允许使用只读工具",
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
