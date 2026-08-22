from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

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
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.config import IdentitySettings, Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.exceptions import (
    NonRetryableExecutionError,
    PermissionDenied,
    ToolPolicyError,
)
from backend.tests.helpers import (
    _ensure_agent_publication_mcp_tools,
    enqueue_job_result_for_delivery,
)
from backend.tests.test_business_application_control_plane import draft_payload


ADMIN_ID = "user_local_admin"
ORIGIN = "http://admin.test"


def _settings() -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="test-only-master-key",
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
            allowed_origins=(ORIGIN,),
        ),
    )


def _container():
    return build_test_container(_settings(), migrate=True, seed=True)


def _complete_login_verification(
    c: object,
    *,
    user_id: str,
    username: str,
    password: str,
) -> None:
    c.identity_repository.set_password_hash(
        user_id,
        c.auth_service.passwords.hash(password),
    )
    c.auth_service.login(username=username, password=password)


def _create_verified_platform_admin(
    c: object,
    *,
    role_id: str,
    username: str,
) -> dict[str, object]:
    user = c.identity_repository.create_user(
        username=username,
        display_name=username,
    )
    _complete_login_verification(
        c,
        user_id=str(user["id"]),
        username=username,
        password=f"{username}-verified-password",
    )
    c.identity_repository.assign_role(
        user_id=str(user["id"]),
        role_id=role_id,
        assigned_by=ADMIN_ID,
    )
    return user


def _admin_headers() -> dict[str, str]:
    return {"x-admin-user-id": ADMIN_ID}


def _active_application(
    c: object,
    code: str,
    *,
    capabilities: tuple[str, ...] = (),
) -> dict[str, object]:
    service = c.business_application_service
    mcp_tools = _ensure_agent_publication_mcp_tools(c, capabilities)
    application = service.create(
        actor_id=ADMIN_ID,
        code=code,
        name=f"{code} 应用",
        description="",
        project_code="default",
        owner_user_id=ADMIN_ID,
    )
    payload = draft_payload(route=f"bot:{code}")
    payload["mcp_tools"] = list(mcp_tools)
    revision = service.save_draft(
        actor_id=ADMIN_ID,
        code=code,
        expected_revision=int(application["revision"]),
        payload=payload,
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
        "publication_config_hash": publication["config_hash"],
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


def test_baseline_repeat_preserves_authorization_rows_and_defaults() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="authorization-baseline-test",
    ).run()
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
    repeated = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="authorization-baseline-repeat-test",
    ).run()

    assert repeated.applied == ()
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


def test_assignable_catalog_describes_tools_from_legacy_agent_publications() -> None:
    c = _container()
    application = _active_application(
        c,
        "described-role-tools",
        capabilities=("query_database",),
    )
    frozen = c.database.execute_one(
        """
        select model_description from agent_publication_mcp_tool
         where agent_publication_id = 'agent_publication_default_v1'
           and tool_identifier = 'query_database'
        """
    )
    assert frozen == {"model_description": ""}

    catalog = c.authorization_center_service.assignable_catalog(actor_id=ADMIN_ID)
    catalog_application = next(
        item for item in catalog["applications"] if item["id"] == application["id"]
    )
    assert catalog_application["mcp_tools"] == [
        {
            "tool_identifier": "query_database",
            "description": MCP_TOOL_MANIFEST["query_database"].description,
            "version_constraint": "",
            "display_name_zh": "只读查询数据库",
        }
    ]
    c.database.close()


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


def test_missing_current_role_never_grants_business_application_access() -> None:
    c = _container()
    legacy_user = c.identity_repository.create_user(
        username="legacy-business-user",
        display_name="旧授权用户",
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
    decision = c.business_authorization_service.decide(
        user_id=str(legacy_user["id"]), application_id="app-legacy"
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "no_application_role"
    assert (
        c.database.execute_one(
            "select name from sqlite_master where type = 'table' and name = 'permission_policy'"
        )
        is None
    )
    c.database.close()


def test_multi_role_union_deny_precedence_and_application_scope_isolation() -> None:
    c = _container()
    base_one, base_two = _topology(c)
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
                "tool_identifiers": ["query_database"],
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
                "tool_identifiers": ["query_redis_get"],
                "scopes": [base_two],
            }
        ],
    )

    database = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        tool_identifier="query_database",
        environment="local",
        base="base-one",
        stage="tool_call",
    )
    redis = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        tool_identifier="query_redis_get",
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
        tool_identifier="query_database",
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

    still_allowed_by_current_roles = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
    )
    assert still_allowed_by_current_roles["allowed"] is True
    assert still_allowed_by_current_roles["reason"] == "application_role_allow"
    assert still_allowed_by_current_roles["source_role_codes"] == sorted(
        [first["code"], second["code"]]
    )
    c.database.close()


def test_current_all_saves_explicit_set_and_excludes_future_base() -> None:
    c = _container()
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
    application = _active_application(
        c,
        "current-all-app",
        capabilities=("query_database",),
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
                "tool_identifiers": ["query_database"],
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
        tool_identifier="query_database",
        environment="local",
        base="base-one",
        stage="tool_call",
    )
    future = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        tool_identifier="query_database",
        environment="local",
        base="base-future",
        stage="tool_call",
    )
    assert allowed["allowed"] is True
    assert future["allowed"] is False
    assert future["reason"] == "application_scope_denied"
    c.database.close()


def test_environment_without_bases_is_an_assignable_leaf_scope() -> None:
    c = _container()
    _topology(c)
    application = _active_application(
        c,
        "environment-leaf-app",
        capabilities=("query_database",),
    )
    timestamp = datetime.now(UTC).isoformat()
    c.database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values ('environment-leaf-test', 'test', '测试环境', 'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    user = c.identity_repository.create_user(
        username="environment-leaf-user",
        display_name="环境叶子用户",
    )
    role = _business_role(
        c,
        code="environment-leaf-reader",
        user_id=str(user["id"]),
        applications=[
            {
                "application_id": application["id"],
                "tool_identifiers": ["query_database"],
                "scopes": [{"environment_id": "environment-leaf-test"}],
            }
        ],
    )

    stored = c.authorization_center_repository.list_business_access(str(role["id"]))
    assert [scope["scope_key"] for scope in stored[0]["scopes"]] == ["test"]
    decision = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        tool_identifier="query_database",
        environment="test",
        base="",
        workshop="",
        stage="tool_call",
    )
    assert decision["allowed"] is True
    assert decision["reason"] == "application_role_allow"
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


def test_two_verified_human_platform_admins_and_confirmed_self_removal() -> None:
    c = _container()
    platform_role = c.authorization_center_repository.get_role_by_code("platform-admin")
    assert platform_role is not None
    _complete_login_verification(
        c,
        user_id=ADMIN_ID,
        username="admin",
        password="local-admin-verified-password",
    )
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
    assert last.value.error_code == "platform_admin_invariant"
    assert c.identity_repository.verified_human_platform_admin_count() == 1

    second = _create_verified_platform_admin(
        c,
        role_id=str(platform_role["id"]),
        username="second-platform-admin",
    )
    assert c.identity_repository.verified_human_platform_admin_count() == 2
    with pytest.raises(NonRetryableExecutionError) as two_admins:
        c.authorization_center_service.update_members(
            actor_id=ADMIN_ID,
            role_id=str(platform_role["id"]),
            expected_revision=int(platform_role["membership_revision"]),
            changes=[
                {
                    "user_id": str(second["id"]),
                    "enabled": False,
                    "expires_at": None,
                    "source": "manual",
                }
            ],
            confirmed=True,
        )
    assert two_admins.value.error_code == "platform_admin_invariant"

    _create_verified_platform_admin(
        c,
        role_id=str(platform_role["id"]),
        username="third-platform-admin",
    )
    assert c.identity_repository.verified_human_platform_admin_count() == 3
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
    assert c.identity_repository.verified_human_platform_admin_count() == 2
    sessions = c.identity_repository.list_sessions(ADMIN_ID)
    assert sessions[0]["status"] == "revoked"
    denied = c.database.execute(
        """
        select event_type, status from audit_event
         where event_type = 'platform_admin_invariant_denied'
         order by created_at
        """
    )
    assert len(denied) == 2
    assert {row["status"] for row in denied} == {"DENIED"}
    c.database.close()


def test_user_disable_and_delete_preserve_two_verified_human_admins() -> None:
    c = _container()
    platform_role = c.authorization_center_repository.get_role_by_code("platform-admin")
    assert platform_role is not None
    _complete_login_verification(
        c,
        user_id=ADMIN_ID,
        username="admin",
        password="local-admin-disable-delete-password",
    )
    second = _create_verified_platform_admin(
        c,
        role_id=str(platform_role["id"]),
        username="disable-delete-second-admin",
    )
    assert c.identity_repository.verified_human_platform_admin_count() == 2

    with pytest.raises(NonRetryableExecutionError) as disabled:
        c.identity_admin_service.update_user(
            actor_id=ADMIN_ID,
            user_id=str(second["id"]),
            expected_revision=int(second["revision"]),
            display_name=str(second["display_name"]),
            email=str(second["email"]),
            status="disabled",
        )
    assert disabled.value.error_code == "platform_admin_invariant"
    with pytest.raises(NonRetryableExecutionError) as deleted:
        c.identity_admin_service.delete_user(
            actor_id=ADMIN_ID,
            user_id=str(second["id"]),
            expected_revision=int(second["revision"]),
            confirmed=True,
        )
    assert deleted.value.error_code == "platform_admin_invariant"

    _create_verified_platform_admin(
        c,
        role_id=str(platform_role["id"]),
        username="disable-delete-third-admin",
    )
    removed = c.identity_admin_service.delete_user(
        actor_id=ADMIN_ID,
        user_id=str(second["id"]),
        expected_revision=int(second["revision"]),
        confirmed=True,
    )
    assert removed["id"] == second["id"]
    assert c.database.execute_one("select id from app_user where id = ?", (second["id"],)) is None
    assert c.identity_repository.verified_human_platform_admin_count() == 2
    c.database.close()


def test_concurrent_platform_admin_removals_cannot_commit_below_two(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "platform-admin-invariant.sqlite3"
    settings = replace(_settings(), database_dsn=f"sqlite:///{database_path}")
    first = build_test_container(settings, migrate=True, seed=True)
    platform_role = first.authorization_center_repository.get_role_by_code("platform-admin")
    assert platform_role is not None
    _complete_login_verification(
        first,
        user_id=ADMIN_ID,
        username="admin",
        password="local-admin-concurrency-password",
    )
    second_admin = _create_verified_platform_admin(
        first,
        role_id=str(platform_role["id"]),
        username="concurrent-second-admin",
    )
    third_admin = _create_verified_platform_admin(
        first,
        role_id=str(platform_role["id"]),
        username="concurrent-third-admin",
    )
    second = build_test_container(settings, migrate=False, seed=False)
    barrier = Barrier(2)

    def remove_membership(container: object, user_id: str) -> str:
        membership = container.database.execute_one(
            "select revision from rbac_user_role where user_id = ? and role_id = ?",
            (user_id, platform_role["id"]),
        )
        assert membership is not None
        barrier.wait()
        try:
            container.identity_admin_service.assign_role(
                actor_id=ADMIN_ID,
                user_id=user_id,
                role_id=str(platform_role["id"]),
                enabled=False,
                expected_revision=int(membership["revision"]),
            )
        except NonRetryableExecutionError as exc:
            return exc.error_code
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: remove_membership(*args),
                (
                    (first, str(second_admin["id"])),
                    (second, str(third_admin["id"])),
                ),
            )
        )

    assert sorted(results) == ["committed", "platform_admin_invariant"]
    assert first.identity_repository.verified_human_platform_admin_count() == 2
    assert (
        first.database.execute_one(
            """
            select count(*) as count from audit_event
             where event_type = 'platform_admin_invariant_denied'
            """
        )["count"]
        == 1
    )
    second.database.close()
    first.database.close()


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


def test_ones_tool_uses_agent_application_and_role_intersection_with_server_provenance() -> None:
    c = _container()
    definition = MCP_TOOL_MANIFEST["ones_work_item_search"]
    c.database.execute(
        """
        insert into agent_publication_mcp_tool
          (agent_publication_id, server_code, tool_identifier, schema_hash,
           model_description, selection_order, created_at)
        values ('agent_publication_default_v1', ?, ?, ?, ?, 10, CURRENT_TIMESTAMP)
        """,
        (
            definition.server_code,
            definition.identifier,
            definition.schema_hash,
            definition.description,
        ),
    )
    base_one, _ = _topology(c)
    application = _active_application(
        c,
        "ones-role-intersection",
        capabilities=(definition.identifier,),
    )
    user = c.identity_repository.create_user(
        username="ones-role-reader",
        display_name="ONES role reader",
    )
    role = _business_role(
        c,
        code="ones-role-reader",
        user_id=str(user["id"]),
        applications=[
            {
                "application_id": application["id"],
                "tool_identifiers": [definition.identifier],
                "scopes": [base_one],
            }
        ],
    )

    decision = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        tool_identifier=definition.identifier,
        environment="local",
        base="base-one",
    )
    assert decision["allowed"] is True
    facts = c.business_authorization_service.capture_runtime_facts(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        publication_id=str(application["publication_id"]),
        publication_config_hash=str(application["publication_config_hash"]),
        environment="local",
        base="base-one",
    )
    assert facts["tool_grants"] == [
        {
            "tool_identifier": definition.identifier,
            "server_code": "ones-mcp",
            "schema_hash": definition.schema_hash,
            "source_role_codes": ["ones-role-reader"],
        }
    ]

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
    revoked = c.business_authorization_service.decide(
        user_id=str(user["id"]),
        application_id=str(application["id"]),
        tool_identifier=definition.identifier,
        environment="local",
        base="base-one",
    )
    assert revoked["allowed"] is False


def test_four_stage_reauthorization_blocks_revoked_access_without_data_leak() -> None:
    c = _container()
    base_one, _ = _topology(c)
    application = _active_application(
        c,
        "four-stage-app",
        capabilities=("query_database",),
    )
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
                "tool_identifiers": ["query_database"],
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
        business_application_publication_id=str(application["publication_id"]),
        business_application_config_hash=str(application["publication_config_hash"]),
        routing_context={
            "project_code": "default",
            "environment": "local",
            "base": "base-one",
            "workshop": "",
            "service": "",
        },
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
    enqueue_job_result_for_delivery(c, job.id)
    c.delivery_dispatcher.dispatch_pending(limit=1)
    attempts = c.agent_repository.list_delivery_attempts(job.id)
    assert attempts[0]["status"] == "FAILED"
    assert attempts[0]["error_code"] == "delivery_authorization_denied"
    assert adapter.messages == []
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


def test_baseline_contains_no_destructive_authorization_statement() -> None:
    sql = Path(default_migrations_dir()).joinpath("100_baseline_v1.sql").read_text().lower()
    assert "drop table" not in sql
    assert "\ntruncate " not in sql
    assert "\ndelete from rbac_" not in sql
