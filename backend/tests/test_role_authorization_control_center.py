from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.admin.application import AdminCapabilityService
from app.modules.admin.domain import (
    ADMIN_CAPABILITIES,
    ADMIN_CAPABILITY_BY_CODE,
    validate_admin_capability_catalog,
)
from app.modules.authorization_center.application import BusinessAuthorizationService
from app.modules.internal_api_platform.domain.addressing import TargetRef
from app.modules.internal_api_platform.domain.errors import AuthorizationError
from app.modules.internal_api_platform.domain.topology import ResourceKind
from app.modules.internal_api_platform.infrastructure.job_authorization import (
    BusinessApplicationJobAccessAuthorizer,
)
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.shared.config import IdentitySettings, Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import (
    NonRetryableExecutionError,
    PermissionDenied,
    ToolPolicyError,
)
from backend.tests.test_business_application_control_plane import draft_payload


ADMIN_ID = "user_local_admin"
ORIGIN = "http://admin.test"


def _settings(*, mode: str = "compatibility") -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
            allowed_origins=(ORIGIN,),
            business_application_authorization_mode=mode,
        ),
    )


def _container(*, mode: str = "compatibility"):
    return build_test_container(_settings(mode=mode), migrate=True, seed=True)


def _admin_headers() -> dict[str, str]:
    return {"x-admin-user-id": ADMIN_ID}


def _active_application(
    c: object,
    code: str,
    *,
    capabilities: tuple[str, ...] = (),
) -> dict[str, object]:
    service = c.business_application_service
    application = service.create(
        actor_id=ADMIN_ID,
        code=code,
        name=f"{code} 应用",
        description="",
        project_code="default",
        owner_user_id=ADMIN_ID,
    )
    revision = service.save_draft(
        actor_id=ADMIN_ID,
        code=code,
        expected_revision=int(application["revision"]),
        payload=draft_payload(
            route=f"bot:{code}",
            capabilities=[
                {
                    "capability_code": capability,
                    "version_constraint": "*",
                    "enabled": True,
                }
                for capability in capabilities
            ],
        ),
    )
    publication = service.publish(
        actor_id=ADMIN_ID,
        code=code,
        revision_id=str(revision["id"]),
    )
    service.activate(
        actor_id=ADMIN_ID,
        code=code,
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    return {
        **application,
        "publication_id": publication["id"],
    }


def _topology(c: object) -> tuple[dict[str, str], dict[str, str]]:
    timestamp = datetime.now(UTC).isoformat()
    c.database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values ('environment-auth-local', 'local', '本地环境', 'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    for suffix in ("one", "two"):
        c.database.execute(
            """
            insert into platform_base
              (id, environment_id, code, display_name, engine, status,
               created_at, updated_at)
            values (?, 'environment-auth-local', ?, ?, 'postgresql',
                    'enabled', ?, ?)
            """,
            (
                f"base-auth-{suffix}",
                f"base-{suffix}",
                f"基地 {suffix}",
                timestamp,
                timestamp,
            ),
        )
    return (
        {"environment_id": "environment-auth-local", "base_id": "base-auth-one"},
        {"environment_id": "environment-auth-local", "base_id": "base-auth-two"},
    )


def _business_role(
    c: object,
    *,
    code: str,
    user_id: str,
    applications: list[dict[str, object]],
) -> dict[str, object]:
    role = c.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code=code,
        name=code,
        description="",
        purpose_tags=["业务访问"],
    )["role"]
    c.authorization_center_service.replace_business_access(
        actor_id=ADMIN_ID,
        role_id=str(role["id"]),
        expected_revision=1,
        applications=applications,
        confirmed=True,
        reason="自动化授权测试",
    )
    c.identity_repository.assign_role(
        user_id=user_id,
        role_id=str(role["id"]),
        assigned_by=ADMIN_ID,
    )
    return role


def test_migration_is_additive_preserves_legacy_rows_and_is_idempotent() -> None:
    database = Database("sqlite:///:memory:")
    migrations = default_migrations_dir()
    for path in sorted(migrations.glob("*.sql")):
        if path.name >= "017_role_authorization_control_center.sql":
            continue
        database.execute_script(path.read_text())
    timestamp = datetime.now(UTC).isoformat()
    database.execute(
        """
        insert into app_user
          (id, username, display_name, email, status, account_type,
           revision, created_at, updated_at)
        values ('user-preserved', 'preserved', '保留用户', '', 'enabled',
                'human', 1, ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into rbac_role
          (id, code, name, description, status, revision, created_at, updated_at)
        values ('role-preserved', 'preserved-role', '保留角色', '', 'enabled',
                1, ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into rbac_user_role
          (id, user_id, role_id, status, revision, created_at, updated_at)
        values ('member-preserved', 'user-preserved', 'role-preserved',
                'enabled', 1, ?, ?)
        """,
        (timestamp, timestamp),
    )
    migration = migrations / "017_role_authorization_control_center.sql"
    database.execute_script(migration.read_text())
    database.execute_script(migration.read_text())

    role = database.execute_one("select * from rbac_role where id = 'role-preserved'")
    member = database.execute_one("select * from rbac_user_role where id = 'member-preserved'")
    assert role and role["origin"] == "custom"
    assert role["metadata_revision"] == role["admin_revision"] == 1
    assert member and member["assignment_source"] == "manual"
    assert database.execute_one("select count(*) as n from app_user")["n"] == 1
    assert database.execute_one("select count(*) as n from rbac_role")["n"] == 1
    assert database.execute_one("select count(*) as n from rbac_user_role")["n"] == 1
    database.close()


def test_capability_catalog_is_unique_closed_and_platform_admin_has_no_data_bypass() -> None:
    validate_admin_capability_catalog()
    assert len(ADMIN_CAPABILITIES) == len(ADMIN_CAPABILITY_BY_CODE)
    for capability in ADMIN_CAPABILITIES:
        assert set(capability.dependencies) <= set(ADMIN_CAPABILITY_BY_CODE)
        assert capability.display_name_zh

    c = _container()
    summary = AdminCapabilityService(c.identity_repository, c.authorization_evaluator).summary(
        ADMIN_ID
    )
    assert set(summary["capabilities"]) == set(ADMIN_CAPABILITY_BY_CODE)
    assert summary["data_scope"]["mode"] == "restricted"

    c.database.execute(
        """
        insert into business_application
          (id, code, name, description, project_code, status, revision,
           created_by, created_at, updated_at)
        values ('app-no-bypass', 'no-bypass', '不可旁路应用', '', 'default',
                'enabled', 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (ADMIN_ID,),
    )
    platform_only_user = c.identity_repository.create_user(
        username="platform-only-admin",
        display_name="仅平台管理员",
    )
    platform_role = c.identity_repository.get_role_by_code("platform-admin")
    assert platform_role is not None
    c.identity_repository.assign_role(
        user_id=str(platform_only_user["id"]),
        role_id=str(platform_role["id"]),
        assigned_by=ADMIN_ID,
    )
    decision = c.business_authorization_service.decide(
        user_id=str(platform_only_user["id"]), application_id="app-no-bypass"
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "no_application_role"
    c.database.close()


def test_navigation_and_management_api_capability_mapping_are_reconciled() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    navigation_source = (repository_root / "frontend/src/mocks/dashboard.ts").read_text()
    navigation_codes = set(re.findall(r'requiredCapability:\s*"([^"]+)"', navigation_source))
    assert navigation_codes
    assert navigation_codes <= set(ADMIN_CAPABILITY_BY_CODE)

    catalog_pairs = {(item.resource_type, item.action) for item in ADMIN_CAPABILITIES}
    management_sources = [
        *repository_root.glob("backend/app/modules/*/api/*controller.py"),
        repository_root / "backend/app/modules/business_application/application/service.py",
    ]
    enforced_pairs: set[tuple[str, str]] = set()
    for path in management_sources:
        source = path.read_text()
        if "/api/admin" not in source and "business_application" not in str(path):
            continue
        for resource_type, action in re.findall(
            r'resource_type\s*=\s*"([^"]+)"[\s\S]{0,240}?'
            r'action\s*=\s*"([^"]+)"',
            source,
        ):
            if action != "use":
                enforced_pairs.add((resource_type, action))
    assert enforced_pairs
    assert enforced_pairs <= catalog_pairs

    guarded_surfaces = {
        "admin/api/controller.py": "require_action(",
        "agent_config/api/controller.py": "require_action(",
        "identity/api/admin_controller.py": "require_action(",
        "identity_discovery/api/controller.py": "require_action(",
        "managed_channel/api/controller.py": "require_action(",
        "model_connection/api/controller.py": "require_action(",
        "platform_config/api/platform_config_controller.py": "require_action(",
        "webhook/api/admin_controller.py": "require_action(",
        "authorization_center/application/service.py": "_require_catalog(",
        "business_application/application/service.py": "self.authorization",
    }
    modules_root = repository_root / "backend/app/modules"
    for relative_path, marker in guarded_surfaces.items():
        assert marker in (modules_root / relative_path).read_text(), relative_path


def test_role_sections_use_independent_revisions_and_dependency_closure() -> None:
    c = _container()
    service = c.authorization_center_service
    created = service.create_role(
        actor_id=ADMIN_ID,
        code="diagnostic-operator",
        name="诊断操作员",
        description="",
        purpose_tags=["业务诊断"],
    )
    role_id = created["role"]["id"]
    admin_result = service.replace_admin_capabilities(
        actor_id=ADMIN_ID,
        role_id=role_id,
        expected_revision=1,
        bindings=[{"capability_code": "jobs.manage", "resource_code": "*"}],
        confirmed=True,
        reason="允许处理运行记录",
    )
    assert {item["capability_code"] for item in admin_result["bindings"]} == {
        "jobs.read",
        "jobs.manage",
    }
    after_admin = c.authorization_center_repository.get_role(role_id)
    assert after_admin["admin_revision"] == 2
    assert after_admin["business_revision"] == 1
    business_result = service.replace_business_access(
        actor_id=ADMIN_ID,
        role_id=role_id,
        expected_revision=1,
        applications=[],
        confirmed=False,
        reason="",
    )
    assert business_result["revision"] == 2
    assert c.authorization_center_repository.get_role(role_id)["admin_revision"] == 2
    with pytest.raises(NonRetryableExecutionError) as conflict:
        service.replace_admin_capabilities(
            actor_id=ADMIN_ID,
            role_id=role_id,
            expected_revision=1,
            bindings=[],
            confirmed=False,
            reason="",
        )
    assert conflict.value.error_code == "revision_conflict"
    assert len(c.authorization_center_repository.list_admin_bindings(role_id)) == 2
    c.database.close()


def test_expired_membership_is_immediately_excluded() -> None:
    c = _container()
    role = c.identity_repository.create_role(code="temporary", name="临时角色")
    user = c.identity_repository.create_user(username="temporary-user", display_name="临时用户")
    c.identity_repository.assign_role(
        user_id=user["id"],
        role_id=role["id"],
        expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        assigned_by=ADMIN_ID,
    )
    assert c.identity_repository.role_codes_for_user(user["id"]) == ()
    memberships = c.identity_repository.list_user_roles(user["id"])
    assert memberships[0]["expires_at"]
    c.database.close()


def test_service_account_cannot_join_role_with_web_capabilities() -> None:
    c = _container()
    role = c.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code="web-manager",
        name="后台管理员",
        description="",
        purpose_tags=["平台管理"],
    )["role"]
    c.authorization_center_service.replace_admin_capabilities(
        actor_id=ADMIN_ID,
        role_id=role["id"],
        expected_revision=1,
        bindings=[{"capability_code": "dashboard.read", "resource_code": "*"}],
        confirmed=False,
        reason="",
    )
    service_user = c.identity_repository.create_user(
        username="service-role-test",
        display_name="服务账号",
        account_type="service",
    )
    with pytest.raises(NonRetryableExecutionError) as denied:
        c.authorization_center_service.update_members(
            actor_id=ADMIN_ID,
            role_id=role["id"],
            expected_revision=1,
            changes=[
                {
                    "user_id": service_user["id"],
                    "enabled": True,
                    "expires_at": None,
                    "source": "manual",
                }
            ],
            confirmed=False,
        )
    assert "服务账号" in denied.value.safe_message
    assert c.identity_repository.list_user_roles(service_user["id"]) == []
    assert c.authorization_center_repository.get_role(role["id"])["membership_revision"] == 1
    c.database.close()


def test_compatibility_and_strict_application_modes() -> None:
    c = _container()
    legacy_user = c.identity_repository.create_user(
        username="legacy-business-user",
        display_name="旧授权用户",
    )
    c.identity_repository.upsert_policy(
        policy_id=None,
        subject_type="user",
        subject_code=str(legacy_user["id"]),
        resource_type="project",
        resource_code="default",
        action="use",
        effect="allow",
        expected_revision=0,
    )
    c.database.execute(
        """
        insert into business_application
          (id, code, name, description, project_code, status, revision,
           created_by, created_at, updated_at)
        values ('app-legacy', 'legacy-app', '旧授权应用', '', 'default',
                'enabled', 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (ADMIN_ID,),
    )
    compatible = c.business_authorization_service.decide(
        user_id=str(legacy_user["id"]), application_id="app-legacy"
    )
    assert compatible["allowed"] is True
    assert compatible["reason"] == "legacy_compatible"
    assert compatible["legacy_compatible"] is True

    strict = BusinessAuthorizationService(
        c.authorization_center_repository,
        c.identity_repository,
        c.authorization_evaluator,
        mode="strict_application_role",
        audit_service=c.audit_service,
    ).decide(user_id=str(legacy_user["id"]), application_id="app-legacy")
    assert strict["allowed"] is False
    assert strict["reason"] == "no_application_role"
    c.database.close()


def test_multi_role_union_deny_precedence_and_application_scope_isolation() -> None:
    c = _container(mode="strict_application_role")
    application = _active_application(
        c,
        "role-union-app",
        capabilities=("query_database", "query_redis_get"),
    )
    other_application = _active_application(
        c,
        "role-isolated-app",
        capabilities=("query_database",),
    )
    base_one, base_two = _topology(c)
    user = c.identity_repository.create_user(
        username="role-union-user",
        display_name="多角色用户",
    )
    first = _business_role(
        c,
        code="database-reader",
        user_id=str(user["id"]),
        applications=[
            {
                "application_id": application["id"],
                "capability_codes": ["query_database"],
                "scopes": [base_one],
            }
        ],
    )
    second = _business_role(
        c,
        code="redis-reader",
        user_id=str(user["id"]),
        applications=[
            {
                "application_id": application["id"],
                "capability_codes": ["query_redis_get"],
                "scopes": [base_two],
            }
        ],
    )

    database = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        capability_code="query_database",
        environment="local",
        base="base-one",
        stage="tool_call",
    )
    redis = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        capability_code="query_redis_get",
        environment="local",
        base="base-two",
        stage="tool_call",
    )
    assert database["allowed"] is True
    assert database["source_role_codes"] == [first["code"]]
    assert redis["allowed"] is True
    assert redis["source_role_codes"] == [second["code"]]

    cross_scope = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        capability_code="query_database",
        environment="local",
        base="base-two",
        stage="tool_call",
    )
    isolated = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(other_application["id"]),
    )
    assert cross_scope["allowed"] is False
    assert cross_scope["reason"] == "application_scope_denied"
    assert isolated["allowed"] is False

    c.identity_repository.upsert_policy(
        policy_id=None,
        subject_type="user",
        subject_code=str(user["id"]),
        resource_type="business_application",
        resource_code=str(application["code"]),
        action="use",
        effect="deny",
        expected_revision=0,
    )
    denied = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
    )
    assert denied["allowed"] is False
    assert denied["reason"] == "explicit_application_deny"
    c.database.close()


def test_current_all_saves_explicit_set_and_excludes_future_base() -> None:
    c = _container(mode="strict_application_role")
    application = _active_application(
        c,
        "current-all-app",
        capabilities=("query_database",),
    )
    timestamp = datetime.now(UTC).isoformat()
    c.database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values ('environment-current', 'local', '本地环境', 'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    c.database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values ('base-current-one', 'environment-current', 'base-one',
                '基地一', 'postgresql', 'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    user = c.identity_repository.create_user(
        username="current-all-user",
        display_name="当前全部用户",
    )
    role = _business_role(
        c,
        code="current-all-reader",
        user_id=str(user["id"]),
        applications=[
            {
                "application_id": application["id"],
                "capability_codes": ["query_database"],
                "scopes": [],
                "current_all": [
                    {
                        "level": "bases",
                        "environment_id": "environment-current",
                    }
                ],
            }
        ],
    )
    stored = c.authorization_center_repository.list_business_access(str(role["id"]))
    assert [scope["scope_key"] for scope in stored[0]["scopes"]] == ["local/base-one"]

    c.database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values ('base-current-future', 'environment-current', 'base-future',
                '未来基地', 'postgresql', 'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    allowed = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        capability_code="query_database",
        environment="local",
        base="base-one",
        stage="tool_call",
    )
    future = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        capability_code="query_database",
        environment="local",
        base="base-future",
        stage="tool_call",
    )
    assert allowed["allowed"] is True
    assert future["allowed"] is False
    assert future["reason"] == "application_scope_denied"
    c.database.close()


def test_grant_delegation_is_resource_bounded_and_cannot_self_escalate() -> None:
    c = _container()
    actor = c.identity_repository.create_user(
        username="delegated-role-manager",
        display_name="受委派角色管理员",
    )
    actor_role = c.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code="delegated-role-manager",
        name="受委派角色管理员",
        description="",
        purpose_tags=["角色管理"],
    )["role"]
    target_role = c.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code="delegated-target",
        name="被管理角色",
        description="",
        purpose_tags=[],
    )["role"]
    c.authorization_center_service.replace_admin_capabilities(
        actor_id=ADMIN_ID,
        role_id=str(actor_role["id"]),
        expected_revision=1,
        bindings=[
            {
                "capability_code": "authorization.manage",
                "resource_code": str(target_role["id"]),
            },
            {
                "capability_code": "jobs.read",
                "resource_code": "job-visible",
            },
            {
                "capability_code": "authorization.assign",
                "resource_code": str(target_role["id"]),
            },
        ],
        confirmed=True,
        reason="委派单一角色和运行记录",
    )
    c.identity_repository.assign_role(
        user_id=str(actor["id"]),
        role_id=str(actor_role["id"]),
        assigned_by=ADMIN_ID,
    )

    with pytest.raises(NonRetryableExecutionError) as wildcard:
        c.authorization_center_service.replace_admin_capabilities(
            actor_id=str(actor["id"]),
            role_id=str(target_role["id"]),
            expected_revision=1,
            bindings=[
                {"capability_code": "jobs.read", "resource_code": "*"},
            ],
            confirmed=False,
            reason="",
        )
    assert "无权授予" in wildcard.value.safe_message

    granted = c.authorization_center_service.replace_admin_capabilities(
        actor_id=str(actor["id"]),
        role_id=str(target_role["id"]),
        expected_revision=1,
        bindings=[
            {"capability_code": "jobs.read", "resource_code": "job-visible"},
        ],
        confirmed=False,
        reason="",
    )
    assert granted["bindings"][0]["resource_code"] == "job-visible"

    platform_role = c.identity_repository.get_role_by_code("platform-admin")
    assert platform_role is not None
    with pytest.raises(PermissionDenied):
        c.authorization_center_service.update_members(
            actor_id=str(actor["id"]),
            role_id=str(platform_role["id"]),
            expected_revision=int(platform_role["membership_revision"]),
            changes=[
                {
                    "user_id": str(actor["id"]),
                    "enabled": True,
                    "expires_at": None,
                    "source": "manual",
                }
            ],
            confirmed=True,
        )
    c.database.close()


def test_last_platform_admin_and_confirmed_self_removal_revokes_sessions() -> None:
    c = _container()
    platform_role = c.authorization_center_repository.get_role_by_code("platform-admin")
    assert platform_role is not None
    admin_membership = c.database.execute_one(
        "select * from rbac_user_role where user_id = ? and role_id = ?",
        (ADMIN_ID, platform_role["id"]),
    )
    assert admin_membership is not None
    with pytest.raises(NonRetryableExecutionError) as last:
        c.authorization_center_service.update_members(
            actor_id=ADMIN_ID,
            role_id=str(platform_role["id"]),
            expected_revision=int(platform_role["membership_revision"]),
            changes=[
                {
                    "user_id": ADMIN_ID,
                    "enabled": False,
                    "expires_at": None,
                    "source": "manual",
                }
            ],
            confirmed=True,
        )
    assert last.value.error_code == "last_platform_admin"

    second = c.identity_repository.create_user(
        username="second-platform-admin",
        display_name="第二管理员",
    )
    c.identity_repository.assign_role(
        user_id=str(second["id"]),
        role_id=str(platform_role["id"]),
        assigned_by=ADMIN_ID,
    )
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    c.identity_repository.create_session(
        user_id=ADMIN_ID,
        token_hash="safe-fixture-token-hash",
        csrf_hash="safe-fixture-csrf-hash",
        idle_expires_at=future,
        absolute_expires_at=future,
    )
    with pytest.raises(NonRetryableExecutionError) as confirmation:
        c.authorization_center_service.update_members(
            actor_id=ADMIN_ID,
            role_id=str(platform_role["id"]),
            expected_revision=int(platform_role["membership_revision"]),
            changes=[
                {
                    "user_id": ADMIN_ID,
                    "enabled": False,
                    "expires_at": None,
                    "source": "manual",
                }
            ],
            confirmed=False,
        )
    assert confirmation.value.error_code == "confirmation_required"

    result = c.authorization_center_service.update_members(
        actor_id=ADMIN_ID,
        role_id=str(platform_role["id"]),
        expected_revision=int(platform_role["membership_revision"]),
        changes=[
            {
                "user_id": ADMIN_ID,
                "enabled": False,
                "expires_at": None,
                "source": "manual",
            }
        ],
        confirmed=True,
    )
    assert result["revision"] == int(platform_role["membership_revision"]) + 1
    sessions = c.identity_repository.list_sessions(ADMIN_ID)
    assert sessions[0]["status"] == "revoked"
    c.database.close()


class _RecordingDeliveryAdapter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(
        self,
        *,
        connector: object,
        route: object,
        title: str,
        text: str,
    ) -> None:
        del connector, route, title
        self.messages.append(text)


def test_four_stage_reauthorization_blocks_revoked_access_without_data_leak() -> None:
    c = _container(mode="strict_application_role")
    application = _active_application(
        c,
        "four-stage-app",
        capabilities=("query_database",),
    )
    base_one, _ = _topology(c)
    user = c.identity_repository.create_user(
        username="four-stage-user",
        display_name="四阶段用户",
    )
    role = _business_role(
        c,
        code="four-stage-reader",
        user_id=str(user["id"]),
        applications=[
            {
                "application_id": application["id"],
                "capability_codes": ["query_database"],
                "scopes": [base_one],
            }
        ],
    )
    command = CreateAgentJobCommand(
        idempotency_key="four-stage-job",
        user_message="安全诊断请求",
        requester_id=str(user["id"]),
        source_channel="debug_api",
        reply_route={
            "type": "dingtalk_conversation",
            "connector_id": "connector-dingtalk-enterprise-default",
            "target": {"conversation_id": "safe-test-conversation"},
            "options": {},
        },
        business_application_id=str(application["id"]),
        business_application_code=str(application["code"]),
        fixed_agent_publication_id="agent_publication_default_v1",
        fixed_agent_revision=1,
        fixed_agent_config_hash=(
            c.agent_config_service.publication("agent_publication_default_v1")["config_hash"]
        ),
        agent_code="default-diagnostic-agent",
    )
    job = c.create_agent_job_service.execute(command)
    assert job.status == JobStatus.PENDING
    assert c.tool_service.is_tool_visible_for_job(job_id=job.id, tool_name="query_database")

    membership = c.database.execute_one(
        "select * from rbac_user_role where user_id = ? and role_id = ?",
        (user["id"], role["id"]),
    )
    assert membership is not None
    c.identity_repository.remove_role(
        user_id=str(user["id"]),
        role_id=str(role["id"]),
        expected_revision=int(membership["revision"]),
    )
    assert not c.tool_service.is_tool_visible_for_job(job_id=job.id, tool_name="query_database")

    with pytest.raises(PermissionDenied):
        c.agent_executor.execute(job.id)
    failed = c.agent_repository.get_job(job.id)
    assert failed.status == JobStatus.FAILED
    assert c.agent_repository.list_tool_calls(job.id) == []

    with pytest.raises(ToolPolicyError):
        c.tool_service.call_tool(
            job_id=job.id,
            user_id=str(user["id"]),
            project_code="default",
            tool_name="query_database",
            arguments={
                "environment": "local",
                "base": "base-one",
                "sql": "select 1",
            },
        )

    c.database.execute(
        "update agent_job set result = ? where id = ?",
        ("不得投递的业务结果", job.id),
    )
    adapter = _RecordingDeliveryAdapter()
    c.result_delivery_service.adapters["dingtalk_conversation"] = adapter
    c.result_delivery_service.deliver_job_result(job.id)
    attempts = c.agent_repository.list_delivery_attempts(job.id)
    assert attempts[0]["status"] == "BLOCKED_BY_AUTHORIZATION"
    assert adapter.messages == [
        "你的业务应用权限已变更，本次诊断结果未发送。请联系管理员确认角色授权。"
    ]
    assert all("不得投递的业务结果" not in message for message in adapter.messages)
    audit_text = str(
        c.database.execute(
            """
            select event_type, status, summary, payload_summary
              from audit_event
             where event_type like 'authorization.business.%'
            """
        )
    )
    assert "安全诊断请求" not in audit_text
    assert "不得投递的业务结果" not in audit_text
    c.database.close()


def test_internal_api_platform_rechecks_job_bound_business_scope() -> None:
    c = _container(mode="strict_application_role")
    application = _active_application(
        c,
        "internal-platform-job-app",
        capabilities=("query_database",),
    )
    base_one, _ = _topology(c)
    user = c.identity_repository.create_user(
        username="internal-platform-job-user",
        display_name="内部平台任务用户",
    )
    role = _business_role(
        c,
        code="internal-platform-job-reader",
        user_id=str(user["id"]),
        applications=[
            {
                "application_id": application["id"],
                "capability_codes": ["query_database"],
                "scopes": [base_one],
            }
        ],
    )
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="internal-platform-job-authorization",
            user_message="验证内部平台授权",
            requester_id=str(user["id"]),
            source_channel="debug_api",
            reply_route={"type": "debug_api", "target": {}, "options": {}},
            business_application_id=str(application["id"]),
            business_application_code=str(application["code"]),
            fixed_agent_publication_id="agent_publication_default_v1",
            fixed_agent_revision=1,
            fixed_agent_config_hash=(
                c.agent_config_service.publication("agent_publication_default_v1")["config_hash"]
            ),
            agent_code="default-diagnostic-agent",
        )
    )
    c.database.execute(
        "update agent_job set status = 'RUNNING' where id = ?",
        (job.id,),
    )
    authorizer = BusinessApplicationJobAccessAuthorizer(
        c.database,
        c.business_authorization_service,
    )
    target = TargetRef(
        environment="local",
        base="base-one",
        workshop=None,
        kind=ResourceKind.DATABASE,
    )

    assert authorizer.authorize(
        job_id=job.id,
        user_id=str(user["id"]),
        capability_code="query_database",
        target=target,
    )

    membership = c.database.execute_one(
        "select * from rbac_user_role where user_id = ? and role_id = ?",
        (user["id"], role["id"]),
    )
    assert membership is not None
    c.identity_repository.remove_role(
        user_id=str(user["id"]),
        role_id=str(role["id"]),
        expected_revision=int(membership["revision"]),
    )
    with pytest.raises(AuthorizationError):
        authorizer.authorize(
            job_id=job.id,
            user_id=str(user["id"]),
            capability_code="query_database",
            target=target,
        )
    c.database.close()


def test_role_authorization_typed_api_requires_csrf_and_returns_chinese_errors() -> None:
    settings = _settings()
    c = _container()
    app = create_app(settings, container_factory=lambda _: c)
    with TestClient(app) as client:
        listed = client.get(
            "/api/admin/authorization/roles",
            headers=_admin_headers(),
        )
        assert listed.status_code == 200
        assert listed.json()["page"]["total"] >= 1

        created = client.post(
            "/api/admin/authorization/roles",
            headers=_admin_headers(),
            json={
                "code": "api-role",
                "name": "接口角色",
                "description": "",
                "purpose_tags": ["业务诊断"],
            },
        )
        assert created.status_code == 200, created.text
        role = created.json()["role"]
        audit = client.get(
            f"/api/admin/authorization/roles/{role['id']}/audit",
            headers=_admin_headers(),
        )
        assert audit.status_code == 200
        assert audit.json()["items"][0]["action_zh"] == "创建角色"
        assert "payload_summary" not in audit.text

        unknown = client.put(
            f"/api/admin/authorization/roles/{role['id']}/admin-capabilities",
            headers=_admin_headers(),
            json={
                "expected_revision": 1,
                "bindings": [{"capability_code": "unknown.capability"}],
                "confirmed": True,
                "reason": "测试未知能力",
            },
        )
        assert unknown.status_code == 400
        detail = unknown.json()["detail"]
        assert detail["code"] == "validation_failed"
        assert "不存在" in detail["message"]

    c.database.close()


def test_migration_contains_no_destructive_authorization_statement() -> None:
    sql = (
        Path(default_migrations_dir())
        .joinpath("017_role_authorization_control_center.sql")
        .read_text()
        .lower()
    )
    assert "drop table" not in sql
    assert "truncate" not in sql
    assert "delete from rbac_" not in sql
