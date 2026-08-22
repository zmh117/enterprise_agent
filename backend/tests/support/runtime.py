from __future__ import annotations

import json

from app.bootstrap import Container, build_test_container
from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.identity.application import AuthorizationEvaluator
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import DingTalkSettings, Settings


def ensure_historical_typescript_agent(runtime: Container) -> None:
    """Insert a minimal immutable legacy fact without making it a seed default."""

    if runtime.database.execute_one(
        "select id from agent_definition where code = ?",
        ("typescript-diagnostic-agent",),
    ):
        return
    config = {
        "business_role": "Historical TypeScript diagnostic Agent",
        "business_instructions": "Historical read-only fixture.",
        "model_policy": {"model": "claude-sonnet-4-20250514"},
        "execution": {"max_turns": 12, "timeout_seconds": 300},
        "skills": [],
        "routing": {"project_code": "default"},
        "channels": {"ingress": [], "delivery": []},
        "mcp_tool_ids": [],
    }
    snapshot = {key: value for key, value in config.items() if key != "mcp_tool_ids"}
    snapshot.update(
        {
            "runtime_kind": "typescript-v1",
            "mcp_tool_envelope": [],
        }
    )
    with runtime.database.unit_of_work():
        runtime.database.execute(
            """
            insert into agent_definition
              (id, code, name, description, project_code, status,
               current_publication_id, classification, runtime_kind, revision,
               created_by, created_at, updated_at)
            values (?, ?, ?, ?, 'default', 'enabled', ?, 'internal_diagnostic',
                    'typescript-v1', 1, 'user_local_admin', CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP)
            """,
            (
                "agent_typescript_diagnostic",
                "typescript-diagnostic-agent",
                "TypeScript 诊断 Agent",
                "Historical retired TypeScript Agent",
                "agent_publication_typescript_v1",
            ),
        )
        runtime.database.execute(
            """
            insert into agent_revision
              (id, agent_id, revision, status, config_json, config_hash,
               validation_json, created_by, created_at, updated_at)
            values (?, ?, 1, 'published', ?, ?, '{"valid":true,"errors":[]}',
                    'user_local_admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                "agent_revision_typescript_v1",
                "agent_typescript_diagnostic",
                json.dumps(config, ensure_ascii=False, separators=(",", ":")),
                snapshot_hash(config),
            ),
        )
        runtime.database.execute(
            """
            insert into agent_publication
              (id, agent_id, revision_id, revision, schema_version,
               snapshot_json, config_hash, runtime_kind, status, published_by,
               published_at)
            values (?, ?, ?, 1, 2, ?, ?, 'typescript-v1', 'active',
                    'user_local_admin', CURRENT_TIMESTAMP)
            """,
            (
                "agent_publication_typescript_v1",
                "agent_typescript_diagnostic",
                "agent_revision_typescript_v1",
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                snapshot_hash(snapshot),
            ),
        )


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
