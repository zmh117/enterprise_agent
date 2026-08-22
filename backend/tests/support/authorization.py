from __future__ import annotations

from datetime import UTC, datetime

from app.bootstrap import Container


def grant_test_application_access(
    container: Container,
    *,
    application_id: str,
    role_code: str,
    user_id: str = "user_local_admin",
    capabilities: tuple[str, ...] = (),
    scopes: tuple[dict[str, str], ...] = (),
) -> dict[str, object]:
    role = container.authorization_center_service.create_role(
        actor_id="user_local_admin",
        code=role_code,
        name=role_code,
        description="Explicit strict application-role authorization for tests",
        purpose_tags=["业务运行"],
    )["role"]
    container.authorization_center_service.replace_business_access(
        actor_id="user_local_admin",
        role_id=str(role["id"]),
        expected_revision=1,
        applications=[
            {
                "application_id": application_id,
                "tool_identifiers": list(capabilities),
                "scopes": list(scopes),
            }
        ],
        confirmed=True,
        reason="自动化严格授权测试",
    )
    container.identity_repository.assign_role(
        user_id=user_id,
        role_id=str(role["id"]),
        assigned_by="user_local_admin",
    )
    return role


def prepare_debug_application_access(
    container: Container,
    *,
    application_code: str,
    role_code: str,
    user_id: str = "user_local_admin",
    capabilities: tuple[str, ...] = (),
    additional_deliveries: tuple[dict[str, object], ...] = (),
    attachments_enabled: bool = False,
    task_file_features: dict[str, bool] | None = None,
) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat()
    environment_id = f"environment-{application_code}"
    base_id = f"base-{application_code}"
    container.database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values (?, 'local', '本地环境', 'enabled', ?, ?)
        """,
        (environment_id, timestamp, timestamp),
    )
    container.database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values (?, ?, 'debug-base', '调试基地', 'postgresql', 'enabled', ?, ?)
        """,
        (base_id, environment_id, timestamp, timestamp),
    )
    from backend.tests.support.applications import activate_dingtalk_test_application

    publication = activate_dingtalk_test_application(
        container,
        code=application_code,
        robot_code=f"robot-{application_code}",
        capabilities=capabilities,
        additional_deliveries=additional_deliveries,
        attachments_enabled=attachments_enabled,
        task_file_features=task_file_features,
    )
    application = container.business_application_repository.get_by_code(application_code)
    role = container.authorization_center_service.create_role(
        actor_id="user_local_admin",
        code=role_code,
        name=role_code,
        description="Debug API integration test role",
        purpose_tags=["业务诊断"],
    )["role"]
    container.authorization_center_service.replace_admin_capabilities(
        actor_id="user_local_admin",
        role_id=str(role["id"]),
        expected_revision=1,
        bindings=[
            {
                "capability_code": "agent.debug.execute",
                "resource_code": "*",
            }
        ],
        confirmed=True,
        reason="Debug API integration test",
    )
    container.authorization_center_service.replace_business_access(
        actor_id="user_local_admin",
        role_id=str(role["id"]),
        expected_revision=1,
        applications=[
            {
                "application_id": str(application["id"]),
                "tool_identifiers": list(capabilities),
                "scopes": [
                    {
                        "environment_id": environment_id,
                        "base_id": base_id,
                    }
                ],
            }
        ],
        confirmed=True,
        reason="Debug API integration test",
    )
    container.identity_repository.assign_role(
        user_id=user_id,
        role_id=str(role["id"]),
        assigned_by="user_local_admin",
    )
    options = container.debug_job_access_service.available_options(
        user_id=user_id,
        environment="local",
    )
    option = next(
        item for item in options["applications"] if str(item["id"]) == str(application["id"])
    )
    return {
        "application_id": str(application["id"]),
        "publication_id": str(publication["id"]),
        "execution_scope_id": str(option["execution_scopes"][0]["id"]),
        "environment_id": environment_id,
        "base_id": base_id,
        "delivery_binding_id": str(
            option["delivery_bindings"][0]["binding_id"] if option["delivery_bindings"] else ""
        ),
    }
