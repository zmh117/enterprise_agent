from __future__ import annotations

from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.shared.exceptions import PermissionDenied, ToolPolicyError


class PermissionService:
    def __init__(self, config_repository: ConfigurationRepository) -> None:
        self.config_repository = config_repository

    def assert_user_can_create_job(self, *, user_id: str, project_code: str) -> None:
        if not self.config_repository.is_allowed(
            subject_code=user_id, resource_type="project", resource_code=project_code
        ):
            raise PermissionDenied(
                f"User {user_id} is not allowed for {project_code}",
                safe_message="User is not allowed to use Agent for this scope",
            )

    def assert_tool_allowed(self, *, user_id: str, tool_name: str, project_code: str) -> None:
        tool = self.config_repository.get_tool(tool_name)
        if not tool or int(tool["enabled"]) != 1:
            raise ToolPolicyError(
                f"Tool {tool_name} is disabled",
                safe_message="Tool is disabled",
            )
        if int(tool["read_only"]) != 1:
            raise ToolPolicyError(
                f"Tool {tool_name} is not read-only",
                safe_message="Only read-only tools are allowed",
            )
        if not self.config_repository.is_allowed(
            subject_code=user_id, resource_type="tool", resource_code=tool_name
        ):
            raise ToolPolicyError(
                f"User {user_id} is not allowed to call {tool_name}",
                safe_message="User is not allowed to call this tool",
            )
        self.assert_user_can_create_job(user_id=user_id, project_code=project_code)
