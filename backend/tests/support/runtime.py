from __future__ import annotations

from app.bootstrap import Container, build_test_container
from app.modules.identity.application import AuthorizationEvaluator
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import DingTalkSettings, Settings


def test_settings(secret: str = "test-secret") -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="test-only-master-key",
        dingtalk=DingTalkSettings(secret=secret),
    )


class DirectJobTestPermissionService(PermissionService):
    """Explicit test substitute for low-level Jobs without an Application."""

    def assert_user_can_create_job(self, *, user_id: str, project_code: str) -> None:
        del user_id, project_code

    def require_action(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_code: str = "*",
        action: str = "manage",
    ) -> None:
        if resource_type == "agent" and action == "use":
            return
        super().require_action(
            user_id=user_id,
            resource_type=resource_type,
            resource_code=resource_code,
            action=action,
        )

    def assert_mcp_tool_use_grant(
        self,
        *,
        user_id: str,
        tool_identifier: str,
        project_code: str,
    ) -> None:
        del user_id, project_code
        self.assert_registered_readonly_tool(tool_identifier)


def direct_job_permission_service_factory(
    repository: ConfigurationRepository,
    evaluator: AuthorizationEvaluator,
) -> PermissionService:
    return DirectJobTestPermissionService(
        repository,
        authorization_evaluator=evaluator,
    )


def container(
    *,
    configure_seed_secrets: bool = True,
    allow_direct_jobs: bool = True,
) -> Container:
    runtime = build_test_container(
        test_settings(),
        migrate=True,
        seed=True,
        configure_seed_secrets=configure_seed_secrets,
        permission_service_factory=(
            direct_job_permission_service_factory if allow_direct_jobs else None
        ),
    )
    if allow_direct_jobs:
        runtime.create_agent_job_service.published_agent_runtime_enabled = True
        runtime.create_agent_job_service.runtime_readiness_guard = None
    return runtime
