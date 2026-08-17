"""Historical TypeScript facts remain readable but cannot execute."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.agent_config.api.controller import AgentDraftRequest
from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container, ensure_historical_typescript_agent


PYTHON_AGENT = "default-diagnostic-agent"
TYPESCRIPT_AGENT = "typescript-diagnostic-agent"
RETIRED_ERROR = "typescript_agent_runtime_retired"


def _container(**kwargs: object) -> Any:
    runtime = container(**kwargs)
    ensure_historical_typescript_agent(runtime)
    return runtime


def _typescript_publication(runtime: object) -> dict[str, object]:
    return runtime.agent_config_service.current_publication(TYPESCRIPT_AGENT)


def _application_payload(agent_publication_id: str) -> dict[str, object]:
    return {
        "agent_publication_id": agent_publication_id,
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
    }


def test_historical_typescript_agent_is_read_only_and_preserves_runtime_facts() -> None:
    runtime = _container()
    definition = runtime.agent_config_service.get(TYPESCRIPT_AGENT)
    publication = _typescript_publication(runtime)

    assert definition["definition"]["runtime_kind"] == "typescript-v1"
    assert definition["management_mode"] == "read_only_retired"
    assert definition["retirement_status"] == "retired"
    assert publication["runtime_kind"] == "typescript-v1"
    assert publication["snapshot"]["runtime_kind"] == "typescript-v1"
    assert (
        runtime.agent_config_service.publication(str(publication["id"]))["config_hash"]
        == (publication["config_hash"])
    )
    assert runtime.agent_config_service.publications(TYPESCRIPT_AGENT)[0]["id"] == publication["id"]

    listed = {value["code"]: value for value in runtime.agent_config_service.list_agents()}
    assert listed[PYTHON_AGENT]["management_mode"] == "editable"
    assert listed[TYPESCRIPT_AGENT]["management_mode"] == "read_only_retired"


def test_historical_typescript_publication_cannot_create_job() -> None:
    runtime = _container(allow_direct_jobs=True)
    publication = _typescript_publication(runtime)

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="retired-typescript-publication",
                requester_id="local-user",
                external_conversation_id="retired-typescript-runtime",
                external_event_id="retired-typescript-event",
                user_message="synthetic retirement check",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                reply_route={"type": "none", "connector_id": ""},
                agent_code=TYPESCRIPT_AGENT,
                fixed_agent_publication_id=str(publication["id"]),
                fixed_agent_revision=int(publication["revision"]),
                fixed_agent_config_hash=str(publication["config_hash"]),
            )
        )

    assert rejected.value.error_code == RETIRED_ERROR
    assert (
        runtime.agent_repository.get_job_by_idempotency_key("retired-typescript-publication")
        is None
    )


def test_publication_runtime_must_match_definition() -> None:
    runtime = _container()
    publication = _typescript_publication(runtime)
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


def test_historical_typescript_agent_rejects_all_configuration_writes() -> None:
    runtime = _container()
    detail = runtime.agent_config_service.get(TYPESCRIPT_AGENT)
    publication = _typescript_publication(runtime)
    revision_id = str(detail["draft"]["id"])

    operations = (
        lambda: runtime.agent_config_service.save_draft(
            actor_id="user_local_admin",
            agent_code=TYPESCRIPT_AGENT,
            expected_revision=int(detail["draft"]["revision"]),
            config=dict(detail["draft"]["config"]),
        ),
        lambda: runtime.agent_config_service.validate_revision(
            actor_id="user_local_admin",
            agent_code=TYPESCRIPT_AGENT,
            revision_id=revision_id,
        ),
        lambda: runtime.agent_config_service.publish(
            actor_id="user_local_admin",
            agent_code=TYPESCRIPT_AGENT,
            revision_id=revision_id,
        ),
        lambda: runtime.agent_config_service.rollback(
            actor_id="user_local_admin",
            agent_code=TYPESCRIPT_AGENT,
            publication_id=str(publication["id"]),
        ),
    )

    for operation in operations:
        with pytest.raises(NonRetryableExecutionError) as rejected:
            operation()
        assert rejected.value.error_code == RETIRED_ERROR

    current = _typescript_publication(runtime)
    assert current["id"] == publication["id"]
    assert current["config_hash"] == publication["config_hash"]


def test_business_application_rejects_new_typescript_reference_without_partial_write() -> None:
    runtime = _container()
    publication = _typescript_publication(runtime)
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="retired-typescript-reference",
        name="Retired TypeScript Reference",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision_ids_before = {
        row["id"]
        for row in runtime.database.execute(
            "select id from business_application_revision where application_id = ?",
            (application["id"],),
        )
    }

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.save_draft(
            actor_id="user_local_admin",
            code="retired-typescript-reference",
            expected_revision=int(application["revision"]),
            payload=_application_payload(str(publication["id"])),
        )

    assert rejected.value.error_code == RETIRED_ERROR
    revision_ids_after = {
        row["id"]
        for row in runtime.database.execute(
            "select id from business_application_revision where application_id = ?",
            (application["id"],),
        )
    }
    assert revision_ids_after == revision_ids_before


def test_historical_typescript_application_publication_cannot_be_reactivated() -> None:
    runtime = _container()
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="retired-typescript-activation",
        name="Retired TypeScript Activation",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="retired-typescript-activation",
        expected_revision=int(application["revision"]),
        payload=_application_payload("agent_publication_default_v1"),
    )
    application_publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="retired-typescript-activation",
        revision_id=str(revision["id"]),
    )
    historical_snapshot = dict(application_publication["snapshot"])
    historical_snapshot["agent"] = {
        **dict(historical_snapshot["agent"]),
        "id": "agent_publication_typescript_v1",
        "runtime_kind": "typescript-v1",
    }
    runtime.database.execute(
        "update business_application_publication set snapshot_json = ?, config_hash = ? where id = ?",
        (
            json.dumps(historical_snapshot, ensure_ascii=False, separators=(",", ":")),
            snapshot_hash(historical_snapshot),
            application_publication["id"],
        ),
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.activate(
            actor_id="user_local_admin",
            code="retired-typescript-activation",
            environment="local",
            publication_id=str(application_publication["id"]),
            expected_revision=0,
        )

    assert rejected.value.error_code == RETIRED_ERROR
    assert (
        runtime.business_application_repository.get_deployment(str(application["id"]), "local")
        is None
    )
