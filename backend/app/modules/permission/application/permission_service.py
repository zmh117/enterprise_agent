from __future__ import annotations

from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.shared.exceptions import NotFound, PermissionDenied


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
