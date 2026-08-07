from __future__ import annotations

import json

from app.bootstrap import build_test_container
from app.cli import legacy_tool_migration
from app.modules.internal_tools.application.legacy_job_migration import (
    BuiltinToolLegacyJobMigrator,
)
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from backend.tests.helpers import grant_test_application_access
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
)
from backend.tests.test_legacy_publication_migration import (
    _create_active_legacy_application,
)
from backend.tests.test_legacy_tool_migration_report import (
    _publish_current_legacy_tool_candidates,
)


def _legacy_recoverable_job(
    runtime: object,
    *,
    publish_candidate: bool,
    idempotency_key: str,
) -> object:
    source_agent_id = "agent_publication_default_v1"
    runtime.database.execute(
        "delete from agent_tool_binding where publication_id = ? and tool_name <> ?",
        (source_agent_id, "get_er_context"),
    )
    if publish_candidate:
        _publish_current_legacy_tool_candidates(runtime)
    source_application_id = _create_active_legacy_application(
        runtime,
        source_agent_id,
    )
    application = runtime.business_application_repository.get_by_code(
        "legacy-publication-migration"
    )
    deployment = next(
        item
        for item in application["deployments"]
        if item["publication_id"] == source_application_id
    )
    environment = runtime.platform_config_service.upsert_environment(
        {"code": f"legacy-job-{idempotency_key}"},
        actor_id="user_local_admin",
    )
    grant_test_application_access(
        runtime,
        application_id=str(application["id"]),
        role_code=f"legacy-job-{idempotency_key}-role",
        scopes=({"environment_id": str(environment["id"])},),
    )
    agent = runtime.agent_config_service.publication(source_agent_id)
    publication = runtime.business_application_repository.get_publication(
        source_application_id
    )
    resolution_set = publication["snapshot"]["builtin_tool_resolution_set"]
    runtime.database.execute(
        """
        insert into business_application_publication_builtin_tool_resolution_set
          (application_publication_id, schema_version, resolution_count,
           resolution_set_hash, created_at)
        values (?, 1, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            source_application_id,
            int(resolution_set["resolution_count"]),
            resolution_set["resolution_set_hash"],
        ),
    )
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=idempotency_key,
            user_message="验证旧 Job 快照迁移",
            requester_id="user_local_admin",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            external_conversation_id=f"conversation-{idempotency_key}",
            reply_route={
                "type": "none",
                "connector_id": "",
                "target": {},
                "options": {},
            },
            routing_context={
                "project_code": "default",
                "environment": str(environment["code"]),
                "base": "",
                "workshop": "",
                "environment_id": str(environment["id"]),
                "base_id": "",
                "workshop_id": "",
            },
            fixed_agent_publication_id=source_agent_id,
            fixed_agent_revision=int(agent["revision"]),
            fixed_agent_config_hash=str(agent["config_hash"]),
            agent_code="default-diagnostic-agent",
            business_application_id=str(application["id"]),
            business_application_code=str(application["code"]),
            business_application_publication_id=source_application_id,
            business_application_deployment_id=str(deployment["id"]),
            business_application_config_hash=str(publication["config_hash"]),
            business_application_runtime_status="ready",
            conversation_mode="channel",
            session_policy={"conversation_mode": "channel"},
        )
    )
    runtime.database.execute(
        """
        delete from business_application_publication_builtin_tool_resolution_set
         where application_publication_id = ?
        """,
        (source_application_id,),
    )
    assert runtime.database.execute_one(
        "select id from agent_job_builtin_tool_snapshot where job_id = ?",
        (job.id,),
    ) is None
    route_row = runtime.database.execute_one(
        "select business_application_route_decision_json from agent_job where id = ?",
        (job.id,),
    )
    assert route_row is not None
    route_decision = json.loads(route_row["business_application_route_decision_json"])
    runtime_authorization = {
        "schema_version": 2,
        "application_publication": {
            "id": source_application_id,
            "application_id": str(application["id"]),
            "revision": int(publication["revision"]),
            "config_hash": str(publication["config_hash"]),
        },
        "agent_publication_id": source_agent_id,
        "agent_classification": "internal_diagnostic",
        "requested_scope": {
            "scope_key": f"{environment['id']}||",
            "environment_id": str(environment["id"]),
            "environment_code": str(environment["code"]),
            "base_id": "",
            "base_code": "",
            "workshop_id": "",
            "workshop_code": "",
        },
        "bindings": [],
    }
    route_decision["runtime_authorization"] = runtime_authorization
    runtime.database.execute(
        "update agent_job set business_application_route_decision_json = ? where id = ?",
        (json.dumps(route_decision, ensure_ascii=False), job.id),
    )
    runtime.agent_repository.create_execution_scope(
        job_id=job.id,
        runtime_authorization=runtime_authorization,
    )
    return runtime.agent_repository.get_job(job.id)


def test_unique_resource_free_legacy_job_snapshot_is_materialized_idempotently() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    job = _legacy_recoverable_job(
        runtime,
        publish_candidate=True,
        idempotency_key="legacy-job-materialize",
    )
    migrator = BuiltinToolLegacyJobMigrator(
        runtime.database,
        snapshot_service=runtime.builtin_tool_snapshot_service,
    )

    result = migrator.migrate(
        actor_id="user_local_admin",
        correlation_id="legacy-job-materialize-test",
    )

    assert result["materialized_count"] == 1
    assert result["quarantined_count"] == 0
    frozen = runtime.builtin_tool_snapshot_service.verify(job.id)
    assert len(frozen["snapshot"]["bindings"]) == 1
    assert frozen["snapshot"]["bindings"][0]["tool_identifier"] == "get_er_context"
    assert frozen["snapshot"]["bindings"][0]["candidates"] == []
    assert runtime.database.execute_one(
        "select status from agent_job where id = ?", (job.id,)
    ) == {"status": "PENDING"}
    before = runtime.database.execute_one(
        "select snapshot_hash from agent_job_builtin_tool_snapshot where job_id = ?",
        (job.id,),
    )

    repeated = migrator.migrate(
        actor_id="user_local_admin",
        correlation_id="legacy-job-materialize-repeat",
    )
    assert repeated["materialized_count"] == 0
    assert repeated["quarantined_count"] == 0
    assert runtime.database.execute_one(
        "select snapshot_hash from agent_job_builtin_tool_snapshot where job_id = ?",
        (job.id,),
    ) == before
    assert runtime.database.execute_one(
        """
        select count(*) as count from builtin_tool_legacy_migration
         where source_type = 'JOB' and source_id = ?
        """,
        (job.id,),
    ) == {"count": 1}
    runtime.database.close()


def test_unresolvable_legacy_job_is_quarantined_and_cannot_retry_or_replay() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    job = _legacy_recoverable_job(
        runtime,
        publish_candidate=False,
        idempotency_key="legacy-job-quarantine",
    )
    migrator = BuiltinToolLegacyJobMigrator(
        runtime.database,
        snapshot_service=runtime.builtin_tool_snapshot_service,
    )

    result = migrator.migrate(
        actor_id="user_local_admin",
        correlation_id="legacy-job-quarantine-test",
    )

    assert result["materialized_count"] == 0
    assert result["quarantined_count"] == 1
    assert result["quarantined"][0]["reason_code"] == (
        "builtin_tool_legacy_resolution_missing"
    )
    state = runtime.database.execute_one(
        """
        select status, retry_count, max_retry_count, last_error_code
          from agent_job where id = ?
        """,
        (job.id,),
    )
    assert state == {
        "status": "FAILED",
        "retry_count": state["max_retry_count"],
        "max_retry_count": state["max_retry_count"],
        "last_error_code": "builtin_tool_legacy_resolution_missing",
    }
    dispatch = runtime.database.execute_one(
        """
        select status, replay_count, max_replay_count, last_error_code
          from job_dispatch_outbox where job_id = ?
        """,
        (job.id,),
    )
    assert dispatch == {
        "status": "DEAD",
        "replay_count": dispatch["max_replay_count"],
        "max_replay_count": dispatch["max_replay_count"],
        "last_error_code": "builtin_tool_legacy_resolution_missing",
    }
    ledger = runtime.database.execute_one(
        """
        select candidate_class, status, quarantine_reason_code, snapshot_hash
          from builtin_tool_legacy_migration
         where source_type = 'JOB' and source_id = ?
        """,
        (job.id,),
    )
    assert ledger == {
        "candidate_class": "ZERO",
        "status": "QUARANTINED",
        "quarantine_reason_code": "builtin_tool_legacy_resolution_missing",
        "snapshot_hash": None,
    }

    repeated = migrator.migrate(
        actor_id="user_local_admin",
        correlation_id="legacy-job-quarantine-repeat",
    )
    assert repeated["source_count"] == 0
    runtime.database.close()


def test_legacy_job_migration_cli_materializes_in_maintenance_mode(
    monkeypatch, capsys
) -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    _legacy_recoverable_job(
        runtime,
        publish_candidate=True,
        idempotency_key="legacy-job-cli",
    )
    monkeypatch.setattr(legacy_tool_migration, "load_settings", lambda: runtime.settings)
    monkeypatch.setattr(
        legacy_tool_migration,
        "build_api_container",
        lambda _settings: runtime,
    )

    exit_code = legacy_tool_migration.main(
        [
            "migrate-jobs",
            "--actor-id",
            "user_local_admin",
            "--correlation-id",
            "legacy-job-cli-test",
            "--confirm-migration-version",
            "builtin-tool-exact-v1",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["mode"] == "job_snapshot_migration"
    assert result["materialized_count"] == 1
    assert result["quarantined_count"] == 0
