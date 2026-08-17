from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.business_application.domain.policies import snapshot_hash
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container, ensure_historical_typescript_agent


SOURCE_AGENT_PUBLICATION_ID = "agent_publication_typescript_v1"
TARGET_AGENT_PUBLICATION_ID = "agent_publication_default_v1"


def _payload(agent_publication_id: str) -> dict[str, object]:
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
        "mcp_tools": [],
    }


def _legacy_active_typescript_application(runtime: Any) -> dict[str, Any]:
    ensure_historical_typescript_agent(runtime)
    service = runtime.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="legacy-typescript-application",
        name="Legacy TypeScript Application",
        description="synthetic retirement fixture",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = service.save_draft(
        actor_id="user_local_admin",
        code=str(application["code"]),
        expected_revision=int(application["revision"]),
        payload=_payload(TARGET_AGENT_PUBLICATION_ID),
    )
    publication = service.publish(
        actor_id="user_local_admin",
        code=str(application["code"]),
        revision_id=str(revision["id"]),
    )
    deployment = service.activate(
        actor_id="user_local_admin",
        code=str(application["code"]),
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )

    source_agent = service.agent_reader.resolve(SOURCE_AGENT_PUBLICATION_ID)
    historical_snapshot = dict(publication["snapshot"])
    historical_snapshot["agent"] = {
        "id": source_agent.id,
        "code": source_agent.code,
        "revision": source_agent.revision,
        "project_code": source_agent.project_code,
        "config_hash": source_agent.config_hash,
        "runtime_kind": source_agent.runtime_kind,
        "runtime_protocol_versions": list(source_agent.runtime_protocol_versions),
    }
    historical_hash = snapshot_hash(historical_snapshot)
    runtime.database.execute(
        "update business_application_revision set agent_publication_id = ? where id = ?",
        (SOURCE_AGENT_PUBLICATION_ID, revision["id"]),
    )
    runtime.database.execute(
        "update business_application_publication set snapshot_json = ?, config_hash = ? where id = ?",
        (
            json.dumps(historical_snapshot, ensure_ascii=False, separators=(",", ":")),
            historical_hash,
            publication["id"],
        ),
    )
    return {
        "application": runtime.business_application_repository.get_by_code(
            str(application["code"])
        ),
        "source_publication": runtime.business_application_repository.get_publication(
            str(publication["id"])
        ),
        "deployment": deployment,
    }


def _migrate(runtime: Any, fixture: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    return runtime.business_application_service.migrate_retired_typescript_publication(
        actor_id="user_local_admin",
        source_application_publication_id=str(fixture["source_publication"]["id"]),
        source_agent_publication_id=SOURCE_AGENT_PUBLICATION_ID,
        target_python_agent_publication_id=TARGET_AGENT_PUBLICATION_ID,
        environment="local",
        expected_application_revision=int(fixture["application"]["revision"]),
        expected_deployment_revision=int(fixture["deployment"]["revision"]),
        correlation_id="retirement-migration-test",
        apply=apply,
    )


def _fact_counts(runtime: Any, application_id: str) -> tuple[int, int]:
    row = runtime.database.execute_one(
        """
        select
          (select count(*) from business_application_revision where application_id = ?) as revisions,
          (select count(*) from business_application_publication where application_id = ?) as publications
        """,
        (application_id, application_id),
    )
    assert row is not None
    return int(row["revisions"]), int(row["publications"])


def test_retirement_migration_dry_run_executes_validation_and_rolls_back() -> None:
    runtime = container()
    fixture = _legacy_active_typescript_application(runtime)
    application_id = str(fixture["application"]["id"])
    counts_before = _fact_counts(runtime, application_id)

    report = _migrate(runtime, fixture, apply=False)

    assert report["status"] == "ready"
    assert report["write_performed"] is False
    assert report["source"]["runtime_kind"] == "typescript-v1"
    assert report["target"]["runtime_kind"] == "python-v1"
    assert report["target"]["application_publication_id"] == ""
    assert report["sensitive_values_exposed"] is False
    assert _fact_counts(runtime, application_id) == counts_before
    deployment = runtime.business_application_repository.get_deployment(application_id, "local")
    assert deployment is not None
    assert deployment["publication_id"] == fixture["source_publication"]["id"]
    assert (
        runtime.database.execute(
            "select id from audit_event where event_type = ?",
            ("typescript_runtime.application_migrated",),
        )
        == []
    )


def test_retirement_migration_apply_creates_new_facts_and_preserves_history() -> None:
    runtime = container()
    fixture = _legacy_active_typescript_application(runtime)
    source_id = str(fixture["source_publication"]["id"])
    source_hash = str(fixture["source_publication"]["config_hash"])

    report = _migrate(runtime, fixture, apply=True)

    assert report["status"] == "migrated"
    assert report["write_performed"] is True
    target_application_publication_id = str(report["target"]["application_publication_id"])
    assert target_application_publication_id
    deployment = runtime.business_application_repository.get_deployment(
        str(fixture["application"]["id"]), "local"
    )
    assert deployment is not None
    assert deployment["publication_id"] == target_application_publication_id
    target = runtime.business_application_repository.get_publication(
        target_application_publication_id
    )
    assert target["snapshot"]["agent"]["id"] == TARGET_AGENT_PUBLICATION_ID
    assert target["snapshot"]["agent"]["runtime_kind"] == "python-v1"
    historical = runtime.business_application_repository.get_publication(source_id)
    assert historical["config_hash"] == source_hash
    assert historical["snapshot"]["agent"]["runtime_kind"] == "typescript-v1"
    audit = runtime.database.execute_one(
        "select actor_id, payload_summary from audit_event where event_type = ?",
        ("typescript_runtime.application_migrated",),
    )
    assert audit is not None
    assert audit["actor_id"] == "user_local_admin"
    payload_summary = json.loads(str(audit["payload_summary"]))
    payload = json.loads(str(payload_summary["payload"]))
    assert payload["source_application_publication_id"] == source_id
    assert payload["target_application_publication_id"] == (target_application_publication_id)
    assert payload["correlation_id"] == "retirement-migration-test"


def test_retirement_migration_rejects_concurrent_revision_without_writes() -> None:
    runtime = container()
    fixture = _legacy_active_typescript_application(runtime)
    counts_before = _fact_counts(runtime, str(fixture["application"]["id"]))
    fixture["application"]["revision"] = int(fixture["application"]["revision"]) - 1

    with pytest.raises(NonRetryableExecutionError) as rejected:
        _migrate(runtime, fixture, apply=True)

    assert rejected.value.error_code == "revision_conflict"
    assert _fact_counts(runtime, str(fixture["application"]["id"])) == counts_before


def test_retirement_migration_rejects_incompatible_tool_and_rolls_back() -> None:
    runtime = container()
    fixture = _legacy_active_typescript_application(runtime)
    source = fixture["source_publication"]
    incompatible_snapshot = dict(source["snapshot"])
    incompatible_snapshot["mcp_tools"] = [
        {
            "server_code": "tool-mcp",
            "tool_identifier": "not_bound_to_target",
            "schema_hash": "0" * 64,
            "selection_order": 0,
        }
    ]
    runtime.database.execute(
        "update business_application_publication set snapshot_json = ?, config_hash = ? where id = ?",
        (
            json.dumps(incompatible_snapshot, ensure_ascii=False, separators=(",", ":")),
            snapshot_hash(incompatible_snapshot),
            source["id"],
        ),
    )
    counts_before = _fact_counts(runtime, str(fixture["application"]["id"]))

    with pytest.raises(NonRetryableExecutionError):
        _migrate(runtime, fixture, apply=True)

    assert _fact_counts(runtime, str(fixture["application"]["id"])) == counts_before
    deployment = runtime.business_application_repository.get_deployment(
        str(fixture["application"]["id"]), "local"
    )
    assert deployment is not None
    assert deployment["publication_id"] == source["id"]


def test_retirement_migration_activation_failure_rolls_back_all_new_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = container()
    fixture = _legacy_active_typescript_application(runtime)
    application_id = str(fixture["application"]["id"])
    counts_before = _fact_counts(runtime, application_id)

    def reject_activation(**_kwargs: object) -> dict[str, Any]:
        raise NonRetryableExecutionError(
            "synthetic activation failure",
            safe_message="合成激活失败",
            error_code="synthetic_activation_failure",
        )

    monkeypatch.setattr(
        runtime.business_application_repository,
        "activate",
        reject_activation,
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        _migrate(runtime, fixture, apply=True)

    assert rejected.value.error_code == "synthetic_activation_failure"
    assert _fact_counts(runtime, application_id) == counts_before
    deployment = runtime.business_application_repository.get_deployment(application_id, "local")
    assert deployment is not None
    assert deployment["publication_id"] == fixture["source_publication"]["id"]
