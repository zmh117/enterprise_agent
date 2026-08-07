from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib

from app.bootstrap import Container, build_test_container
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.shared.config import IdentitySettings, Settings


ACTOR_ID = "user_local_admin"
AGENT_CODE = "default-diagnostic-agent"


@dataclass(frozen=True)
class Scenario:
    code: str
    leaf: str
    placements: tuple[str | None, ...]


SCENARIOS = (
    Scenario("environment-no-placement", "environment", (None,)),
    Scenario("base-cloud-only", "base", ("cloud",)),
    Scenario("workshop-edge-only", "workshop", ("edge",)),
    Scenario("workshop-cloud-edge", "workshop", ("cloud", "edge")),
)


class _PassingMysqlVerifier:
    def verify(
        self,
        *,
        resource: dict[str, object],
        draft: dict[str, object],
    ) -> ResourceVerificationOutcome:
        del resource, draft
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={"connection": True, "readonly_account": True},
        )


def _settings() -> Settings:
    return replace(
        Settings(
            database_dsn="sqlite:///:memory:",
            app_config_master_key="compose-acceptance-only-master-key",
        ),
        environment="compose-acceptance",
        feature_business_application_control_plane=True,
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=False,
            cookie_secure=False,
        ),
    )


def _publish_exact_agent(runtime: Container) -> tuple[str, dict[str, object]]:
    runtime.database.execute(
        """
        insert into permission_policy
          (id, subject_type, subject_code, resource_type, resource_code,
           effect, action, status, priority, revision, created_at, updated_at)
        values ('compose-acceptance-builtin-tool-admin', 'user', ?,
                'builtin_tool', '*', 'allow', '*', 'enabled', 100, 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """,
        (ACTOR_ID,),
    )
    handlers = runtime.platform_config_service.handlers
    handlers.reconcile(actor_id=ACTOR_ID)
    evidence = handlers.verify_payload(
        {"tool_identifier": "query_database", "handler_version": "1.0.0"},
        actor_id=ACTOR_ID,
    )
    release = handlers.publish_builtin_tool_payload(
        {
            "tool_identifier": "query_database",
            "handler_version": "1.0.0",
            "verification_id": evidence["id"],
            "idempotency_key": "compose-acceptance-query-database-v1",
        },
        actor_id=ACTOR_ID,
    )

    connection = runtime.model_connection_service.get("default-deepseek-anthropic")
    runtime.model_connection_service.dns_resolver = lambda *_args, **_kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    connection_revision = runtime.model_connection_service.save_revision(
        actor_id=ACTOR_ID,
        code="default-deepseek-anthropic",
        expected_revision=int(connection["revision"]),
        config={
            "protocol": "anthropic_compatible",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": "compose-acceptance-model",
            "default_opus_model": "compose-acceptance-model",
            "default_sonnet_model": "compose-acceptance-model",
            "default_haiku_model": "compose-acceptance-model",
            "subagent_model": "compose-acceptance-model",
            "effort_level": "max",
        },
        api_key=hashlib.sha256(b"compose-acceptance-key-material").hexdigest(),
    )
    current = runtime.agent_config_service.get()
    revision = runtime.agent_config_service.save_draft(
        actor_id=ACTOR_ID,
        agent_code=AGENT_CODE,
        expected_revision=int(current["draft"]["revision"]),
        config={
            "business_role": "Compose acceptance Agent",
            "business_instructions": "Use only exact published evidence.",
            "model_policy": {
                "runtime": "claude_agent_sdk",
                "model": "compose-acceptance-model",
                "model_connection_revision_id": connection_revision["id"],
            },
            "execution": {"max_turns": 2, "timeout_seconds": 30},
            "tools": [],
            "builtin_tool_release_ids": [release["id"]],
            "skills": [],
            "routing": {"project_code": "default"},
            "channels": {
                "ingress": ["connector-debug-api"],
                "delivery": ["connector-none"],
            },
        },
    )
    publication = runtime.agent_config_service.publish(
        actor_id=ACTOR_ID,
        agent_code=AGENT_CODE,
        revision_id=str(revision["id"]),
    )
    return str(publication["id"]), release


def _target(runtime: Container, scenario: Scenario) -> tuple[dict[str, str], str | None]:
    environment_code = f"accept-{scenario.code}"
    runtime.platform_config_service.upsert_environment(
        {"code": environment_code},
        actor_id=ACTOR_ID,
    )
    if scenario.leaf == "environment":
        return (
            {
                "target_scope_type": "environment",
                "environment_code": environment_code,
                "base_code": "",
                "workshop_code": "",
            },
            None,
        )

    base_code = "base-leaf"
    runtime.platform_config_service.upsert_base(
        {
            "environment_code": environment_code,
            "code": base_code,
            "engine": "mysql",
        },
        actor_id=ACTOR_ID,
    )
    if scenario.leaf == "base":
        return (
            {
                "target_scope_type": "base",
                "environment_code": environment_code,
                "base_code": base_code,
                "workshop_code": "",
            },
            None,
        )

    workshop_code = "GL001"
    runtime.platform_config_service.upsert_workshop(
        {
            "environment_code": environment_code,
            "base_code": base_code,
            "code": workshop_code,
        },
        actor_id=ACTOR_ID,
    )
    policies = runtime.platform_config_service.workshop_partition_policies
    policy = policies.create(
        {
            "code": f"policy-{scenario.code}",
            "environment_code": environment_code,
            "base_code": base_code,
            "workshop_code": workshop_code,
            "database_rule_enabled": True,
            "database_table_prefix": "GL001_",
            "redis_rule_enabled": False,
            "redis_prefixes": [],
        },
        actor_id=ACTOR_ID,
    )
    evidence = policies.verify(
        f"policy-{scenario.code}",
        expected_draft_revision=int(policy["draft"]["draft_revision"]),
        actor_id=ACTOR_ID,
    )
    policy_revision = policies.publish(
        f"policy-{scenario.code}",
        verification_id=str(evidence["id"]),
        expected_policy_revision=1,
        actor_id=ACTOR_ID,
    )
    return (
        {
            "target_scope_type": "workshop",
            "environment_code": environment_code,
            "base_code": base_code,
            "workshop_code": workshop_code,
        },
        str(policy_revision["id"]),
    )


def _resource_revision(
    runtime: Container,
    *,
    scenario: Scenario,
    target: dict[str, str],
    placement: str | None,
) -> str:
    suffix = placement or "none"
    code = f"resource-{scenario.code}-{suffix}"
    secret_code = f"password_{scenario.code.replace('-', '_')}_{suffix}"
    runtime.platform_config_service.create_platform_secret(
        {"code": secret_code, "value": "compose-acceptance-password"},
        actor_id=ACTOR_ID,
    )
    scope_type = "environment" if scenario.leaf == "environment" else "base"
    resources = runtime.platform_config_service.governed_resources
    resources.create_resource(
        {
            "code": code,
            "name": code,
            "resource_kind": "database",
            "scope_type": scope_type,
            "environment_code": target["environment_code"],
            "base_code": target["base_code"] if scope_type == "base" else "",
            "provider_type": "mysql",
            "config": {
                "host": "database.acceptance.invalid",
                "port": 3306,
                "database": "acceptance",
                "username": "readonly",
            },
            "secret_refs": {
                "password_ref": f"secret://platform/{secret_code}",
            },
        },
        actor_id=ACTOR_ID,
    )
    resources.verify_draft(
        code,
        actor_id=ACTOR_ID,
        verifier=_PassingMysqlVerifier(),
    )
    return str(resources.publish_draft(code, actor_id=ACTOR_ID)["id"])


def _application_payload(
    *,
    agent_publication_id: str,
    release: dict[str, object],
    target: dict[str, str],
    policy_revision_id: str | None,
    resources: list[tuple[str | None, str]],
) -> dict[str, object]:
    return {
        "agent_publication_id": agent_publication_id,
        "workflow_publication_id": "",
        "session_policy": {
            "conversation_mode": "channel",
            "recent_message_limit": 4,
            "retention_days": 1,
            "continuous_conversation_enabled": False,
            "attachments_enabled": False,
        },
        "execution_policy": {
            "max_turns": 2,
            "timeout_seconds": 30,
            "max_tool_calls": 4,
        },
        "triggers": [],
        "deliveries": [],
        "capabilities": [],
        "target_paths": [target],
        "builtin_tools": [
            {
                "tool_release_id": release["id"],
                "resources": [
                    {
                        "resource_slot": "database",
                        **target,
                        "placement": placement,
                        "resource_revision_id": resource_revision_id,
                        "workshop_partition_policy_revision_id": (
                            policy_revision_id or ""
                        ),
                        "loki_scope_policy_revision_id": "",
                    }
                    for placement, resource_revision_id in resources
                ],
            }
        ],
    }


def _run_scenario(
    runtime: Container,
    *,
    scenario: Scenario,
    agent_publication_id: str,
    release: dict[str, object],
) -> None:
    target, policy_revision_id = _target(runtime, scenario)
    resource_revisions = [
        (
            placement,
            _resource_revision(
                runtime,
                scenario=scenario,
                target=target,
                placement=placement,
            ),
        )
        for placement in scenario.placements
    ]
    application = runtime.business_application_service.create(
        actor_id=ACTOR_ID,
        code=f"app-{scenario.code}",
        name=f"Compose {scenario.code}",
        description="Isolated Built-in Tool composition acceptance",
        project_code="default",
        owner_user_id=ACTOR_ID,
    )
    revision = runtime.business_application_service.save_draft(
        actor_id=ACTOR_ID,
        code=f"app-{scenario.code}",
        expected_revision=int(application["revision"]),
        payload=_application_payload(
            agent_publication_id=agent_publication_id,
            release=release,
            target=target,
            policy_revision_id=policy_revision_id,
            resources=resource_revisions,
        ),
    )
    publication = runtime.business_application_service.publish(
        actor_id=ACTOR_ID,
        code=f"app-{scenario.code}",
        revision_id=str(revision["id"]),
    )
    resolution_set = publication["snapshot"]["builtin_tool_resolution_set"]
    resolutions = resolution_set["resolutions"]
    expected_placements = sorted(placement or "" for placement in scenario.placements)
    actual_placements = sorted(str(item.get("placement") or "") for item in resolutions)
    if int(resolution_set["resolution_count"]) != len(scenario.placements):
        raise RuntimeError(f"{scenario.code}: resolution count mismatch")
    if actual_placements != expected_placements:
        raise RuntimeError(f"{scenario.code}: placement mismatch")
    if {str(item["target_scope_type"]) for item in resolutions} != {scenario.leaf}:
        raise RuntimeError(f"{scenario.code}: target leaf mismatch")
    print(
        f"compose-acceptance {scenario.code}: ok "
        f"leaf={scenario.leaf} placements={','.join(value or 'none' for value in scenario.placements)} "
        f"resolutions={len(resolutions)}"
    )


def main() -> int:
    runtime = build_test_container(_settings(), migrate=True, seed=True)
    try:
        agent_publication_id, release = _publish_exact_agent(runtime)
        for scenario in SCENARIOS:
            _run_scenario(
                runtime,
                scenario=scenario,
                agent_publication_id=agent_publication_id,
                release=release,
            )
    finally:
        runtime.database.close()
    print("compose-acceptance builtin-tool-composition: passed scenarios=4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
