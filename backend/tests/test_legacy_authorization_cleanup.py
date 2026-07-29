from __future__ import annotations

import pytest

from app.bootstrap import Container, _build_container, build_test_container
from app.modules.identity.application.legacy_authorization_cleanup import (
    LegacyAuthorizationCleanupService,
)
from app.modules.message_bus.infrastructure.in_memory_bus import InMemoryMessageBus
from app.modules.permission.application.permission_service import PermissionService
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator
from backend.tests.helpers import test_settings as make_test_settings


ADMIN_ID = "user_local_admin"
ADMIN_USERNAME = "local-user"
ADMIN_PASSWORD = "local-admin-change-me"


def _runtime_with_two_logged_in_admins() -> Container:
    runtime = build_test_container(
        make_test_settings(),
        migrate=True,
        seed=True,
    )
    runtime.auth_service.login(
        username=ADMIN_USERNAME,
        password=ADMIN_PASSWORD,
    )
    role = runtime.identity_repository.get_role_by_code("platform-admin")
    assert role is not None
    second = runtime.identity_repository.create_user(
        username="maintenance-admin",
        display_name="Maintenance Admin",
    )
    runtime.identity_repository.set_password_hash(
        str(second["id"]),
        runtime.auth_service.passwords.hash(
            "maintenance-admin-password"
        ),
    )
    runtime.identity_repository.assign_role(
        user_id=str(second["id"]),
        role_id=str(role["id"]),
        assigned_by=ADMIN_ID,
    )
    runtime.auth_service.login(
        username="maintenance-admin",
        password="maintenance-admin-password",
    )
    runtime.database.execute(
        """
        insert into platform_access_grant
          (id, subject_type, subject_code, effect,
           environment_id, base_id, workshop_id,
           tool_scope_json, resource_scope_json, condition_json,
           priority, status, revision, created_at, updated_at)
        values (
          'legacy-cleanup-test-grant', 'user', ?,
          'allow', null, null, null, '[]', '{}', '{}',
          100, 'enabled', 1,
          '2026-07-29T00:00:00+00:00',
          '2026-07-29T00:00:00+00:00'
        )
        """,
        (ADMIN_ID,),
    )
    return runtime


def _count(runtime: Container, table: str) -> int:
    row = runtime.database.execute_one(
        f"select count(*) as count from {table}"
    )
    assert row is not None
    return int(row["count"])


def test_production_composition_uses_only_strict_permission_service() -> None:
    settings = make_test_settings()
    database = Database(settings.database_dsn)
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="strict-composition-test",
        ).run()
        message_bus = InMemoryMessageBus()
        runtime = _build_container(
            settings=settings,
            service_name="api-server",
            publisher=message_bus,
            consumer=None,
            message_bus=None,
            database=database,
            seed=True,
            use_real_claude=False,
        )

        assert type(runtime.permission_service) is PermissionService
    finally:
        database.close()


def test_report_is_exact_read_only_and_verifies_two_admins() -> None:
    runtime = _runtime_with_two_logged_in_admins()
    try:
        service = LegacyAuthorizationCleanupService(runtime.database)
        before_operations = _count(
            runtime,
            "legacy_authorization_cleanup_operation",
        )
        report = service.report()

        assert report["counts"]["permission_policy"] > 0
        assert report["counts"]["platform_access_grant"] > 0
        assert len(report["digest"]) == 64
        assert len(report["targets"]) == sum(
            int(value) for value in report["counts"].values()
        )
        assert report["verified_human_platform_admin_count"] == 2
        assert {
            item["username"]
            for item in report["verified_human_platform_admins"]
        } == {ADMIN_USERNAME, "maintenance-admin"}
        assert all(
            set(target)
            == {"table", "id", "revision", "item_digest"}
            for target in report["targets"]
        )
        assert (
            _count(
                runtime,
                "legacy_authorization_cleanup_operation",
            )
            == before_operations
        )
    finally:
        runtime.database.close()


def test_prepare_requires_verified_backup_and_two_admins() -> None:
    runtime = build_test_container(
        make_test_settings(),
        migrate=True,
        seed=True,
    )
    try:
        service = LegacyAuthorizationCleanupService(runtime.database)
        with pytest.raises(
            ValueError,
            match="backup",
        ):
            service.prepare(
                actor_id=ADMIN_ID,
                backup_reference="",
            )
        with pytest.raises(
            NonRetryableExecutionError,
            match="two verified human platform admins",
        ):
            service.prepare(
                actor_id=ADMIN_ID,
                backup_reference=(
                    "backup://runtime-foundation/test"
                ),
            )
        assert (
            _count(
                runtime,
                "legacy_authorization_cleanup_operation",
            )
            == 0
        )
    finally:
        runtime.database.close()


def test_apply_rejects_wrong_digest_and_post_prepare_drift() -> None:
    runtime = _runtime_with_two_logged_in_admins()
    try:
        service = LegacyAuthorizationCleanupService(runtime.database)
        prepared = service.prepare(
            actor_id=ADMIN_ID,
            backup_reference="backup://runtime-foundation/drift",
        )
        operation_id = str(prepared["operation_id"])

        with pytest.raises(
            NonRetryableExecutionError,
            match="digest mismatch",
        ):
            service.apply(
                operation_id=operation_id,
                expected_digest="f" * 64,
                confirmed_by=ADMIN_ID,
            )

        runtime.database.execute(
            """
            update permission_policy
               set revision = revision + 1
             where id = (
               select id from permission_policy order by id limit 1
             )
            """
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="inventory changed",
        ):
            service.apply(
                operation_id=operation_id,
                expected_digest=str(prepared["digest"]),
                confirmed_by=ADMIN_ID,
            )
        assert _count(runtime, "permission_policy") > 0
        assert _count(runtime, "platform_access_grant") > 0
        operation = runtime.database.execute_one(
            """
            select status
              from legacy_authorization_cleanup_operation
             where id = ?
            """,
            (operation_id,),
        )
        assert operation == {"status": "PREPARED"}
    finally:
        runtime.database.close()


def test_apply_failure_rolls_back_all_legacy_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime_with_two_logged_in_admins()
    try:
        service = LegacyAuthorizationCleanupService(runtime.database)
        prepared = service.prepare(
            actor_id=ADMIN_ID,
            backup_reference="backup://runtime-foundation/rollback",
        )
        before_policy = _count(runtime, "permission_policy")
        before_grants = _count(runtime, "platform_access_grant")
        original_execute = runtime.database.execute

        def fail_grant_delete(sql, params=()):
            if "delete from platform_access_grant" in sql:
                raise RuntimeError("injected legacy cleanup failure")
            return original_execute(sql, params)

        monkeypatch.setattr(
            runtime.database,
            "execute",
            fail_grant_delete,
        )
        with pytest.raises(
            RuntimeError,
            match="injected legacy cleanup failure",
        ):
            service.apply(
                operation_id=str(prepared["operation_id"]),
                expected_digest=str(prepared["digest"]),
                confirmed_by=ADMIN_ID,
            )
        assert _count(runtime, "permission_policy") == before_policy
        assert (
            _count(runtime, "platform_access_grant")
            == before_grants
        )
    finally:
        runtime.database.close()


def test_apply_and_verify_preserve_new_rbac_and_admin_sessions() -> None:
    runtime = _runtime_with_two_logged_in_admins()
    try:
        before_users = _count(runtime, "app_user")
        before_roles = _count(runtime, "rbac_role")
        before_memberships = _count(runtime, "rbac_user_role")
        before_sessions = _count(runtime, "user_session")
        service = LegacyAuthorizationCleanupService(runtime.database)
        prepared = service.prepare(
            actor_id=ADMIN_ID,
            backup_reference="backup://runtime-foundation/success",
            correlation_id="legacy-auth-cleanup-test",
        )
        applied = service.apply(
            operation_id=str(prepared["operation_id"]),
            expected_digest=str(prepared["digest"]),
            confirmed_by=ADMIN_ID,
        )
        assert applied["status"] == "APPLIED"
        assert applied["deleted_counts"]["permission_policy"] > 0
        assert applied["deleted_counts"]["platform_access_grant"] > 0

        verified = service.verify(
            operation_id=str(prepared["operation_id"]),
            actor_id=ADMIN_ID,
        )
        assert verified["status"] == "VERIFIED"
        assert all(verified["checks"].values())
        assert _count(runtime, "permission_policy") == 0
        assert _count(runtime, "platform_access_grant") == 0
        assert _count(runtime, "app_user") == before_users
        assert _count(runtime, "rbac_role") == before_roles
        assert _count(runtime, "rbac_user_role") == before_memberships
        assert _count(runtime, "user_session") == before_sessions
        audit_types = {
            str(row["event_type"])
            for row in runtime.database.execute(
                """
                select event_type
                  from audit_event
                 where event_type like
                       'legacy_authorization_cleanup_%'
                """
            )
        }
        assert audit_types == {
            "legacy_authorization_cleanup_prepared",
            "legacy_authorization_cleanup_applied",
            "legacy_authorization_cleanup_verified",
        }
    finally:
        runtime.database.close()
