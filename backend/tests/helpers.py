from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from app.bootstrap import Container, build_test_container
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.platform_config.infrastructure.repository import now_iso
from app.shared.config import DingTalkSettings, Settings


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


def _ensure_exact_builtin_tool_releases(
    container: Container,
    tool_identifiers: tuple[str, ...],
    *,
    agent_publication_id: str = "agent_publication_default_v1",
) -> dict[str, dict[str, object]]:
    requested = tuple(
        sorted(set(tool_identifiers).intersection(ToolRegistry.READONLY_TOOLS))
    )
    if not requested:
        return {}
    container.database.execute(
        """
        insert into permission_policy
          (id, subject_type, subject_code, resource_type, resource_code,
           effect, action, status, priority, revision, created_at, updated_at)
        values ('test-user-local-admin-builtin-tools', 'user',
                'user_local_admin', 'builtin_tool', '*', 'allow', '*',
                'enabled', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """
    )
    handlers = container.platform_config_service.handlers
    handlers.reconcile(actor_id="user_local_admin")
    releases: dict[str, dict[str, object]] = {}
    for tool_identifier in requested:
        existing = container.database.execute_one(
            """
            select release.*
              from agent_publication_builtin_tool envelope
              join builtin_tool_release release
                on release.id = envelope.tool_release_id
             where envelope.agent_publication_id = ?
               and envelope.tool_identifier = ?
            """,
            (agent_publication_id, tool_identifier),
        )
        if existing is not None:
            releases[tool_identifier] = dict(existing)
            continue
        if agent_publication_id != "agent_publication_default_v1":
            raise AssertionError(
                "Exact test Agent publication does not contain requested Built-in Tool "
                f"{tool_identifier}"
            )
        evidence = handlers.verify_payload(
            {
                "tool_identifier": tool_identifier,
                "handler_version": "1.0.0",
            },
            actor_id="user_local_admin",
        )
        release = handlers.publish_builtin_tool_payload(
            {
                "tool_identifier": tool_identifier,
                "handler_version": "1.0.0",
                "verification_id": evidence["id"],
                "idempotency_key": f"test-fixture-{tool_identifier}-v1",
            },
            actor_id="user_local_admin",
        )
        envelope = {
            "agent_publication_id": agent_publication_id,
            "tool_identifier": release["tool_identifier"],
            "tool_release_id": release["id"],
            "handler_version": release["handler_version"],
            "implementation_digest": release["implementation_digest"],
            "public_schema_hash": release["public_schema_hash"],
        }
        container.database.execute(
            """
            insert into agent_publication_builtin_tool
              (id, agent_publication_id, tool_identifier, tool_release_id,
               handler_version, implementation_digest, public_schema_hash,
               envelope_hash, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"agent_envelope_test_{tool_identifier}",
                envelope["agent_publication_id"],
                envelope["tool_identifier"],
                envelope["tool_release_id"],
                envelope["handler_version"],
                envelope["implementation_digest"],
                envelope["public_schema_hash"],
                snapshot_hash(envelope),
                now_iso(),
            ),
        )
        releases[tool_identifier] = dict(release)
    return releases


def _published_test_resource(
    container: Container,
    *,
    code: str,
    resource_kind: str,
    scope_type: str,
    environment_id: str,
    base_id: str | None = None,
) -> str:
    timestamp = now_iso()
    resource_id = f"resource_{code}"
    revision_id = f"resource_revision_{code}_v1"
    verification_id = f"resource_verification_{code}_v1"
    provider_type = {
        "database": "mysql",
        "redis": "redis",
        "loki": "loki",
    }[resource_kind]
    provider_contract_version = {
        "database": "mysql_v1",
        "redis": "redis_v1",
        "loki": "loki_v1",
    }[resource_kind]
    config = (
        {
            "base_url": "http://loki.test:3100",
            "tenant_id": "",
            "timeout_seconds": 5,
            "max_minutes": 60,
            "max_lines": 200,
            "max_response_bytes": 65_536,
        }
        if resource_kind == "loki"
        else {}
    )
    content_hash = snapshot_hash(
        {"resource": code, "revision": 1, "config": config}
    )
    container.database.execute(
        """
        insert into platform_resource
          (id, code, name, resource_kind, scope_type, environment_id,
           base_id, workshop_id, status, revision, created_by,
           created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, null, 'enabled', 1,
                'user_local_admin', ?, ?)
        """,
        (
            resource_id,
            code,
            code,
            resource_kind,
            scope_type,
            environment_id,
            base_id,
            timestamp,
            timestamp,
        ),
    )
    container.database.execute(
        """
        insert into platform_resource_verification
          (id, resource_id, draft_id, draft_revision, content_hash, status,
           provider_contract_version, checks_json, verified_by, verified_at)
        values (?, ?, null, 1, ?, 'PASSED', ?, '{}',
                'user_local_admin', ?)
        """,
        (
            verification_id,
            resource_id,
            content_hash,
            provider_contract_version,
            timestamp,
        ),
    )
    container.database.execute(
        """
        insert into platform_resource_revision
          (id, resource_id, revision, provider_type,
           provider_contract_version, config_json, secret_refs_json,
           content_hash, verification_id, status, published_by,
           published_at)
        values (?, ?, 1, ?, ?, ?, '{}', ?, ?, 'PUBLISHED',
                'user_local_admin', ?)
        """,
        (
            revision_id,
            resource_id,
            provider_type,
            provider_contract_version,
            json.dumps(config, ensure_ascii=False, sort_keys=True),
            content_hash,
            verification_id,
            timestamp,
        ),
    )
    return revision_id


def _published_test_loki_policy(
    container: Container,
    *,
    code: str,
    environment_id: str,
    base_id: str,
    resource_revision_id: str,
) -> str:
    timestamp = now_iso()
    policy_id = f"loki_policy_{code}"
    verification_id = f"loki_policy_verification_{code}_v1"
    revision_id = f"loki_policy_revision_{code}_v1"
    conditions = [{"key": "customer", "value": "local"}]
    content_hash = snapshot_hash(
        {
            "resource_revision_id": resource_revision_id,
            "conditions": conditions,
        }
    )
    container.database.execute(
        """
        insert into loki_scope_policy
          (id, code, environment_id, base_id, status, revision, created_by,
           created_at, updated_at)
        values (?, ?, ?, ?, 'enabled', 1, 'user_local_admin', ?, ?)
        """,
        (policy_id, code, environment_id, base_id, timestamp, timestamp),
    )
    container.database.execute(
        """
        insert into loki_scope_policy_verification
          (id, policy_id, draft_revision, resource_revision_id, content_hash,
           verifier_version, status, match_count, truncated,
           zero_match_warning, result_summary_json, verified_by, verified_at)
        values (?, ?, 1, ?, ?, 'test-fixture.v1', 'PASSED', 1, 0, 0, '{}',
                'user_local_admin', ?)
        """,
        (
            verification_id,
            policy_id,
            resource_revision_id,
            content_hash,
            timestamp,
        ),
    )
    container.database.execute(
        """
        insert into loki_scope_policy_revision
          (id, policy_id, revision, resource_revision_id, content_hash,
           verification_id, status, health_status, published_by,
           published_at)
        values (?, ?, 1, ?, ?, ?, 'PUBLISHED', 'HEALTHY',
                'user_local_admin', ?)
        """,
        (
            revision_id,
            policy_id,
            resource_revision_id,
            content_hash,
            verification_id,
            timestamp,
        ),
    )
    container.database.execute(
        """
        insert into loki_scope_policy_revision_condition
          (policy_revision_id, label_key, label_value, position)
        values (?, 'customer', 'local', 0)
        """,
        (revision_id,),
    )
    return revision_id


def activate_dingtalk_test_application(
    container: Container,
    *,
    code: str,
    robot_code: str,
    group_conversation_ids: tuple[str, ...] = (),
    attachments_enabled: bool = False,
    capabilities: tuple[str, ...] = (),
    additional_deliveries: tuple[dict[str, object], ...] = (),
    target_paths: tuple[dict[str, object], ...] = (),
    builtin_tool_resources: dict[
        str, tuple[dict[str, object], ...]
    ] | None = None,
    agent_publication_id: str = "agent_publication_default_v1",
) -> dict[str, object]:
    ensure_active_dingtalk_test_enterprise(container)
    releases = _ensure_exact_builtin_tool_releases(
        container,
        capabilities,
        agent_publication_id=agent_publication_id,
    )
    governed_capabilities = tuple(
        capability
        for capability in capabilities
        if capability not in ToolRegistry.READONLY_TOOLS
    )
    resources_by_tool = builtin_tool_resources or {}
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
                for capability in governed_capabilities
            ],
            "target_paths": list(target_paths),
            "builtin_tools": [
                {
                    "tool_release_id": releases[tool_identifier]["id"],
                    "resources": list(resources_by_tool.get(tool_identifier, ())),
                }
                for tool_identifier in sorted(releases)
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
                    "routing_key": (
                        f"webhook:{webhook_definition_id}"
                    ),
                    "actor_policy": "SERVICE_ACCOUNT",
                    "service_account_user_id": (
                        service_account_user_id
                    ),
                    "enabled": True,
                    "config": {
                        "conversation_type": "event",
                        "require_mention": False,
                        "webhook_definition_id": (
                            webhook_definition_id
                        ),
                    },
                }
            ],
            "deliveries": [
                {
                    "delivery_type": "dingtalk_group",
                    "connector_id": delivery_connector_id,
                    "enabled": True,
                    "config": {
                        "target_reference": (
                            delivery_target_reference
                        ),
                        "reply_mode": "fixed",
                    },
                }
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
    builtin_tool_resources: dict[
        str, tuple[dict[str, object], ...]
    ] = {}
    database_tools = {
        "get_schema_directory",
        "query_database",
    }.intersection(capabilities)
    if database_tools:
        database_revision_id = _published_test_resource(
            container,
            code=f"{application_code}-database",
            resource_kind="database",
            scope_type="base",
            environment_id=environment_id,
            base_id=base_id,
        )
        mapping = {
            "resource_slot": "database",
            "target_scope_type": "base",
            "environment_code": "local",
            "base_code": "debug-base",
            "workshop_code": "",
            "placement": "",
            "resource_revision_id": database_revision_id,
            "workshop_partition_policy_revision_id": "",
            "loki_scope_policy_revision_id": "",
        }
        for tool_identifier in database_tools:
            builtin_tool_resources[tool_identifier] = (dict(mapping),)
    redis_tools = {
        "query_redis_get",
        "query_redis_scan",
    }.intersection(capabilities)
    if redis_tools:
        redis_revision_id = _published_test_resource(
            container,
            code=f"{application_code}-redis",
            resource_kind="redis",
            scope_type="base",
            environment_id=environment_id,
            base_id=base_id,
        )
        mapping = {
            "resource_slot": "redis",
            "target_scope_type": "base",
            "environment_code": "local",
            "base_code": "debug-base",
            "workshop_code": "",
            "placement": "",
            "resource_revision_id": redis_revision_id,
            "workshop_partition_policy_revision_id": "",
            "loki_scope_policy_revision_id": "",
        }
        for tool_identifier in redis_tools:
            builtin_tool_resources[tool_identifier] = (dict(mapping),)
    loki_tools = {
        "diagnose_loki_labels",
        "diagnose_loki_label_values",
        "diagnose_loki_probe",
        "query_loki",
    }.intersection(capabilities)
    if loki_tools:
        loki_revision_id = _published_test_resource(
            container,
            code=f"{application_code}-loki",
            resource_kind="loki",
            scope_type="environment",
            environment_id=environment_id,
        )
        loki_policy_revision_id = _published_test_loki_policy(
            container,
            code=f"{application_code}-loki",
            environment_id=environment_id,
            base_id=base_id,
            resource_revision_id=loki_revision_id,
        )
        mapping = {
            "resource_slot": "loki",
            "target_scope_type": "base",
            "environment_code": "local",
            "base_code": "debug-base",
            "workshop_code": "",
            "placement": "",
            "resource_revision_id": loki_revision_id,
            "workshop_partition_policy_revision_id": "",
            "loki_scope_policy_revision_id": loki_policy_revision_id,
        }
        for tool_identifier in loki_tools:
            builtin_tool_resources[tool_identifier] = (dict(mapping),)
    publication = activate_dingtalk_test_application(
        container,
        code=application_code,
        robot_code=f"robot-{application_code}",
        capabilities=capabilities,
        additional_deliveries=additional_deliveries,
        target_paths=(
            {
                "target_scope_type": "base",
                "environment_code": "local",
                "base_code": "debug-base",
                "workshop_code": "",
            },
        ),
        builtin_tool_resources=builtin_tool_resources,
    )
    application = container.business_application_repository.get_by_code(
        application_code
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
