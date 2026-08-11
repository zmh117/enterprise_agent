from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.agent_config.api.controller import AgentDraftRequest
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


PYTHON_AGENT = "default-diagnostic-agent"
TYPESCRIPT_AGENT = "typescript-diagnostic-agent"


class RejectTypeScriptRuntime:
    def __init__(self) -> None:
        self.checked: list[str] = []

    def require_ready(self, runtime_kind: str) -> None:
        assert_external_io_allowed("test.runtime_readiness")
        self.checked.append(runtime_kind)
        if runtime_kind == "typescript-v1":
            raise NonRetryableExecutionError(
                "TypeScript Runtime unavailable",
                safe_message="所选 Agent Runtime 当前未就绪",
                error_code="agent_runtime_unavailable",
            )


def test_seed_creates_two_runtime_fixed_agents_and_is_idempotent() -> None:
    runtime = container()

    definitions = {
        value["code"]: value for value in runtime.agent_config_service.list_agents()
    }
    assert definitions[PYTHON_AGENT]["runtime_kind"] == "python-v1"
    assert definitions[TYPESCRIPT_AGENT]["runtime_kind"] == "typescript-v1"

    python_publication = runtime.agent_config_service.current_publication(PYTHON_AGENT)
    typescript_publication = runtime.agent_config_service.current_publication(TYPESCRIPT_AGENT)
    assert python_publication["schema_version"] == 1
    assert python_publication["runtime_kind"] == "python-v1"
    assert "runtime_kind" not in python_publication["snapshot"]
    assert typescript_publication["schema_version"] == 2
    assert typescript_publication["runtime_kind"] == "typescript-v1"
    assert typescript_publication["snapshot"]["runtime_kind"] == "typescript-v1"

    seed_path = Path(__file__).parents[1] / "seeds" / "local_seed.sql"
    runtime.database.execute_script(seed_path.read_text(encoding="utf-8"))
    assert len(runtime.agent_config_service.list_agents()) == len(definitions)
    assert (
        runtime.agent_config_service.current_publication(TYPESCRIPT_AGENT)["id"]
        == typescript_publication["id"]
    )


def test_job_freezes_runtime_from_exact_agent_publication() -> None:
    runtime = container(allow_direct_jobs=True)
    publication = runtime.agent_config_service.current_publication(TYPESCRIPT_AGENT)

    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="typescript-publication-runtime",
            requester_id="local-user",
            external_conversation_id="typescript-runtime-test",
            external_event_id="typescript-runtime-event",
            user_message="diagnose with TypeScript",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            reply_route={"type": "none", "connector_id": ""},
            agent_code=TYPESCRIPT_AGENT,
            fixed_agent_publication_id=str(publication["id"]),
            fixed_agent_revision=int(publication["revision"]),
            fixed_agent_config_hash=str(publication["config_hash"]),
        )
    )

    assert job.agent_definition_id == "agent_typescript_diagnostic"
    assert job.agent_publication_id == publication["id"]
    assert job.agent_runtime_kind == "typescript-v1"
    assert job.agent_runtime_protocol_version == "1.0"


def test_publication_runtime_must_match_definition() -> None:
    runtime = container()
    publication = runtime.agent_config_service.current_publication(TYPESCRIPT_AGENT)
    runtime.database.execute(
        "update agent_definition set runtime_kind = 'python-v1' where code = ?",
        (TYPESCRIPT_AGENT,),
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.agent_config_service.publication(str(publication["id"]))

    assert rejected.value.error_code == "agent_publication_runtime_mismatch"


def test_runtime_kind_is_not_a_draft_override() -> None:
    with pytest.raises(ValidationError):
        AgentDraftRequest.model_validate(
            {
                "expected_revision": 1,
                "config": {
                    "business_role": "diagnostic",
                    "business_instructions": "Use approved evidence.",
                    "runtime_kind": "typescript-v1",
                    "model_policy": {
                        "runtime": "claude_agent_sdk",
                        "model": "claude-sonnet-4-20250514",
                    },
                    "execution": {"max_turns": 12, "timeout_seconds": 300},
                    "skills": [],
                    "routing": {"project_code": "default"},
                    "channels": {"ingress": [], "delivery": []},
                },
            }
        )


def test_typescript_agent_supports_draft_publish_history_and_rollback() -> None:
    runtime = container()
    original = runtime.agent_config_service.current_publication(TYPESCRIPT_AGENT)
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="typescript-publication-pinning-test",
        name="TypeScript Publication Pinning Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    application_revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="typescript-publication-pinning-test",
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": original["id"],
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
            "triggers": [],
            "deliveries": [],
            "capabilities": [],
        },
    )
    application_publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="typescript-publication-pinning-test",
        revision_id=str(application_revision["id"]),
    )
    runtime.business_application_service.activate(
        actor_id="user_local_admin",
        code="typescript-publication-pinning-test",
        environment="local",
        publication_id=str(application_publication["id"]),
        expected_revision=0,
    )
    detail = runtime.agent_config_service.get(TYPESCRIPT_AGENT)
    assert detail["management_mode"] == "editable"
    config = dict(detail["draft"]["config"])
    config["business_instructions"] = "Use the TypeScript runtime and approved evidence."
    connection = runtime.model_connection_service.get("default-deepseek-anthropic")
    runtime.model_connection_service.dns_resolver = lambda *_args, **_kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    connection_revision = runtime.model_connection_service.save_revision(
        actor_id="user_local_admin",
        code="default-deepseek-anthropic",
        expected_revision=int(connection["revision"]),
        config={
            "protocol": "anthropic_compatible",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": "claude-sonnet-4-20250514",
            "default_opus_model": "claude-sonnet-4-20250514",
            "default_sonnet_model": "claude-sonnet-4-20250514",
            "default_haiku_model": "claude-sonnet-4-20250514",
            "subagent_model": "claude-sonnet-4-20250514",
            "effort_level": "max",
        },
        api_key=hashlib.sha256(b"typescript-agent-test-key").hexdigest(),
    )
    config["model_policy"] = {
        "runtime": "claude_agent_sdk",
        "model": "claude-sonnet-4-20250514",
        "model_connection_revision_id": connection_revision["id"],
    }

    draft = runtime.agent_config_service.save_draft(
        actor_id="user_local_admin",
        agent_code=TYPESCRIPT_AGENT,
        expected_revision=int(detail["draft"]["revision"]),
        config=config,
    )
    publication = runtime.agent_config_service.publish(
        actor_id="user_local_admin",
        agent_code=TYPESCRIPT_AGENT,
        revision_id=str(draft["id"]),
    )

    assert publication["runtime_kind"] == "typescript-v1"
    assert publication["snapshot"]["runtime_kind"] == "typescript-v1"
    assert publication["id"] != original["id"]
    active = runtime.business_application_resolver.resolve_active(
        "typescript-publication-pinning-test",
        "local",
    )
    assert active["publication"]["snapshot"]["agent"]["id"] == original["id"]
    assert {item["id"] for item in runtime.agent_config_service.publications(TYPESCRIPT_AGENT)} >= {
        original["id"],
        publication["id"],
    }

    rolled_back = runtime.agent_config_service.rollback(
        actor_id="user_local_admin",
        agent_code=TYPESCRIPT_AGENT,
        publication_id=str(original["id"]),
    )
    assert rolled_back["id"] == original["id"]
    assert rolled_back["runtime_kind"] == "typescript-v1"


def test_selected_runtime_readiness_blocks_only_new_job_and_activation() -> None:
    runtime = container(allow_direct_jobs=True)
    typescript = runtime.agent_config_service.current_publication(TYPESCRIPT_AGENT)
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="runtime-readiness-activation-test",
        name="Runtime Readiness Activation Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    application_revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="runtime-readiness-activation-test",
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": typescript["id"],
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 30,
            },
            "execution_policy": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "triggers": [],
            "deliveries": [],
            "capabilities": [],
        },
    )
    application_publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="runtime-readiness-activation-test",
        revision_id=str(application_revision["id"]),
    )
    guard = RejectTypeScriptRuntime()
    runtime.create_agent_job_service.runtime_readiness_guard = guard  # type: ignore[assignment]
    runtime.business_application_service.runtime_readiness_guard = guard  # type: ignore[assignment]

    with pytest.raises(NonRetryableExecutionError) as job_rejected:
        runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="runtime-readiness-typescript-job",
                requester_id="local-user",
                external_conversation_id="runtime-readiness-conversation",
                external_event_id="runtime-readiness-event",
                user_message="run TypeScript",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                reply_route={"type": "none", "connector_id": ""},
                agent_code=TYPESCRIPT_AGENT,
                fixed_agent_publication_id=str(typescript["id"]),
                fixed_agent_revision=int(typescript["revision"]),
                fixed_agent_config_hash=str(typescript["config_hash"]),
            )
        )
    assert job_rejected.value.error_code == "agent_runtime_unavailable"
    assert runtime.agent_repository.get_job_by_idempotency_key(
        "runtime-readiness-typescript-job"
    ) is None

    with pytest.raises(NonRetryableExecutionError) as activation_rejected:
        runtime.business_application_service.activate(
            actor_id="user_local_admin",
            code="runtime-readiness-activation-test",
            environment="local",
            publication_id=str(application_publication["id"]),
            expected_revision=0,
        )
    assert activation_rejected.value.error_code == "agent_runtime_unavailable"
    assert guard.checked == ["typescript-v1", "typescript-v1"]
