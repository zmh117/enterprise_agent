from __future__ import annotations

import hashlib
import json

import pytest

from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


ADMIN = "user_local_admin"
DEFAULT_AGENT_PUBLICATION = "agent_publication_default_v1"


def _publish_ones_tool(runtime, code: str = "ones-search") -> str:
    tool = runtime.mcp_tool_publication_service.create(
        code=code,
        name="ONES work item search",
        catalog_key="ones-mcp/ones_work_item_search",
        actor_id=ADMIN,
        idempotency_key=f"{code}-create",
    )
    runtime.mcp_tool_publication_service.verify(
        code,
        expected_revision=int(tool["revision"]),
        actor_id=ADMIN,
    )
    published = runtime.mcp_tool_publication_service.publish(
        code,
        expected_revision=int(tool["revision"]),
        actor_id=ADMIN,
        idempotency_key=f"{code}-publish",
    )
    return str(published["publication_id"])


def _application_payload(
    tool_ids: list[str] | None = None,
    *,
    agent_publication_id: str = DEFAULT_AGENT_PUBLICATION,
    routing_key: str = "bot:application-one",
) -> dict[str, object]:
    return {
        "agent_publication_id": agent_publication_id,
        "mcp_tool_publication_ids": tool_ids or [],
        "session_policy": {
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
            "continuous_conversation_enabled": True,
            "attachments_enabled": False,
        },
        "execution_policy": {
            "max_turns": 12,
            "timeout_seconds": 300,
            "max_tool_calls": 30,
        },
        "triggers": [
            {
                "trigger_type": "dingtalk_private",
                "connector_id": "connector-dingtalk-stream-default",
                "routing_key": routing_key,
                "actor_policy": "CURRENT_SENDER",
                "service_account_user_id": "",
                "enabled": True,
                "config": {"conversation_type": "private", "require_mention": False},
            }
        ],
        "deliveries": [
            {
                "delivery_type": "reply_original",
                "connector_id": "connector-dingtalk-stream-default",
                "enabled": True,
                "config": {"target_reference": "", "reply_mode": "original"},
            }
        ],
    }


def _active_redis_deployment(runtime, code: str, key_prefix: str) -> str:
    runtime.mcp_resource_service.apply(
        {
            "api_version": "enterprise-agent/v1",
            "kind": "REDIS",
            "metadata": {"code": code, "name": code.replace("_", " ").title()},
            "spec": {
                "host": f"{code}.internal",
                "port": 6379,
                "database": 0,
                "key_prefixes": [key_prefix],
                "scan_limit": 50,
                "timeout_seconds": 5,
                "tls": True,
            },
        },
        actor_id=ADMIN,
        expected_revision=0,
        idempotency_key=f"{code}-create",
    )
    runtime.mcp_resource_service.verify(code, actor_id=ADMIN, expected_revision=1)
    published = runtime.mcp_resource_service.publish(
        code,
        actor_id=ADMIN,
        expected_revision=1,
        idempotency_key=f"{code}-publish",
    )
    runtime.mcp_resource_service.activate_generation(str(published["generation_id"]), success=True)
    return str(published["deployment_id"])


def _publish_redis_tool(runtime, code: str, catalog_key: str, deployment_id: str) -> str:
    created = runtime.mcp_tool_publication_service.create(
        code=code,
        name=code.replace("-", " ").title(),
        catalog_key=catalog_key,
        resource_deployment_id=deployment_id,
        actor_id=ADMIN,
        idempotency_key=f"{code}-create",
    )
    runtime.mcp_tool_publication_service.verify(
        code,
        expected_revision=int(created["revision"]),
        actor_id=ADMIN,
    )
    published = runtime.mcp_tool_publication_service.publish(
        code,
        expected_revision=int(created["revision"]),
        actor_id=ADMIN,
        idempotency_key=f"{code}-publish",
    )
    return str(published["publication_id"])


def _ready_model_revision(runtime, model: str, label: str) -> str:
    runtime.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    connection = runtime.model_connection_service.get("default-deepseek-anthropic")
    revision = runtime.model_connection_service.save_revision(
        actor_id=ADMIN,
        code="default-deepseek-anthropic",
        expected_revision=int(connection["revision"]),
        config={
            "protocol": "anthropic_compatible",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": model,
            "default_opus_model": model,
            "default_sonnet_model": model,
            "default_haiku_model": model,
            "subagent_model": model,
            "effort_level": "max",
        },
        api_key=hashlib.sha256(f"model-fixture:{label}".encode()).hexdigest(),
        idempotency_key=f"model-{label}-save",
    )
    return str(revision["id"])


def _publish_agent(
    runtime,
    *,
    code: str,
    model: str,
    model_revision_id: str,
    tool_publication_id: str,
) -> str:
    runtime.agent_config_service.allowed_models.add(model)
    created = runtime.agent_config_service.create(
        actor_id=ADMIN,
        code=code,
        name=code.replace("-", " ").title(),
        description=f"Isolated {code}",
        project_code="default",
        idempotency_key=f"{code}-create",
    )
    revision = runtime.agent_config_service.save_draft(
        actor_id=ADMIN,
        agent_code=code,
        expected_revision=int(created["definition"]["revision"]),
        config={
            "business_role": f"Role for {code}",
            "business_instructions": f"Only serve {code}",
            "model_policy": {
                "runtime": "claude_agent_sdk",
                "model": model,
                "model_connection_revision_id": model_revision_id,
            },
            "execution": {"max_turns": 8, "timeout_seconds": 120},
            "skills": [],
            "routing": {"project_code": "default"},
            "channels": {"ingress": [], "delivery": []},
            "mcp_tool_publication_ids": [tool_publication_id],
        },
        idempotency_key=f"{code}-draft",
    )
    publication = runtime.agent_config_service.publish(
        actor_id=ADMIN,
        agent_code=code,
        revision_id=str(revision["id"]),
        expected_revision=int(created["definition"]["revision"]) + 1,
        idempotency_key=f"{code}-publish",
    )
    return str(publication["id"])


def _publish_application(
    runtime,
    *,
    code: str,
    agent_publication_id: str,
    tool_publication_id: str,
    environment: str,
) -> dict[str, object]:
    created = runtime.business_application_service.create(
        actor_id=ADMIN,
        code=code,
        name=code.replace("-", " ").title(),
        description=f"Isolated {code}",
        project_code="default",
        owner_user_id=ADMIN,
        idempotency_key=f"{code}-create",
    )
    revision = runtime.business_application_service.save_draft(
        actor_id=ADMIN,
        code=code,
        expected_revision=int(created["revision"]),
        payload=_application_payload(
            [tool_publication_id],
            agent_publication_id=agent_publication_id,
            routing_key=f"bot:{code}",
        ),
        idempotency_key=f"{code}-draft",
    )
    publication = runtime.business_application_service.publish(
        actor_id=ADMIN,
        code=code,
        revision_id=str(revision["id"]),
        expected_revision=int(created["revision"]) + 1,
        idempotency_key=f"{code}-publish",
    )
    deployment = runtime.business_application_service.activate(
        actor_id=ADMIN,
        code=code,
        environment=environment,
        publication_id=str(publication["id"]),
        expected_revision=0,
        idempotency_key=f"{code}-{environment}-activate",
    )
    return {"publication": publication, "deployment": deployment}


def test_multiple_agent_definition_lifecycle_is_editable_and_guarded() -> None:
    runtime = container()
    try:
        created = runtime.agent_config_service.create(
            actor_id=ADMIN,
            code="operations-agent",
            name="Operations Agent",
            description="Read-only operations diagnosis",
            project_code="default",
        )
        assert created["definition"]["code"] == "operations-agent"
        assert created["management_mode"] == "editable"
        assert {item["code"] for item in runtime.agent_config_service.list_agents()} >= {
            "default-diagnostic-agent",
            "operations-agent",
        }

        disabled = runtime.agent_config_service.update_definition(
            actor_id=ADMIN,
            agent_code="operations-agent",
            expected_revision=1,
            name="Operations Agent",
            description="Read-only operations diagnosis",
            project_code="default",
            status="disabled",
        )
        archived = runtime.agent_config_service.update_definition(
            actor_id=ADMIN,
            agent_code="operations-agent",
            expected_revision=int(disabled["definition"]["revision"]),
            name="Operations Agent",
            description="Read-only operations diagnosis",
            project_code="default",
            status="archived",
        )
        assert archived["definition"]["status"] == "archived"
        with pytest.raises(NonRetryableExecutionError) as restore:
            runtime.agent_config_service.update_definition(
                actor_id=ADMIN,
                agent_code="operations-agent",
                expected_revision=int(archived["definition"]["revision"]),
                name="Operations Agent",
                description="Read-only operations diagnosis",
                project_code="default",
                status="enabled",
            )
        assert restore.value.error_code == "invalid_lifecycle"
    finally:
        runtime.database.close()


def test_application_freezes_agent_tool_subset_and_routes_deterministically() -> None:
    runtime = container()
    try:
        tool_publication_id = _publish_ones_tool(runtime)
        runtime.mcp_tool_publication_service.bind_agent_publication(
            DEFAULT_AGENT_PUBLICATION,
            [tool_publication_id],
        )
        created = runtime.business_application_service.create(
            actor_id=ADMIN,
            code="application-one",
            name="Application One",
            description="First governed application",
            project_code="default",
            owner_user_id=ADMIN,
            idempotency_key="application-one-create",
        )
        revision = runtime.business_application_service.save_draft(
            actor_id=ADMIN,
            code="application-one",
            expected_revision=int(created["revision"]),
            payload=_application_payload([tool_publication_id]),
        )
        validated = runtime.business_application_service.validate(
            actor_id=ADMIN,
            code="application-one",
            revision_id=str(revision["id"]),
            expected_revision=int(created["revision"]) + 1,
            idempotency_key="application-one-validate",
        )
        assert validated["validation"] == {"valid": True, "errors": []}
        publication = runtime.business_application_service.publish(
            actor_id=ADMIN,
            code="application-one",
            revision_id=str(revision["id"]),
            expected_revision=int(created["revision"]) + 1,
            idempotency_key="application-one-publish",
        )
        assert [item["id"] for item in publication["snapshot"]["mcp_tools"]] == [
            tool_publication_id
        ]
        assert publication["snapshot"]["runtime_contract"]["protocol_version"] == "1.0"
        serialized = str(publication).lower()
        for forbidden in ("password", "authorization", "secret://", "api_key"):
            assert forbidden not in serialized

        deployment = runtime.business_application_service.activate(
            actor_id=ADMIN,
            code="application-one",
            environment="test",
            publication_id=str(publication["id"]),
            expected_revision=0,
            idempotency_key="application-one-activate",
        )
        assert deployment["active"] is True
        resolved = runtime.business_application_resolver.resolve_trigger(
            "test",
            "dingtalk_private",
            "connector-dingtalk-stream-default",
            "bot:application-one",
        )
        assert resolved["application"]["code"] == "application-one"
        assert resolved["publication"]["id"] == publication["id"]

        with pytest.raises(NonRetryableExecutionError) as in_use:
            runtime.mcp_tool_publication_service.disable(
                "ones-search",
                expected_revision=2,
                actor_id=ADMIN,
            )
        assert in_use.value.error_code == "dependency_in_use"
        assert in_use.value.diagnostics["active_applications"] == [
            {
                "deployment_id": deployment["id"],
                "environment": "test",
                "application_code": "application-one",
                "publication_id": publication["id"],
                "publication_revision": publication["revision"],
            }
        ]
    finally:
        runtime.database.close()


def test_application_rejects_tool_outside_agent_and_disabled_dependency() -> None:
    runtime = container()
    try:
        tool_publication_id = _publish_ones_tool(runtime, "unbound-ones-search")
        created = runtime.business_application_service.create(
            actor_id=ADMIN,
            code="application-two",
            name="Application Two",
            description="Second governed application",
            project_code="default",
            owner_user_id=ADMIN,
            idempotency_key="application-two-create",
        )
        revision = runtime.business_application_service.save_draft(
            actor_id=ADMIN,
            code="application-two",
            expected_revision=int(created["revision"]),
            payload=_application_payload([tool_publication_id]),
        )
        validated = runtime.business_application_service.validate(
            actor_id=ADMIN,
            code="application-two",
            revision_id=str(revision["id"]),
            expected_revision=int(created["revision"]) + 1,
            idempotency_key="application-two-validate",
        )
        assert validated["validation"]["valid"] is False
        assert validated["validation"]["errors"][0]["field"] == "mcp_tool_publication_ids"

        runtime.mcp_tool_publication_service.bind_agent_publication(
            DEFAULT_AGENT_PUBLICATION,
            [tool_publication_id],
        )
        runtime.mcp_tool_publication_service.disable(
            "unbound-ones-search",
            expected_revision=2,
            actor_id=ADMIN,
        )
        with pytest.raises(NonRetryableExecutionError) as rejected:
            runtime.business_application_service.publish(
                actor_id=ADMIN,
                code="application-two",
                revision_id=str(revision["id"]),
                expected_revision=int(created["revision"]) + 1,
                idempotency_key=hashlib.sha256(b"application-two-publish").hexdigest(),
            )
        assert rejected.value.error_code == "validation_failed"
    finally:
        runtime.database.close()


def test_two_agents_and_applications_keep_model_tool_resource_and_route_boundaries() -> None:
    runtime = container()
    try:
        cache_a = _active_redis_deployment(runtime, "orders_cache", "orders:")
        cache_b = _active_redis_deployment(runtime, "support_cache", "support:")
        tool_a = _publish_redis_tool(runtime, "orders-cache-get", "data-mcp/redis_get", cache_a)
        tool_b = _publish_redis_tool(
            runtime,
            "support-cache-scan",
            "data-mcp/redis_scan_prefix",
            cache_b,
        )
        model_a = _ready_model_revision(runtime, "claude-orders-fixture", "orders")
        model_b = _ready_model_revision(runtime, "claude-support-fixture", "support")
        agent_a = _publish_agent(
            runtime,
            code="orders-agent",
            model="claude-orders-fixture",
            model_revision_id=model_a,
            tool_publication_id=tool_a,
        )
        agent_b = _publish_agent(
            runtime,
            code="support-agent",
            model="claude-support-fixture",
            model_revision_id=model_b,
            tool_publication_id=tool_b,
        )
        app_a = _publish_application(
            runtime,
            code="orders-application",
            agent_publication_id=agent_a,
            tool_publication_id=tool_a,
            environment="test",
        )
        app_b = _publish_application(
            runtime,
            code="support-application",
            agent_publication_id=agent_b,
            tool_publication_id=tool_b,
            environment="test",
        )

        snapshot_a = app_a["publication"]["snapshot"]
        snapshot_b = app_b["publication"]["snapshot"]
        assert snapshot_a["agent"]["id"] == agent_a
        assert snapshot_b["agent"]["id"] == agent_b
        assert [item["id"] for item in snapshot_a["mcp_tools"]] == [tool_a]
        assert [item["id"] for item in snapshot_b["mcp_tools"]] == [tool_b]
        assert [item["deployment_id"] for item in snapshot_a["resources"]] == [cache_a]
        assert [item["deployment_id"] for item in snapshot_b["resources"]] == [cache_b]

        frozen_agents = runtime.database.execute(
            "select id, snapshot_json from agent_publication where id in (?, ?) order by id",
            (agent_a, agent_b),
        )
        frozen_models = {
            row["id"]: json.loads(row["snapshot_json"])["model_policy"] for row in frozen_agents
        }
        assert frozen_models == {
            agent_a: {
                "runtime": "claude_agent_sdk",
                "model": "claude-orders-fixture",
                "model_connection_revision_id": model_a,
            },
            agent_b: {
                "runtime": "claude_agent_sdk",
                "model": "claude-support-fixture",
                "model_connection_revision_id": model_b,
            },
        }

        resolved_a = runtime.business_application_resolver.resolve_trigger(
            "test",
            "dingtalk_private",
            "connector-dingtalk-stream-default",
            "bot:orders-application",
        )
        resolved_b = runtime.business_application_resolver.resolve_trigger(
            "test",
            "dingtalk_private",
            "connector-dingtalk-stream-default",
            "bot:support-application",
        )
        assert resolved_a["application"]["code"] == "orders-application"
        assert resolved_a["publication"]["id"] == app_a["publication"]["id"]
        assert resolved_b["application"]["code"] == "support-application"
        assert resolved_b["publication"]["id"] == app_b["publication"]["id"]

        with pytest.raises(NonRetryableExecutionError) as crossed_tool:
            runtime.mcp_tool_publication_service.prepare_application_selection(
                agent_a,
                [tool_b],
            )
        assert crossed_tool.value.error_code == "application_mcp_tool_scope_exceeded"
    finally:
        runtime.database.close()
