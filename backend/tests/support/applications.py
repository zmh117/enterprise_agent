from __future__ import annotations

import json
from datetime import UTC, datetime

from app.bootstrap import Container
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.business_application.domain.policies import (
    required_file_mcp_tools,
    snapshot_hash,
    validate_task_file_features,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from backend.tests.support.channels import ensure_active_dingtalk_test_enterprise


def ensure_agent_publication_mcp_tools(
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
    document_processing_profile_code: str = "NONE",
) -> dict[str, object]:
    ensure_active_dingtalk_test_enterprise(container)
    normalized_task_file_features = validate_task_file_features(task_file_features)
    effective_capabilities = tuple(
        sorted(set(capabilities) | set(required_file_mcp_tools(normalized_task_file_features)))
    )
    mcp_tools = ensure_agent_publication_mcp_tools(
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
            "document_processing_profile_code": document_processing_profile_code,
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
                    "routing_key": f"webhook:{webhook_definition_id}",
                    "actor_policy": "SERVICE_ACCOUNT",
                    "service_account_user_id": service_account_user_id,
                    "enabled": True,
                    "config": {
                        "conversation_type": "event",
                        "require_mention": False,
                        "webhook_definition_id": webhook_definition_id,
                    },
                }
            ],
            "deliveries": [
                {
                    "delivery_type": "dingtalk_group",
                    "connector_id": delivery_connector_id,
                    "enabled": True,
                    "config": {
                        "target_reference": delivery_target_reference,
                        "reply_mode": "fixed",
                    },
                }
            ],
            "mcp_tools": list(ensure_agent_publication_mcp_tools(container, capabilities)),
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
        (environment_id, environment_code, environment_code, timestamp, timestamp),
    )
    container.database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values (?, ?, ?, ?, 'postgresql', 'enabled', ?, ?)
        """,
        (base_id, environment_id, base_code, base_code, timestamp, timestamp),
    )
    container.database.execute(
        """
        insert into platform_workshop
          (id, base_id, code, display_name, status, created_at, updated_at)
        values (?, ?, ?, ?, 'enabled', ?, ?)
        """,
        (workshop_id, base_id, workshop_code, workshop_code, timestamp, timestamp),
    )
    from backend.tests.support.authorization import grant_test_application_access

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
