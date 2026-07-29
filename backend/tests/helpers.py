from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime

from app.bootstrap import Container, build_test_container
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.config import DingTalkSettings, Settings


def test_settings(secret: str = "test-secret") -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="test-only-master-key",
        dingtalk=DingTalkSettings(secret=secret),
    )


def container(*, configure_seed_secrets: bool = True) -> Container:
    return build_test_container(
        test_settings(),
        migrate=True,
        seed=True,
        configure_seed_secrets=configure_seed_secrets,
    )


def publish_pending_agent_jobs(runtime: Container) -> None:
    result = runtime.job_dispatcher.publish_pending(limit=100)
    assert result.failed == 0
    assert result.dead == 0


def enqueue_job_result_for_delivery(
    runtime: Container,
    job_id: str,
    *,
    correlation_id: str = "test-delivery",
) -> str:
    job = runtime.agent_repository.get_job(job_id)
    if not job.result:
        raise AssertionError("Job result must be persisted before Delivery enqueue")
    artifact = runtime.agent_repository.get_artifact_for_job(
        job_id=job_id,
        artifact_type="report",
        name="diagnostic-report.md",
    )
    artifact_id = (
        str(artifact["id"])
        if artifact is not None
        else runtime.agent_repository.add_artifact(
            job_id=job_id,
            artifact_type="report",
            name="diagnostic-report.md",
            content=job.result,
        )
    )
    return runtime.result_delivery_service.enqueue_job_result(
        job_id=job_id,
        artifact_id=artifact_id,
        correlation_id=correlation_id,
    )


def dispatch_pending_deliveries(runtime: Container) -> None:
    result = runtime.delivery_dispatcher.dispatch_pending(limit=100)
    assert result.retrying == 0
    assert result.failed == 0
    assert result.dead == 0


def persisted_agent_job_message(
    runtime: Container,
    job_id: str,
) -> AgentJobMessage:
    event = runtime.agent_repository.get_dispatch_event_for_job(job_id)
    assert event is not None
    return AgentJobMessage(
        event_id=event.id,
        job_id=event.job_id,
        correlation_id=event.correlation_id,
    )


def activate_dingtalk_test_application(
    container: Container,
    *,
    code: str,
    robot_code: str,
    group_conversation_ids: tuple[str, ...] = (),
    attachments_enabled: bool = False,
    capabilities: tuple[str, ...] = (),
    additional_deliveries: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    triggers: list[dict[str, object]] = [
        {
            "trigger_type": "dingtalk_private",
            "connector_id": "connector-dingtalk-stream-default",
            "routing_key": f"bot:{robot_code}",
            "actor_policy": "CURRENT_SENDER",
            "service_account_user_id": "",
            "enabled": True,
            "config": {
                "conversation_type": "private",
                "require_mention": False,
                "webhook_definition_id": "",
            },
        }
    ]
    triggers.extend(
        {
            "trigger_type": "dingtalk_group",
            "connector_id": "connector-dingtalk-stream-default",
            "routing_key": f"conversation:{conversation_id}",
            "actor_policy": "CURRENT_SENDER",
            "service_account_user_id": "",
            "enabled": True,
            "config": {
                "conversation_type": "group",
                "require_mention": True,
                "webhook_definition_id": "",
            },
        }
        for conversation_id in group_conversation_ids
    )
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code=code,
        name=f"{code} test application",
        description="Explicit local route for ingress tests",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": "agent_publication_default_v1",
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 30,
                "continuous_conversation_enabled": True,
                "attachments_enabled": attachments_enabled,
            },
            "execution_policy": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "triggers": triggers,
            "deliveries": [
                {
                    "delivery_type": "reply_original",
                    "connector_id": "connector-dingtalk-stream-default",
                    "enabled": True,
                    "config": {"target_reference": "", "reply_mode": "original"},
                },
                *additional_deliveries,
            ],
            "capabilities": [
                {
                    "capability_code": capability,
                    "version_constraint": "*",
                    "enabled": True,
                }
                for capability in capabilities
            ],
        },
    )
    publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    container.business_application_service.activate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    return publication


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
                "capability_codes": list(capabilities),
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
) -> dict[str, str]:
    publication = activate_dingtalk_test_application(
        container,
        code=application_code,
        robot_code=f"robot-{application_code}",
        capabilities=capabilities,
        additional_deliveries=additional_deliveries,
    )
    application = container.business_application_repository.get_by_code(
        application_code
    )
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
                "capability_codes": list(capabilities),
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
        item
        for item in options["applications"]
        if str(item["id"]) == str(application["id"])
    )
    return {
        "application_id": str(application["id"]),
        "publication_id": str(publication["id"]),
        "execution_scope_id": str(option["execution_scopes"][0]["id"]),
        "environment_id": environment_id,
        "base_id": base_id,
        "delivery_binding_id": str(
            option["delivery_bindings"][0]["binding_id"]
            if option["delivery_bindings"]
            else ""
        ),
    }


def dingtalk_sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def dingtalk_payload(
    *,
    msg_id: str = "msg-1",
    user_id: str = "local-user",
    content: str = "Why is order MO20260627001 waiting material?",
) -> dict[str, object]:
    return {
        "conversationId": "conversation-1",
        "senderStaffId": user_id,
        "msgId": msg_id,
        "text": {"content": content},
        "project_code": "default",
    }
