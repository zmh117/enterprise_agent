from __future__ import annotations

import hashlib
import json

from app.bootstrap import build_test_container
from app.cli import legacy_tool_migration
from app.modules.internal_tools.application.legacy_publication_migration import (
    BuiltinToolLegacyPublicationMigrator,
)
from backend.tests.test_agent_publication_runtime import publishable_config
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)
from backend.tests.test_legacy_tool_migration_report import (
    _publish_current_legacy_tool_candidates,
)


def _snapshot_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _prepare_uniquely_migratable_legacy_agent(runtime: object) -> str:
    source_id = "agent_publication_default_v1"
    runtime.database.execute(
        "delete from agent_tool_binding where publication_id = ? and tool_name <> ?",
        (source_id, "get_er_context"),
    )
    _publish_current_legacy_tool_candidates(runtime)
    pinned = publishable_config(runtime, builtin_tool_release_ids=[])
    source = runtime.agent_config_service.publication(source_id)
    snapshot = dict(source["snapshot"])
    snapshot["model_policy"] = dict(pinned["model_policy"])
    snapshot["tools"] = ["get_er_context"]
    runtime.database.execute(
        "update agent_publication set snapshot_json = ?, config_hash = ? where id = ?",
        (
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            _snapshot_hash(snapshot),
            source_id,
        ),
    )
    return source_id


def _create_active_legacy_application(runtime: object, source_agent_id: str) -> str:
    service = runtime.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="legacy-publication-migration",
        name="Legacy Publication Migration",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["agent_publication_id"] = source_agent_id
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="legacy-publication-migration",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = service.publish(
        actor_id="user_local_admin",
        code="legacy-publication-migration",
        revision_id=str(revision["id"]),
    )
    runtime.database.execute(
        """
        delete from business_application_publication_builtin_tool_resolution_set
         where application_publication_id = ?
        """,
        (publication["id"],),
    )
    # Simulate a pre-removal active legacy deployment without invoking the
    # removal-stage activation API, which must reject this publication.
    runtime.database.execute(
        """
        insert into business_application_deployment
          (id, application_id, environment, publication_id, active,
           revision, activated_by, activated_at, updated_at)
        values (?, ?, 'local', ?, 1, 1, 'pre-removal-fixture',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            f"legacy_deployment_{application['id']}",
            application["id"],
            publication["id"],
        ),
    )
    return str(publication["id"])


def test_unique_legacy_agent_and_application_create_new_exact_publications() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    source_agent_id = _prepare_uniquely_migratable_legacy_agent(runtime)
    source_application_id = _create_active_legacy_application(runtime, source_agent_id)
    source_agent_before = runtime.database.execute_one(
        "select snapshot_json, config_hash from agent_publication where id = ?",
        (source_agent_id,),
    )
    source_application_before = runtime.database.execute_one(
        "select snapshot_json, config_hash from business_application_publication where id = ?",
        (source_application_id,),
    )

    migrator = BuiltinToolLegacyPublicationMigrator(
        runtime.database,
        agent_config_service=runtime.agent_config_service,
        business_application_service=runtime.business_application_service,
    )
    result = migrator.migrate(
        actor_id="user_local_admin",
        correlation_id="legacy-publication-migration-test",
    )

    assert result["migrated_count"] == 2
    assert result["blocked_count"] == 0
    agent_result = next(
        item for item in result["migrated"] if item["source_type"] == "AGENT_PUBLICATION"
    )
    application_result = next(
        item
        for item in result["migrated"]
        if item["source_type"] == "APPLICATION_PUBLICATION"
    )
    assert agent_result["target_publication_id"] != source_agent_id
    assert application_result["target_publication_id"] != source_application_id
    assert runtime.database.execute_one(
        "select snapshot_json, config_hash from agent_publication where id = ?",
        (source_agent_id,),
    ) == source_agent_before
    assert runtime.database.execute_one(
        "select snapshot_json, config_hash from business_application_publication where id = ?",
        (source_application_id,),
    ) == source_application_before
    assert runtime.database.execute_one(
        "select status from agent_publication where id = ?", (source_agent_id,)
    ) == {"status": "inactive"}
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from agent_publication_builtin_tool
         where agent_publication_id = ?
        """,
        (agent_result["target_publication_id"],),
    ) == {"count": 1}
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from business_application_publication_builtin_tool
         where application_publication_id = ?
        """,
        (application_result["target_publication_id"],),
    ) == {"count": 1}
    assert runtime.database.execute_one(
        """
        select publication_id
          from business_application_deployment
         where application_id = (
               select id from business_application
                where code = 'legacy-publication-migration'
         )
           and environment = 'local'
        """
    ) == {"publication_id": application_result["target_publication_id"]}
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from builtin_tool_legacy_migration
         where migration_version = 'builtin-tool-exact-v1'
           and status = 'MATERIALIZED'
        """
    ) == {"count": 2}

    repeated = migrator.migrate(
        actor_id="user_local_admin",
        correlation_id="legacy-publication-migration-repeat",
    )
    assert repeated["migrated_count"] == 0
    assert runtime.database.execute_one(
        "select count(*) as count from agent_publication"
    ) == {"count": 2}
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from business_application_publication
         where application_id = (
               select id from business_application
                where code = 'legacy-publication-migration'
         )
        """
    ) == {"count": 2}
    runtime.database.close()


def test_publication_migration_reports_resource_and_model_blockers_without_writes() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    _publish_current_legacy_tool_candidates(runtime)
    before = {
        "agent_publications": runtime.database.execute_one(
            "select count(*) as count from agent_publication"
        ),
        "application_publications": runtime.database.execute_one(
            "select count(*) as count from business_application_publication"
        ),
        "ledger": runtime.database.execute_one(
            "select count(*) as count from builtin_tool_legacy_migration"
        ),
    }

    result = BuiltinToolLegacyPublicationMigrator(
        runtime.database,
        agent_config_service=runtime.agent_config_service,
        business_application_service=runtime.business_application_service,
    ).migrate(
        actor_id="user_local_admin",
        correlation_id="legacy-publication-blocked-test",
    )

    assert result["migrated_count"] == 0
    assert result["blocked_count"] > 0
    assert any(
        item["reason_code"] in {"validation_failed", "model_connection_required"}
        for item in result["blocked"]
        if item["source_type"] == "AGENT_PUBLICATION"
    )
    assert runtime.database.execute_one(
        "select count(*) as count from agent_publication"
    ) == before["agent_publications"]
    assert runtime.database.execute_one(
        "select count(*) as count from business_application_publication"
    ) == before["application_publications"]
    assert runtime.database.execute_one(
        "select count(*) as count from builtin_tool_legacy_migration"
    ) == before["ledger"]
    runtime.database.close()


def test_publication_migration_cli_requires_explicit_version_and_runs_exact_cutover(
    monkeypatch, capsys
) -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    source_agent_id = _prepare_uniquely_migratable_legacy_agent(runtime)
    _create_active_legacy_application(runtime, source_agent_id)
    monkeypatch.setattr(legacy_tool_migration, "load_settings", lambda: runtime.settings)
    monkeypatch.setattr(
        legacy_tool_migration,
        "build_api_container",
        lambda _settings: runtime,
    )

    exit_code = legacy_tool_migration.main(
        [
            "migrate-publications",
            "--actor-id",
            "user_local_admin",
            "--correlation-id",
            "legacy-publication-cli-test",
            "--confirm-migration-version",
            "builtin-tool-exact-v1",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["mode"] == "publication_migration"
    assert result["migrated_count"] == 2
    assert result["blocked_count"] == 0
