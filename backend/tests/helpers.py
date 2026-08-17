from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from app.bootstrap import Container, build_test_container
from app.modules.identity.application import AuthorizationEvaluator
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.business_application.domain.policies import (
    required_file_mcp_tools,
    snapshot_hash,
    validate_task_file_features,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
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


def ensure_active_dingtalk_test_enterprise(
    runtime: Container,
    *,
    connector_id: str = "connector-dingtalk-stream-default",
    corp_id: str = "corp-test-enterprise",
    name: str = "测试钉钉企业",
) -> dict[str, object]:
    timestamp = "2026-08-03T00:00:00+00:00"
    existing = runtime.database.execute_one(
        "select * from dingtalk_enterprise where corp_id = ?",
        (corp_id,),
    )
    if existing is None:
        created = runtime.managed_channel_service.create_dingtalk_enterprise(
            name=name,
            actor_id="user_local_admin",
        )
        runtime.database.execute(
            """
            update dingtalk_enterprise
               set corp_id = ?, status = 'ACTIVE', verified_at = ?,
                   verification_event_id = 'test-fixture-verification'
             where id = ?
            """,
            (corp_id, timestamp, created["id"]),
        )
        existing = runtime.database.execute_one(
            "select * from dingtalk_enterprise where id = ?",
            (created["id"],),
        )
    assert existing is not None
    runtime.database.execute(
        """
        update integration_connector
           set dingtalk_enterprise_id = ?
         where id = ? and connector_type = 'dingtalk_enterprise_stream'
        """,
        (existing["id"], connector_id),
    )
    runtime.database.execute(
        """
        update user_external_identity
           set dingtalk_enterprise_id = ?, tenant_code = ?, connector_id = ''
         where provider = 'dingtalk'
           and dingtalk_enterprise_id is null
           and (connector_id = ? or tenant_code in ('default', 'tenant-discovery'))
        """,
        (existing["id"], existing["id"], connector_id),
    )
    return existing


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


def _ensure_agent_publication_mcp_tools(
    container: Container,
    tool_identifiers: tuple[str, ...],
    *,
    agent_publication_id: str = "agent_publication_default_v1",
) -> tuple[str, ...]:
    requested = tuple(sorted(set(tool_identifiers).intersection(ToolRegistry.READONLY_TOOLS)))
    if not requested:
        return ()
    published = {
        str(row["tool_identifier"])
        for row in container.database.execute(
            """
            select tool_identifier
              from agent_publication_mcp_tool
             where agent_publication_id = ?
            """,
            (agent_publication_id,),
        )
    }
    missing = sorted(set(requested) - published)
    file_tools = [
        identifier
        for identifier in missing
        if MCP_TOOL_MANIFEST[identifier].server_code == "file-service"
    ]
    if file_tools:
        row = container.database.execute_one(
            """
            select coalesce(max(selection_order), -1) as maximum_order
              from agent_publication_mcp_tool
             where agent_publication_id = ?
            """,
            (agent_publication_id,),
        )
        next_order = int((row or {}).get("maximum_order") or -1) + 1
        for offset, identifier in enumerate(file_tools):
            definition = MCP_TOOL_MANIFEST[identifier]
            container.database.execute(
                """
                insert into agent_publication_mcp_tool
                  (agent_publication_id, server_code, tool_identifier, schema_hash,
                   model_description, selection_order, created_at)
                values (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    agent_publication_id,
                    definition.server_code,
                    definition.identifier,
                    definition.schema_hash,
                    definition.description,
                    next_order + offset,
                ),
            )
        published.update(file_tools)
        missing = sorted(set(requested) - published)
    if missing:
        raise AssertionError(
            "Test Agent publication does not contain requested MCP Tools: " + ", ".join(missing)
        )
    return requested


def activate_dingtalk_test_application(
    container: Container,
    *,
    code: str,
    robot_code: str,
    group_conversation_ids: tuple[str, ...] = (),
    attachments_enabled: bool = False,
    capabilities: tuple[str, ...] = (),
    additional_deliveries: tuple[dict[str, object], ...] = (),
    agent_publication_id: str = "agent_publication_default_v1",
    task_file_features: dict[str, bool] | None = None,
    file_format_policy_version: str = "text-v1",
) -> dict[str, object]:
    ensure_active_dingtalk_test_enterprise(container)
    normalized_task_file_features = validate_task_file_features(task_file_features)
    effective_capabilities = tuple(
        sorted(set(capabilities) | set(required_file_mcp_tools(normalized_task_file_features)))
    )
    mcp_tools = _ensure_agent_publication_mcp_tools(
        container,
        effective_capabilities,
        agent_publication_id=agent_publication_id,
    )
    if file_format_policy_version == "text-v2":
        publication_row = container.database.execute_one(
            "select snapshot_json from agent_publication where id = ?",
            (agent_publication_id,),
        )
        if publication_row is None:
            raise AssertionError("Test Agent publication is missing")
        snapshot = json.loads(str(publication_row["snapshot_json"]))
        runtime_kind_row = container.database.execute_one(
            "select runtime_kind from agent_publication where id = ?",
            (agent_publication_id,),
        )
        assert runtime_kind_row is not None
        snapshot["runtime_kind"] = str(runtime_kind_row["runtime_kind"])
        snapshot["supported_runtime_protocol_versions"] = ["1.2", "1.3"]
        container.database.execute(
            """
            update agent_publication
               set schema_version = 3, snapshot_json = ?, config_hash = ?
             where id = ?
            """,
            (
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                snapshot_hash(snapshot),
                agent_publication_id,
            ),
        )
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
            "agent_publication_id": agent_publication_id,
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
            "task_file_features": normalized_task_file_features,
            "file_format_policy_version": file_format_policy_version,
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
            "mcp_tools": list(mcp_tools),
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


def activate_webhook_test_application(
    container: Container,
    *,
    code: str,
    webhook_definition_id: str,
    service_account_user_id: str,
    ingress_connector_id: str,
    delivery_connector_id: str,
    delivery_target_reference: str,
    capabilities: tuple[str, ...] = (),
    environment_code: str = "prod",
    base_code: str = "guanlan",
    workshop_code: str = "GL001",
) -> dict[str, object]:
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code=code,
        name=f"{code} test application",
        description="Strict Webhook Business Application test route",
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
                "continuous_conversation_enabled": False,
                "attachments_enabled": False,
            },
            "execution_policy": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "triggers": [
                {
                    "trigger_type": "webhook",
                    "connector_id": ingress_connector_id,
                    "routing_key": (f"webhook:{webhook_definition_id}"),
                    "actor_policy": "SERVICE_ACCOUNT",
                    "service_account_user_id": (service_account_user_id),
                    "enabled": True,
                    "config": {
                        "conversation_type": "event",
                        "require_mention": False,
                        "webhook_definition_id": (webhook_definition_id),
                    },
                }
            ],
            "deliveries": [
                {
                    "delivery_type": "dingtalk_group",
                    "connector_id": delivery_connector_id,
                    "enabled": True,
                    "config": {
                        "target_reference": (delivery_target_reference),
                        "reply_mode": "fixed",
                    },
                }
            ],
            "mcp_tools": list(
                _ensure_agent_publication_mcp_tools(
                    container,
                    capabilities,
                )
            ),
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
    timestamp = datetime.now(UTC).isoformat()
    environment_id = f"environment-{code}"
    base_id = f"base-{code}"
    workshop_id = f"workshop-{code}"
    container.database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values (?, ?, ?, 'enabled', ?, ?)
        """,
        (
            environment_id,
            environment_code,
            environment_code,
            timestamp,
            timestamp,
        ),
    )
    container.database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values (?, ?, ?, ?, 'postgresql', 'enabled', ?, ?)
        """,
        (
            base_id,
            environment_id,
            base_code,
            base_code,
            timestamp,
            timestamp,
        ),
    )
    container.database.execute(
        """
        insert into platform_workshop
          (id, base_id, code, display_name, status,
           created_at, updated_at)
        values (?, ?, ?, ?, 'enabled', ?, ?)
        """,
        (
            workshop_id,
            base_id,
            workshop_code,
            workshop_code,
            timestamp,
            timestamp,
        ),
    )
    grant_test_application_access(
        container,
        application_id=str(application["id"]),
        role_code=f"{code}-runtime",
        user_id=service_account_user_id,
        capabilities=capabilities,
        scopes=(
            {
                "environment_id": environment_id,
                "base_id": base_id,
                "workshop_id": workshop_id,
            },
        ),
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
    publication = activate_dingtalk_test_application(
        container,
        code=application_code,
        robot_code=f"robot-{application_code}",
        capabilities=capabilities,
        additional_deliveries=additional_deliveries,
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
