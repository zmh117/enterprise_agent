from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from app.bootstrap import Container, build_test_container
from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.config import DingTalkSettings, Settings


def ensure_active_dingtalk_test_enterprise(
    runtime: Container,
    *,
    connector_id: str = "connector-dingtalk-stream-default",
    corp_id: str = "corp-test-enterprise",
    name: str = "测试钉钉企业",
) -> dict[str, object]:
    """Install an immutable trusted-enterprise fixture without a retired admin API."""

    timestamp = "2026-08-03T00:00:00+00:00"
    existing = runtime.database.execute_one(
        "select * from dingtalk_enterprise where corp_id = ?",
        (corp_id,),
    )
    if existing is None:
        enterprise_id = f"dingtalk-enterprise-{hashlib.sha256(corp_id.encode()).hexdigest()[:20]}"
        runtime.database.execute(
            """
            insert into dingtalk_enterprise
              (id, name, corp_id, status, verification_event_id, verified_at,
               revision, created_by, created_at, updated_at)
            values (?, ?, ?, 'ACTIVE', 'test-fixture-verification', ?, 1,
                    'user_local_admin', ?, ?)
            """,
            (enterprise_id, name, corp_id, timestamp, timestamp, timestamp),
        )
        existing = runtime.database.execute_one(
            "select * from dingtalk_enterprise where id = ?",
            (enterprise_id,),
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
    runtime = build_test_container(
        test_settings(),
        migrate=True,
        seed=True,
        configure_seed_secrets=configure_seed_secrets,
    )
    ensure_active_dingtalk_test_enterprise(runtime)
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


def activate_dingtalk_test_application(
    runtime: Container,
    *,
    code: str,
    robot_code: str,
    group_conversation_ids: tuple[str, ...] = (),
    attachments_enabled: bool = False,
    capabilities: tuple[str, ...] = (),
    additional_deliveries: tuple[dict[str, object], ...] = (),
    target_paths: tuple[dict[str, object], ...] = (),
    builtin_tool_resources: dict[str, tuple[dict[str, object], ...]] | None = None,
    agent_publication_id: str = "agent_publication_default_v1",
) -> dict[str, object]:
    del capabilities, target_paths, builtin_tool_resources
    ensure_active_dingtalk_test_enterprise(runtime)
    triggers: list[dict[str, object]] = [
        {
            "trigger_type": "dingtalk_private",
            "connector_id": "connector-dingtalk-stream-default",
            "routing_key": f"bot:{robot_code}",
            "actor_policy": "CURRENT_SENDER",
            "service_account_user_id": "",
            "enabled": True,
            "config": {"conversation_type": "private", "require_mention": False},
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
            "config": {"conversation_type": "group", "require_mention": True},
        }
        for conversation_id in group_conversation_ids
    )
    return _install_immutable_application(
        runtime,
        code=code,
        triggers=tuple(triggers),
        deliveries=(
            {
                "delivery_type": "reply_original",
                "connector_id": "connector-dingtalk-stream-default",
                "enabled": True,
                "config": {"target_reference": "", "reply_mode": "original"},
            },
            *additional_deliveries,
        ),
        attachments_enabled=attachments_enabled,
        continuous_conversation_enabled=True,
        agent_publication_id=agent_publication_id,
    )


def activate_webhook_test_application(
    runtime: Container,
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
    del capabilities
    publication = _install_immutable_application(
        runtime,
        code=code,
        triggers=(
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
            },
        ),
        deliveries=(
            {
                "delivery_type": "dingtalk_group",
                "connector_id": delivery_connector_id,
                "enabled": True,
                "config": {
                    "target_reference": delivery_target_reference,
                    "reply_mode": "fixed",
                },
            },
        ),
        attachments_enabled=False,
        continuous_conversation_enabled=False,
    )
    _grant_application_scope(
        runtime,
        application_id=str(publication["application_id"]),
        code=code,
        user_id=service_account_user_id,
        environment_code=environment_code,
        base_code=base_code,
        workshop_code=workshop_code,
    )
    return publication


def _install_immutable_application(
    runtime: Container,
    *,
    code: str,
    triggers: tuple[dict[str, object], ...],
    deliveries: tuple[dict[str, object], ...],
    attachments_enabled: bool,
    continuous_conversation_enabled: bool,
    agent_publication_id: str = "agent_publication_default_v1",
) -> dict[str, object]:
    """Write test-only immutable routing facts, mirroring code-owned bootstrap data."""

    timestamp = datetime.now(UTC).isoformat()
    key = hashlib.sha256(code.encode()).hexdigest()[:20]
    application_id = f"test-application-{key}"
    revision_id = f"test-application-revision-{key}"
    publication_id = f"test-application-publication-{key}"
    deployment_id = f"test-application-deployment-{key}"
    agent_publication = runtime.agent_config_service.repository.get_publication(
        agent_publication_id
    )
    agent_definition = runtime.database.execute_one(
        "select code from agent_definition where id = ?",
        (agent_publication["agent_id"],),
    )
    assert agent_definition is not None
    normalized_triggers = [
        {
            **dict(trigger),
            "routing_key": str(trigger["routing_key"]),
            "normalized_routing_key": str(trigger["routing_key"]).strip().lower(),
        }
        for trigger in triggers
    ]
    snapshot: dict[str, Any] = {
        "application": {
            "id": application_id,
            "code": code,
            "project_code": "default",
        },
        "agent": {
            "id": agent_publication_id,
            "code": str(agent_definition["code"]),
            "revision": int(agent_publication["revision"]),
            "config_hash": str(agent_publication["config_hash"]),
        },
        "session_policy": {
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
            "continuous_conversation_enabled": continuous_conversation_enabled,
            "attachments_enabled": attachments_enabled,
        },
        "execution_policy": {
            "max_turns": 12,
            "timeout_seconds": 300,
            "max_tool_calls": 30,
        },
        "triggers": normalized_triggers,
        "deliveries": [dict(delivery) for delivery in deliveries],
        "capabilities": [],
    }
    config_hash = snapshot_hash(snapshot)
    runtime.database.execute(
        """
        insert into business_application
          (id, code, name, description, project_code, owner_user_id, status,
           revision, created_by, created_at, updated_at)
        values (?, ?, ?, 'Immutable runtime fixture', 'default',
                'user_local_admin', 'enabled', 1, 'test-bootstrap', ?, ?)
        """,
        (application_id, code, f"{code} test application", timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, agent_publication_id,
           workflow_publication_id, session_policy_json, execution_policy_json,
           validation_json, config_hash, created_by, created_at, updated_at)
        values (?, ?, 1, 'published', ?, null, ?, ?,
                '{"valid":true,"errors":[]}', ?, 'test-bootstrap', ?, ?)
        """,
        (
            revision_id,
            application_id,
            agent_publication_id,
            json.dumps(snapshot["session_policy"], sort_keys=True),
            json.dumps(snapshot["execution_policy"], sort_keys=True),
            config_hash,
            timestamp,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, schema_version,
           snapshot_json, config_hash, published_by, published_at)
        values (?, ?, ?, 1, 1, ?, ?, 'test-bootstrap', ?)
        """,
        (
            publication_id,
            application_id,
            revision_id,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            config_hash,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into business_application_deployment
          (id, application_id, environment, publication_id, active, revision,
           activated_by, activated_at, updated_at)
        values (?, ?, 'local', ?, 1, 1, 'test-bootstrap', ?, ?)
        """,
        (deployment_id, application_id, publication_id, timestamp, timestamp),
    )
    for index, trigger in enumerate(normalized_triggers):
        runtime.database.execute(
            """
            insert into business_application_active_route
              (id, deployment_id, application_id, publication_id, environment,
               trigger_type, connector_id, normalized_routing_key, created_at)
            values (?, ?, ?, ?, 'local', ?, ?, ?, ?)
            """,
            (
                f"test-application-route-{key}-{index}",
                deployment_id,
                application_id,
                publication_id,
                trigger["trigger_type"],
                trigger["connector_id"],
                trigger["normalized_routing_key"],
                timestamp,
            ),
        )
    return {
        "id": publication_id,
        "application_id": application_id,
        "revision_id": revision_id,
        "revision": 1,
        "schema_version": 1,
        "snapshot": snapshot,
        "config_hash": config_hash,
    }


def _grant_application_scope(
    runtime: Container,
    *,
    application_id: str,
    code: str,
    user_id: str,
    environment_code: str,
    base_code: str,
    workshop_code: str,
) -> None:
    timestamp = datetime.now(UTC).isoformat()
    role_id = f"test-role-{code}"
    membership_id = f"test-membership-{code}"
    access_id = f"test-application-access-{code}"
    environment_id = f"test-environment-{code}"
    base_id = f"test-base-{code}"
    workshop_id = f"test-workshop-{code}"
    runtime.database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values (?, ?, ?, 'enabled', ?, ?)
        """,
        (environment_id, environment_code, environment_code, timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values (?, ?, ?, ?, 'postgresql', 'enabled', ?, ?)
        """,
        (base_id, environment_id, base_code, base_code, timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into platform_workshop
          (id, base_id, code, display_name, status, created_at, updated_at)
        values (?, ?, ?, ?, 'enabled', ?, ?)
        """,
        (workshop_id, base_id, workshop_code, workshop_code, timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into rbac_role
          (id, code, name, description, status, revision, origin, protected,
           purpose_tags_json, metadata_revision, admin_revision,
           business_revision, membership_revision, created_at, updated_at)
        values (?, ?, ?, 'Immutable runtime fixture role', 'enabled', 1,
                'custom', 0, '["runtime"]', 1, 1, 1, 1, ?, ?)
        """,
        (role_id, f"{code}-runtime", f"{code} runtime", timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into rbac_user_role
          (id, user_id, role_id, status, revision, assigned_by,
           assignment_source, created_at, updated_at)
        values (?, ?, ?, 'enabled', 1, 'test-bootstrap', 'bootstrap', ?, ?)
        """,
        (membership_id, user_id, role_id, timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into rbac_role_application_access
          (id, role_id, application_id, status, revision, created_at, updated_at)
        values (?, ?, ?, 'enabled', 1, ?, ?)
        """,
        (access_id, role_id, application_id, timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into rbac_role_application_scope
          (id, application_access_id, environment_id, base_id, workshop_id,
           scope_key, created_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"test-application-scope-{code}",
            access_id,
            environment_id,
            base_id,
            workshop_id,
            f"{environment_code}/{base_code}/{workshop_code}",
            timestamp,
        ),
    )


def dingtalk_sign(secret: str, timestamp: str) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


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
