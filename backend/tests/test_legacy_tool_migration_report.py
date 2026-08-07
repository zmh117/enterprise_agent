from __future__ import annotations

import json
from dataclasses import replace

from app.bootstrap import build_test_container
from app.cli import legacy_tool_migration
from app.modules.internal_tools.application.legacy_migration import (
    BuiltinToolLegacyMigrationService,
)
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    build_builtin_handler_registry,
)
from app.modules.platform_config.infrastructure.repository import now_iso
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
)


def _publish_current_legacy_tool_candidates(runtime: object) -> None:
    handlers = runtime.platform_config_service.handlers
    handlers.reconcile(actor_id="user_local_admin")
    publication = runtime.database.execute_one(
        """
        select current_publication_id
          from agent_definition
         where code = 'default-diagnostic-agent'
        """
    )
    assert publication is not None
    tool_names = runtime.database.execute(
        """
        select tool_name
          from agent_tool_binding
         where publication_id = ?
         order by tool_name
        """,
        (publication["current_publication_id"],),
    )
    for row in tool_names:
        tool_identifier = str(row["tool_name"])
        evidence = handlers.verify_payload(
            {
                "tool_identifier": tool_identifier,
                "handler_version": "1.0.0",
            },
            actor_id="user_local_admin",
        )
        handlers.publish_builtin_tool_payload(
            {
                "tool_identifier": tool_identifier,
                "handler_version": "1.0.0",
                "verification_id": evidence["id"],
                "idempotency_key": f"legacy-report-{tool_identifier}-v1",
            },
            actor_id="user_local_admin",
        )


def test_legacy_report_is_read_only_and_counts_active_and_recoverable_references() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    before = {
        "ledger": runtime.database.execute_one(
            "select count(*) as count from builtin_tool_legacy_migration"
        ),
        "audit": runtime.database.execute_one(
            "select count(*) as count from builtin_tool_legacy_write_audit"
        ),
    }

    report = BuiltinToolLegacyMigrationService(runtime.database).report(
        detail_limit=0
    )

    assert report["mode"] == "read_only_report"
    assert report["safe_fields_only"] is True
    assert report["legacy_write_allowed"] is False
    assert report["counts"]["all_agent_name_bindings"] > 0
    assert report["counts"]["active_agent_name_bindings"] > 0
    assert report["counts"]["active_agent_publications_with_legacy"] > 0
    assert report["detail_count"] > 0
    assert report["details"] == []
    assert report["details_truncated"] is True
    assert runtime.database.execute_one(
        "select count(*) as count from builtin_tool_legacy_migration"
    ) == before["ledger"]
    assert runtime.database.execute_one(
        "select count(*) as count from builtin_tool_legacy_write_audit"
    ) == before["audit"]
    runtime.database.close()


def test_legacy_report_classifies_one_release_and_resource_policy_blockers() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    _publish_current_legacy_tool_candidates(runtime)
    agent_publication_id = str(
        runtime.database.execute_one(
            """
            select current_publication_id
              from agent_definition
             where code = 'default-diagnostic-agent'
            """
        )["current_publication_id"]
    )
    timestamp = now_iso()
    runtime.database.execute(
        """
        insert into business_application
          (id, code, name, description, project_code, status, revision,
           created_by, created_at, updated_at)
        values ('legacy_report_application', 'legacy-report-app',
                'Legacy Report App', '', 'default', 'enabled', 1,
                'user_local_admin', ?, ?)
        """,
        (timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, agent_publication_id,
           session_policy_json, execution_policy_json, validation_json,
           config_hash, created_by, created_at, updated_at)
        values ('legacy_report_application_revision',
                'legacy_report_application', 1, 'published', ?, '{}', '{}',
                '{"valid":true,"errors":[]}', 'legacy-report-app-hash',
                'user_local_admin', ?, ?)
        """,
        (agent_publication_id, timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, schema_version,
           snapshot_json, config_hash, published_by, published_at)
        values ('legacy_report_application_publication',
                'legacy_report_application',
                'legacy_report_application_revision', 1, 1, '{}',
                'legacy-report-app-hash', 'user_local_admin', ?)
        """,
        (timestamp,),
    )
    runtime.database.execute(
        """
        insert into business_application_deployment
          (id, application_id, environment, publication_id, active, revision,
           activated_by, activated_at, updated_at)
        values ('legacy_report_application_deployment',
                'legacy_report_application', 'local',
                'legacy_report_application_publication', 1, 1,
                'user_local_admin', ?, ?)
        """,
        (timestamp, timestamp),
    )

    report = BuiltinToolLegacyMigrationService(runtime.database).report()

    agent = next(
        item
        for item in report["details"]
        if item["source_type"] == "AGENT_PUBLICATION"
        and item["source_id"] == agent_publication_id
    )
    assert agent["candidate_class"] == "ONE"
    assert agent["candidate_count"] == 1
    assert all(
        item["candidate_class"] == "ONE" for item in agent["tool_candidates"]
    )

    applications = [
        item
        for item in report["details"]
        if item["source_type"] == "APPLICATION_PUBLICATION"
        and item["agent_publication_id"] == agent_publication_id
    ]
    assert applications
    assert applications[0]["release_candidate_class"] == "ONE"
    assert applications[0]["candidate_class"] == "ZERO"
    assert applications[0]["blocking_dimensions"] == [
        "resource_policy_mapping_missing"
    ]
    runtime.database.close()


def test_legacy_report_classifies_multiple_code_exact_release_candidates() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    handlers = runtime.platform_config_service.handlers
    handlers.reconcile(actor_id="user_local_admin")
    evidence = handlers.verify_payload(
        {
            "tool_identifier": "query_database",
            "handler_version": "1.0.0",
        },
        actor_id="user_local_admin",
    )
    handlers.publish_builtin_tool_payload(
        {
            "tool_identifier": "query_database",
            "handler_version": "1.0.0",
            "verification_id": evidence["id"],
            "idempotency_key": "legacy-report-query-database-v1",
        },
        actor_id="user_local_admin",
    )

    default_registry = build_builtin_handler_registry()
    current = default_registry.require("query_database", "1.0.0")
    next_definition = replace(
        current,
        handler_version="2.0.0",
        tool_semantic_version="2.0.0",
        implementation_key=f"{current.implementation_key}:v2",
    )
    registry = HandlerRegistry((*default_registry.definitions(), next_definition))
    timestamp = now_iso()
    runtime.database.execute(
        """
        insert into builtin_tool_manifest_projection
          (tool_identifier, handler_version, implementation_digest,
           tool_semantic_version, manifest_hash, public_schema_hash,
           manifest_json, verifier_plan_json, verifier_version, observed_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            next_definition.tool_identifier,
            next_definition.handler_version,
            next_definition.implementation_digest,
            next_definition.tool_semantic_version,
            next_definition.manifest_hash,
            next_definition.public_schema_hash,
            json.dumps(next_definition.manifest(), sort_keys=True),
            json.dumps(next_definition.verifier_plan.public(), sort_keys=True),
            next_definition.verifier_plan.verifier_version,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into builtin_tool_installation
          (tool_identifier, handler_version, implementation_digest,
           installation_status, first_seen_at, last_seen_at)
        values (?, ?, ?, 'INSTALLED', ?, ?)
        """,
        (
            next_definition.tool_identifier,
            next_definition.handler_version,
            next_definition.implementation_digest,
            timestamp,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into builtin_tool_verification
          (id, tool_identifier, handler_version, implementation_digest,
           verifier_version, normalized_input_hash, status,
           result_summary_json, verified_by, verified_at)
        values ('legacy_report_verification_v2', ?, ?, ?, ?, ?, 'PASSED',
                '{}', 'user_local_admin', ?)
        """,
        (
            next_definition.tool_identifier,
            next_definition.handler_version,
            next_definition.implementation_digest,
            next_definition.verifier_plan.verifier_version,
            "e" * 64,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into builtin_tool_release
          (id, tool_identifier, release_revision, tool_semantic_version,
           handler_version, implementation_digest, manifest_hash,
           public_schema_hash, verification_id, status, idempotency_key,
           published_by, published_at)
        values ('legacy_report_release_v2', ?, 2, ?, ?, ?, ?, ?,
                'legacy_report_verification_v2', 'ACTIVE',
                'legacy-report-release-v2', 'user_local_admin', ?)
        """,
        (
            next_definition.tool_identifier,
            next_definition.tool_semantic_version,
            next_definition.handler_version,
            next_definition.implementation_digest,
            next_definition.manifest_hash,
            next_definition.public_schema_hash,
            timestamp,
        ),
    )
    agent = runtime.database.execute_one(
        "select id from agent_definition where code = 'default-diagnostic-agent'"
    )
    assert agent is not None
    runtime.database.execute(
        """
        insert into agent_revision
          (id, agent_id, revision, status, config_json, config_hash,
           validation_json, created_by, created_at, updated_at)
        values ('legacy_report_agent_revision', ?, 999, 'published', '{}',
                'legacy-report-agent-hash', '{}', 'user_local_admin', ?, ?)
        """,
        (agent["id"], timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into agent_publication
          (id, agent_id, revision_id, revision, schema_version, snapshot_json,
           config_hash, status, published_by, published_at)
        values ('legacy_report_agent_publication', ?,
                'legacy_report_agent_revision', 999, 1, '{}',
                'legacy-report-agent-hash', 'active', 'user_local_admin', ?)
        """,
        (agent["id"], timestamp),
    )
    runtime.database.execute(
        """
        insert into agent_tool_binding (id, publication_id, tool_name, created_at)
        values ('legacy_report_tool_binding', 'legacy_report_agent_publication',
                'query_database', ?)
        """,
        (timestamp,),
    )

    report = BuiltinToolLegacyMigrationService(
        runtime.database,
        registry=registry,
    ).report()

    item = next(
        value
        for value in report["details"]
        if value["source_id"] == "legacy_report_agent_publication"
    )
    assert item["candidate_class"] == "MULTIPLE"
    assert item["candidate_count"] == 2
    assert item["reason_code"] == "builtin_tool_legacy_resolution_ambiguous"
    runtime.database.close()


def test_legacy_tool_migration_cli_report_is_read_only(monkeypatch, capsys) -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    monkeypatch.setattr(
        legacy_tool_migration,
        "load_settings",
        lambda: runtime.settings,
    )
    monkeypatch.setattr(
        legacy_tool_migration,
        "build_api_container",
        lambda _settings: runtime,
    )

    assert legacy_tool_migration.main(["report", "--detail-limit", "0"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "read_only_report"
    assert result["details"] == []
    assert result["legacy_write_allowed"] is False
