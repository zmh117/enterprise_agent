from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import uuid

import pytest

from app.bootstrap import build_api_container, build_worker_container
from app.cli import baseline_adoption as baseline_adoption_cli
from app.cli import migrate as migrate_cli
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import (
    BaselineAdoptionInspector,
    BaselineAdoptionRollback,
    MigrationDefinitionError,
    MigrationExecutionError,
    Migrator,
    SchemaMigrationLedger,
    SchemaHeadError,
    SchemaHeadValidator,
    load_migration_catalog,
    deployable_migration_catalog,
    migration_checksum,
    normalized_migration_sql,
)
from app.shared.schema_baseline import (
    LEGACY_MANIFEST_FILENAME,
    catalog_digest,
    load_legacy_manifest,
)


def test_repository_migration_catalog_has_unique_ordered_versions_and_checksums() -> None:
    catalog = load_migration_catalog(default_migrations_dir())

    assert len({item.version for item in catalog}) == len(catalog)
    assert len({item.name for item in catalog}) == len(catalog)
    assert [(item.version, item.name) for item in catalog] == [
        ("100", "100_baseline_v1.sql"),
        ("101", "101_expand_canonical_job_message.sql"),
        ("102", "102_schema_consolidation_checkpoint.sql"),
        ("103", "103_contract_retire_compatibility_shadows.sql"),
        ("104", "104_add_identity_aware_ones_mcp.sql"),
        ("105", "105_expand_unified_mcp_operation_audit.sql"),
        ("106", "106_expand_agent_run_audit.sql"),
        ("107", "107_expand_task_file_workspaces.sql"),
        ("108", "108_stage_attachment_only_messages.sql"),
        ("109", "109_allow_file_service_mcp_publications.sql"),
        ("110", "110_expand_file_source_received_time.sql"),
        ("111", "111_expand_text_file_format_policy.sql"),
        ("112", "112_expand_resource_revision_scope_bindings.sql"),
        ("113", "113_expand_document_file_processing.sql"),
        ("114", "114_expand_execution_summary_protocol_v13.sql"),
        ("115", "115_expand_file_turn_admission.sql"),
        ("116", "116_expand_office_embedded_image_layout_ocr.sql"),
        ("117", "117_expand_docling_layout_ocr_v2.sql"),
        ("118", "118_expand_bounded_workspace_working_sets.sql"),
        ("119", "119_contract_single_current_file_rule.sql"),
    ]
    assert all(len(item.checksum) == 64 for item in catalog)
    assert [item.version for item in deployable_migration_catalog(catalog)] == [
        "100",
        "101",
        "102",
        "103",
        "104",
        "105",
        "106",
        "107",
        "108",
        "109",
        "110",
        "111",
        "112",
        "113",
        "114",
        "115",
        "116",
        "117",
        "118",
        "119",
    ]

    manifest = load_legacy_manifest(default_migrations_dir() / LEGACY_MANIFEST_FILENAME)
    assert manifest["legacy_head"] == "042"
    assert manifest["target_baseline"] == "100"
    assert len(manifest["catalog"]) == 43
    assert manifest["catalog_digest"] == catalog_digest(manifest["catalog"])


def test_agent_run_audit_expand_keeps_job_lifecycle_separate() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="agent-run-audit-test").run()

    tables = {
        row["name"]
        for row in database.execute("select name from sqlite_master where type = 'table'")
    }
    assert {"agent_job_execution_summary", "agent_model_call"}.issubset(tables)
    job_columns = {row["name"] for row in database.execute("pragma table_info(agent_job)")}
    assert {
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
        "total_duration_ms",
    }.isdisjoint(job_columns)
    protocol = next(
        row
        for row in database.execute("pragma table_info(agent_job)")
        if row["name"] == "agent_runtime_protocol_version"
    )
    assert str(protocol["dflt_value"]).strip("'") == "1.3"
    summary_fks = database.execute("pragma foreign_key_list(agent_job_execution_summary)")
    model_fks = database.execute("pragma foreign_key_list(agent_model_call)")
    assert any(row["table"] == "agent_job" and row["on_delete"] == "CASCADE" for row in summary_fks)
    assert any(row["table"] == "agent_job" and row["on_delete"] == "CASCADE" for row in model_fks)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("legacy_head", "041"),
        ("target_baseline", "101"),
        ("catalog_digest", "0" * 64),
        ("catalog_checksum", "0" * 64),
    ],
)
def test_legacy_manifest_rejects_immutable_evidence_drift(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    manifest = load_legacy_manifest(default_migrations_dir() / LEGACY_MANIFEST_FILENAME)
    if field == "catalog_checksum":
        manifest["catalog"][0]["checksum"] = value
    else:
        manifest[field] = value
    path = tmp_path / LEGACY_MANIFEST_FILENAME
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest"):
        load_legacy_manifest(path)


def test_migration_checksum_normalizes_line_endings_but_detects_content_drift() -> None:
    lf = normalized_migration_sql(b"select 1;\nselect 2;\n")
    crlf = normalized_migration_sql(b"select 1;\r\nselect 2;\r\n")

    assert migration_checksum(lf) == migration_checksum(crlf)
    assert migration_checksum(lf) != migration_checksum(lf + "-- changed\n")


def test_migration_catalog_rejects_duplicate_versions_before_database_access(
    tmp_path: Path,
) -> None:
    (tmp_path / "001_first.sql").write_text("select 1;\n", encoding="utf-8")
    (tmp_path / "001_second.sql").write_text("select 2;\n", encoding="utf-8")

    with pytest.raises(MigrationDefinitionError, match="Duplicate migration version 001"):
        load_migration_catalog(tmp_path)


def test_schema_head_validator_allows_only_an_explicit_previous_head(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_initial.sql").write_text(
        "create table example (id text primary key);\n",
        encoding="utf-8",
    )
    database = Database(f"sqlite:///{tmp_path / 'previous-head.db'}")
    Migrator(database, migrations, migrator_build="previous-head-test").run()
    (migrations / "002_contract.sql").write_text(
        "alter table example add column value text;\n",
        encoding="utf-8",
    )

    validator = SchemaHeadValidator(database, migrations)
    assert validator.require_current_or_previous(
        allowed_previous_heads=frozenset({"001"})
    ) == "001"
    with pytest.raises(SchemaHeadError, match="expected 002"):
        validator.require_current()
    with pytest.raises(SchemaHeadError, match="unknown"):
        validator.require_current_or_previous(
            allowed_previous_heads=frozenset({"999"})
        )


@pytest.mark.parametrize("name", ["099_reused.sql", "100a_reused.sql"])
def test_baseline_catalog_forbids_reusing_versions_before_101(
    tmp_path: Path,
    name: str,
) -> None:
    migrations = default_migrations_dir()
    (tmp_path / "100_baseline_v1.sql").write_bytes(
        (migrations / "100_baseline_v1.sql").read_bytes()
    )
    (tmp_path / LEGACY_MANIFEST_FILENAME).write_bytes(
        (migrations / LEGACY_MANIFEST_FILENAME).read_bytes()
    )
    (tmp_path / name).write_text("select 1;\n", encoding="utf-8")

    with pytest.raises(
        MigrationDefinitionError,
        match="start at 100|from 101|three-digit integers",
    ):
        Migrator(
            Database("sqlite:///:memory:"),
            tmp_path,
            migrator_build="version-gate-test",
        ).run()


def test_baseline_refuses_nonempty_schema_without_ledger_rows() -> None:
    database = Database("sqlite:///:memory:")
    database.execute("create table unknown_application_table (id text primary key)")

    with pytest.raises(MigrationDefinitionError, match="Non-empty application schema"):
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="test-build",
        ).run()

    assert SchemaMigrationLedger(database).list_records() == []


def test_one_shot_migrator_applies_fresh_database_and_is_idempotent() -> None:
    database = Database("sqlite:///:memory:")
    migrator = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="test-build",
    )

    first = migrator.run()
    second = migrator.run()

    assert first.head == "119"
    assert first.baselined == 0
    assert first.applied == (
        "100",
        "101",
        "102",
        "103",
        "104",
        "105",
        "106",
        "107",
        "108",
        "109",
        "110",
        "111",
        "112",
        "113",
        "114",
        "115",
        "116",
        "117",
        "118",
        "119",
    )
    assert second.head == "119"
    assert second.baselined == 0
    assert second.applied == ()
    assert len(SchemaMigrationLedger(database).list_records()) == len(
        deployable_migration_catalog(load_migration_catalog(default_migrations_dir()))
    )


def test_explicit_fresh_contract_remains_supported_after_release() -> None:
    database = Database("sqlite:///:memory:")

    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="explicit-fresh-contract-test",
        include_schema_contract=True,
    ).run()

    assert result.head == "119"
    assert result.applied == (
        "100",
        "101",
        "102",
        "103",
        "104",
        "105",
        "106",
        "107",
        "108",
        "109",
        "110",
        "111",
        "112",
        "113",
        "114",
        "115",
        "116",
        "117",
        "118",
        "119",
    )
    assert SchemaHeadValidator(database, default_migrations_dir()).require_current() == "119"
    assert (
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="post-contract-normal-startup",
        )
        .run()
        .applied
        == ()
    )
    assert {
        "dingding_conversation_id",
        "dingding_user_id",
        "source",
    }.isdisjoint({row["name"] for row in database.execute("pragma table_info(agent_session)")})
    assert {"user_id", "source", "user_message"}.isdisjoint(
        {row["name"] for row in database.execute("pragma table_info(agent_job)")}
    )
    assert "graph_json" not in {
        row["name"] for row in database.execute("pragma table_info(agent_workflow_template)")
    }


def test_identity_aware_ones_mcp_migration_upgrades_103_and_enforces_schema(
    tmp_path: Path,
) -> None:
    database = Database("sqlite:///:memory:")
    through_103 = _migrations_through(tmp_path, "103")
    initial = Migrator(
        database,
        through_103,
        migrator_build="identity-aware-ones-predecessor",
        include_schema_contract=True,
    ).run()
    assert initial.head == "103"
    timestamp = "2026-08-12T00:00:00+00:00"
    database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('ones-migration-user', 'ones-migration-user', 'ONES Migration User',
                'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into user_external_identity
          (id, user_id, provider, tenant_code, external_subject_id, connector_id,
           display_name, status, verified_at, metadata_json, revision,
           created_at, updated_at)
        values ('ones-migration-identity', 'ones-migration-user', 'ones', 'default',
                'ONES-MIGRATION-SUBJECT', '', 'ONES Migration Subject', 'enabled',
                ?, '{}', 1, ?, ?)
        """,
        (timestamp, timestamp, timestamp),
    )

    upgraded = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="identity-aware-ones-upgrade",
    ).run()
    repeated = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="identity-aware-ones-repeat",
    ).run()

    assert upgraded.applied == (
        "104", "105", "106", "107", "108", "109", "110", "111", "112", "113", "114", "115", "116", "117", "118", "119"
    )
    assert repeated.applied == ()
    assert database.execute_one(
        "select external_subject_id from user_external_identity where id = ?",
        ("ones-migration-identity",),
    ) == {"external_subject_id": "ONES-MIGRATION-SUBJECT"}
    tables = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'table'")
    }
    assert {"external_identity_credential", "mcp_operation_audit"}.issubset(tables)
    challenge_columns = {
        str(row["name"])
        for row in database.execute("pragma table_info(ones_identity_verification_challenge)")
    }
    assert {
        "login_material_ciphertext",
        "login_material_nonce",
        "token_ciphertext",
        "token_nonce",
        "credential_key_id",
        "credential_algorithm",
    }.issubset(challenge_columns)
    credential_foreign_keys = {
        (str(row["table"]), str(row["from"]), str(row["to"]))
        for row in database.execute("pragma foreign_key_list(external_identity_credential)")
    }
    assert (
        "user_external_identity",
        "external_identity_id",
        "id",
    ) in credential_foreign_keys
    audit_foreign_key_tables = {
        str(row["table"])
        for row in database.execute("pragma foreign_key_list(mcp_operation_audit)")
    }
    assert {
        "agent_job",
        "agent_session",
        "app_user",
        "user_external_identity",
        "external_identity_credential",
        "audit_event",
        "agent_tool_call",
    }.issubset(audit_foreign_key_tables)
    indexes = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'index'")
    }
    assert {
        "idx_external_identity_credential_provider_status",
        "idx_external_identity_credential_updated",
        "idx_mcp_operation_audit_created",
        "idx_mcp_operation_audit_correlation",
        "idx_mcp_operation_audit_job",
        "idx_mcp_operation_audit_actor",
        "idx_mcp_operation_audit_identity",
        "idx_mcp_operation_audit_principal",
        "idx_mcp_operation_audit_status",
    }.issubset(indexes)


def test_unified_mcp_audit_migration_preserves_legacy_rows_without_guessing_links(
    tmp_path: Path,
) -> None:
    database = Database("sqlite:///:memory:")
    through_104 = _migrations_through(tmp_path, "104")
    Migrator(
        database,
        through_104,
        migrator_build="unified-audit-predecessor",
        include_schema_contract=True,
    ).run()
    timestamp = "2026-08-12T00:00:00+00:00"
    database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('legacy-audit-user', 'legacy-audit-user', 'Legacy Audit User',
                'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_session
          (id, project_code, created_at, updated_at, source_channel,
           source_connector_id, external_conversation_id, requester_id, session_key)
        values ('legacy-audit-session', 'default', ?, ?, 'test', 'connector-test',
                'conversation', 'legacy-audit-user', 'legacy-audit-session')
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, project_code, status, created_at,
           source_channel, source_connector_id, requester_id, internal_user_id)
        values ('legacy-audit-job', 'legacy-audit-session', 'legacy-audit-job',
                'default', 'SUCCEEDED', ?, 'test', 'connector-test',
                'legacy-audit-user', 'legacy-audit-user')
        """,
        (timestamp,),
    )
    database.execute(
        """
        insert into agent_tool_call
          (id, job_id, tool_name, request_payload, response_summary, status,
           duration_ms, risk_level, created_at)
        values ('same-name-unrelated-tool-call', 'legacy-audit-job',
                'ones_work_item_search', '{}', '{}', 'SUCCEEDED', 1, 'low', ?)
        """,
        (timestamp,),
    )
    database.execute(
        """
        insert into mcp_operation_audit
          (id, correlation_id, job_id, session_id, principal_jti,
           actor_user_id, actor_type, server_code, tool_identifier, operation,
           event_kind, attempt, status, payload_schema_version,
           tool_request_json, provider_request_json, provider_response_json,
           tool_response_json, created_at)
        values ('legacy-ones-audit', 'legacy-correlation', 'legacy-audit-job',
                'legacy-audit-session', 'legacy-jti', 'legacy-audit-user', 'user',
                'ones-mcp', 'ones_work_item_search', 'read', 'TOOL', 0,
                'SUCCEEDED', 1, '{"keyword":"legacy"}', '{}', '{}',
                '{"total":1}', ?)
        """,
        (timestamp,),
    )

    upgraded = Migrator(
        database,
        _migrations_through(tmp_path, "118"),
        migrator_build="unified-audit-upgrade",
    ).run()

    assert upgraded.applied == (
        "105", "106", "107", "108", "109", "110", "111", "112", "113", "114", "115", "116", "117", "118"
    )
    row = database.execute_one("select * from mcp_operation_audit where id = 'legacy-ones-audit'")
    assert row is not None
    assert row["mcp_call_id"] == "legacy:legacy-ones-audit"
    assert row["legacy_link_status"] == "LEGACY_UNLINKED"
    assert row["agent_tool_call_id"] is None
    assert json.loads(str(row["business_request_json"])) == {"keyword": "legacy"}
    assert json.loads(str(row["business_response_json"])) == {"total": 1}


def _convert_fresh_baseline_to_legacy_ledger(database: Database) -> dict[str, object]:
    manifest = load_legacy_manifest(default_migrations_dir() / LEGACY_MANIFEST_FILENAME)
    applied_at = datetime.now(UTC).isoformat()
    with database.unit_of_work():
        database.execute("delete from schema_migration")
        database.execute("delete from schema_baseline_adoption")
        for artifact in manifest["catalog"]:
            database.execute(
                """
                insert into schema_migration
                  (version, name, checksum, applied_at, duration_ms, migrator_build)
                values (?, ?, ?, ?, 0, 'legacy-fixture')
                """,
                (
                    artifact["version"],
                    artifact["name"],
                    artifact["checksum"],
                    applied_at,
                ),
            )
    return manifest


def _baseline_only_migrations(tmp_path: Path) -> Path:
    source = default_migrations_dir()
    target = tmp_path / "baseline-only"
    target.mkdir()
    (target / "100_baseline_v1.sql").write_bytes((source / "100_baseline_v1.sql").read_bytes())
    (target / LEGACY_MANIFEST_FILENAME).write_bytes(
        (source / LEGACY_MANIFEST_FILENAME).read_bytes()
    )
    return target


def _migrations_through(tmp_path: Path, head: str) -> Path:
    source = default_migrations_dir()
    target = tmp_path / f"migrations-through-{head}"
    target.mkdir()
    for artifact in load_migration_catalog(source):
        if int(artifact.version) <= int(head):
            (target / artifact.name).write_bytes(artifact.path.read_bytes())
    (target / LEGACY_MANIFEST_FILENAME).write_bytes(
        (source / LEGACY_MANIFEST_FILENAME).read_bytes()
    )
    return target


def _record_contract_approval(database: Database) -> None:
    database.execute(
        """
        insert into schema_consolidation_contract_approval
          (contract_version, expected_head, target_label, evidence_digest,
           backup_reference_digest, parity_verified, workflow_parity_verified,
           zero_legacy_access_verified, retry_recovery_cycle_observed,
           production_release_cycle_observed, retention_verified,
           approvals_verified, approved_at)
        values ('103', '102', 'test-target', ?, ?, 1, 1, 1, 1, 1, 1, 1,
                '2026-08-12T00:00:00Z')
        """,
        ("a" * 64, "b" * 64),
    )


def test_existing_database_contract_requires_separate_approval(tmp_path: Path) -> None:
    database = Database("sqlite:///:memory:")
    through_102 = _migrations_through(tmp_path, "102")
    Migrator(database, through_102, migrator_build="expand-build").run()

    with pytest.raises(MigrationDefinitionError, match="separately authorized"):
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="contract-without-approval",
            include_schema_contract=True,
        ).run()

    assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "102"
    assert "user_message" in {
        row["name"] for row in database.execute("pragma table_info(agent_job)")
    }

    _record_contract_approval(database)
    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="contract-approved",
        include_schema_contract=True,
    ).run()

    assert result.applied == (
        "103", "104", "105", "106", "107", "108", "109", "110", "111", "112", "113", "114", "115", "116", "117", "118", "119"
    )
    assert "user_message" not in {
        row["name"] for row in database.execute("pragma table_info(agent_job)")
    }
    assert database.execute_one(
        """
        select name from sqlite_master
         where type = 'table' and name = 'job_dispatch_cutover_quarantine'
        """
    ) == {"name": "job_dispatch_cutover_quarantine"}


def test_contract_approval_does_not_bypass_live_parity(tmp_path: Path) -> None:
    database = Database("sqlite:///:memory:")
    through_102 = _migrations_through(tmp_path, "102")
    Migrator(database, through_102, migrator_build="expand-build").run()
    database.execute(
        """
        insert into agent_session
          (id, project_code, created_at, updated_at, source_channel,
           source_connector_id, external_conversation_id, requester_id, session_key)
        values ('blocked-session', 'default', '2026-08-12T00:00:00Z',
                '2026-08-12T00:00:00Z', 'debug_api', 'connector-debug-api',
                '', '', 'blocked-session')
        """
    )
    _record_contract_approval(database)

    with pytest.raises(MigrationDefinitionError, match="live parity"):
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="contract-parity-blocked",
            include_schema_contract=True,
        ).run()

    assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "102"


def test_contract_approval_does_not_bypass_pending_outbox(tmp_path: Path) -> None:
    database = Database("sqlite:///:memory:")
    through_102 = _migrations_through(tmp_path, "102")
    Migrator(database, through_102, migrator_build="expand-build").run()
    timestamp = "2026-08-12T00:00:00Z"
    database.execute(
        """
        insert into agent_session
          (id, project_code, created_at, updated_at, source_channel,
           source_connector_id, external_conversation_id, requester_id, session_key)
        values ('contract-session', 'default', ?, ?, 'test', 'connector-test',
                'conversation', 'requester', 'contract-session')
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, project_code, status, created_at,
           source_channel, source_connector_id, requester_id)
        values ('contract-job', 'contract-session', 'contract-job', 'default',
                'SUCCEEDED', ?, 'test', 'connector-test', 'requester')
        """,
        (timestamp,),
    )
    database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('contract-message', 'contract-session', 'contract-job', 'user',
                'synthetic', ?, 1)
        """,
        (timestamp,),
    )
    database.execute(
        "update agent_job set input_message_id = 'contract-message' where id = 'contract-job'"
    )
    database.execute(
        """
        insert into job_dispatch_outbox
          (id, event_key, idempotency_key, job_id, correlation_id, status,
           next_attempt_at, created_at, updated_at)
        values ('contract-outbox', 'contract-outbox', 'contract-outbox',
                'contract-job', 'contract', 'PENDING', ?, ?, ?)
        """,
        (timestamp, timestamp, timestamp),
    )
    _record_contract_approval(database)

    with pytest.raises(MigrationDefinitionError, match="pending operational"):
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="contract-outbox-blocked",
            include_schema_contract=True,
        ).run()

    assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "102"


def test_exact_legacy_042_adoption_preserves_schema_data_and_is_idempotent(
    tmp_path: Path,
) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        migrations,
        migrator_build="baseline-fixture",
    ).run()
    database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('adoption-user', 'adoption-user', 'Adoption User', 'enabled', ?, ?)
        """,
        ("2026-08-11T00:00:00Z", "2026-08-11T00:00:00Z"),
    )
    _convert_fresh_baseline_to_legacy_ledger(database)

    first = Migrator(
        database,
        migrations,
        migrator_build="adoption-test",
    ).run()
    second = Migrator(
        database,
        migrations,
        migrator_build="adoption-repeat-test",
    ).run()

    assert first.head == "100"
    assert first.baselined == 1
    assert first.applied == ()
    assert second.baselined == 0
    assert second.applied == ()
    assert database.execute_one("select username from app_user where id = 'adoption-user'") == {
        "username": "adoption-user"
    }
    assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "100"
    assert len(SchemaMigrationLedger(database).read_adoptions()) == 1
    assert database.execute("pragma foreign_key_check") == []
    database.close()


def test_baseline_adoption_preflight_is_read_only_and_returns_safe_evidence(
    tmp_path: Path,
) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        migrations,
        migrator_build="baseline-fixture",
    ).run()
    database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('preflight-user', 'preflight-user', 'must-not-appear', 'enabled', ?, ?)
        """,
        ("2026-08-11T00:00:00Z", "2026-08-11T00:00:00Z"),
    )
    _convert_fresh_baseline_to_legacy_ledger(database)
    database.execute("drop table schema_baseline_adoption")
    before_ledger = SchemaMigrationLedger(database).read_records()

    report = BaselineAdoptionInspector(
        database,
        migrations,
    ).preflight(migrator_build="build-2026.08.11")

    assert report["status"] == "ready-for-adoption"
    assert report["source_head"] == "042"
    assert report["target_baseline"] == "100"
    assert report["migrator_build"] == "build-2026.08.11"
    assert report["retained_data_counts"]["app_user"] == 1
    assert len(report["retained_data_digest"]) == 64
    assert report["runtime_config_summary"]["revision"] == 0
    assert SchemaMigrationLedger(database).read_records() == before_ledger
    assert (
        database.execute_one(
            "select name from sqlite_master where type = 'table' and name = 'schema_baseline_adoption'"
        )
        is None
    )
    assert "must-not-appear" not in json.dumps(report, ensure_ascii=False)
    database.close()


def test_baseline_adoption_verify_checks_marker_counts_config_and_readiness(
    tmp_path: Path,
) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        migrations,
        migrator_build="baseline-fixture",
    ).run()
    _convert_fresh_baseline_to_legacy_ledger(database)
    Migrator(
        database,
        migrations,
        migrator_build="build-2026.08.11",
    ).run()
    before_ledger = SchemaMigrationLedger(database).read_records()
    before_adoptions = SchemaMigrationLedger(database).read_adoptions()

    report = BaselineAdoptionInspector(
        database,
        migrations,
    ).verify(expected_migrator_build="build-2026.08.11")

    assert report["status"] == "adoption-verified"
    assert report["schema_head"] == "100"
    assert report["marker_count"] == 1
    assert report["adoption_metadata_count"] == 1
    assert report["runtime_config_summary"] == {
        "definition_count": 0,
        "value_count": 0,
        "secret_count": 0,
        "revision": 0,
        "digest": report["runtime_config_summary"]["digest"],
    }
    assert report["readiness"] == {
        "schema_head_current": True,
        "adoption_verified": True,
        "business_start_gate": "schema-verified",
    }
    assert SchemaMigrationLedger(database).read_records() == before_ledger
    assert SchemaMigrationLedger(database).read_adoptions() == before_adoptions
    database.close()


def test_failed_adoption_acceptance_allows_marker_only_rollback(tmp_path: Path) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    database = Database("sqlite:///:memory:")
    Migrator(database, migrations, migrator_build="fixture").run()
    _convert_fresh_baseline_to_legacy_ledger(database)
    Migrator(
        database,
        migrations,
        migrator_build="build-2026.08.11",
    ).run()
    database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('unexpected-write', 'unexpected-write', 'Unexpected', 'enabled', ?, ?)
        """,
        ("2026-08-11T00:00:00Z", "2026-08-11T00:00:00Z"),
    )

    with pytest.raises(MigrationDefinitionError, match="counts changed"):
        BaselineAdoptionInspector(
            database,
            migrations,
        ).verify(expected_migrator_build="build-2026.08.11")

    assert (
        BaselineAdoptionRollback(
            database,
            migrations,
            migrator_build="rollback-test",
        ).run()
        == "042"
    )
    assert SchemaMigrationLedger(database).read_records()[-1]["version"] == "042"
    assert database.execute_one("select username from app_user where id = 'unexpected-write'") == {
        "username": "unexpected-write"
    }
    database.close()


def test_final_schema_comment_manifest_covers_every_owned_table_and_column() -> None:
    database = Database("sqlite:///:memory:")
    catalog = load_migration_catalog(default_migrations_dir())
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="schema-comment-coverage-test",
    ).run()

    table_pattern = re.compile(
        r"COMMENT\s+ON\s+TABLE\s+(?:public\.)?\"?([a-z0-9_]+)\"?\s+IS\s+"
        r"'((?:''|[^'])*)'\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    column_pattern = re.compile(
        r"COMMENT\s+ON\s+COLUMN\s+(?:public\.)?\"?([a-z0-9_]+)\"?\."
        r"\"?([a-z0-9_]+)\"?\s+IS\s+'((?:''|[^'])*)'\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    table_comments: dict[str, str] = {}
    column_comments: dict[tuple[str, str], str] = {}
    for artifact in catalog:
        for match in table_pattern.finditer(artifact.sql):
            table_comments[match.group(1)] = match.group(2).replace("''", "'")
        for match in column_pattern.finditer(artifact.sql):
            column_comments[(match.group(1), match.group(2))] = match.group(3).replace("''", "'")

    owned_tables = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'table'")
        if str(row["name"]) not in {"schema_migration", "schema_baseline_adoption"}
        and not str(row["name"]).startswith("sqlite_")
    }
    owned_columns = {
        (table, str(row["name"]))
        for table in owned_tables
        for row in database.execute(f'pragma table_info("{table}")')
    }

    assert owned_tables - table_comments.keys() == set()
    assert owned_columns - column_comments.keys() == set()
    assert all(re.search(r"[\u3400-\u9fff]", table_comments[table]) for table in owned_tables)
    assert all(re.search(r"[\u3400-\u9fff]", column_comments[column]) for column in owned_columns)
    assert len(owned_tables) == 124
    assert len(owned_columns) == 1616
    database.close()


def test_baseline_static_gate_excludes_retired_schema_data_and_plaintext() -> None:
    sql = (default_migrations_dir() / "100_baseline_v1.sql").read_text(encoding="utf-8")
    executable_sql = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    retired_names = {
        "api_capability",
        "api_connection",
        "api_handler",
        "external_api_credential",
        "handler_installation",
        "permission_policy",
        "platform_access_grant",
        "runtime_snapshot_generation",
        "tool_definition",
    }

    assert not re.search(
        r"^\s*(?:insert\s+into|update\s+\w+\s+set|delete\s+from)\b",
        executable_sql,
        re.IGNORECASE | re.MULTILINE,
    )
    assert not re.search(r"\badmin\b|111111111111", executable_sql, re.IGNORECASE)
    assert not re.search(r"(?:password|token|secret)\s*=", executable_sql, re.IGNORECASE)
    for retired_name in retired_names:
        assert not re.search(rf"\b{retired_name}\b", executable_sql, re.IGNORECASE)


def test_partial_legacy_head_and_checksum_drift_fail_closed() -> None:
    partial = Database("sqlite:///:memory:")
    Migrator(partial, default_migrations_dir(), migrator_build="fixture").run()
    manifest = _convert_fresh_baseline_to_legacy_ledger(partial)
    partial.execute("delete from schema_migration where version = '042'")
    with pytest.raises(MigrationDefinitionError, match="exact head 042"):
        Migrator(partial, default_migrations_dir(), migrator_build="partial").run()
    partial.close()

    drifted = Database("sqlite:///:memory:")
    Migrator(drifted, default_migrations_dir(), migrator_build="fixture").run()
    _convert_fresh_baseline_to_legacy_ledger(drifted)
    drifted.execute(
        "update schema_migration set checksum = ? where version = '042'",
        ("0" * 64,),
    )
    with pytest.raises(MigrationDefinitionError, match="checksum or identity"):
        Migrator(drifted, default_migrations_dir(), migrator_build="drift").run()
    assert manifest["legacy_head"] == "042"
    drifted.close()


def test_schema_drift_rejects_legacy_adoption_and_rollback_preserves_schema(
    tmp_path: Path,
) -> None:
    migrations = _baseline_only_migrations(tmp_path)
    drifted = Database("sqlite:///:memory:")
    Migrator(drifted, migrations, migrator_build="fixture").run()
    _convert_fresh_baseline_to_legacy_ledger(drifted)
    drifted.execute("drop index idx_agent_job_status")
    with pytest.raises(MigrationDefinitionError, match="schema fingerprint"):
        Migrator(drifted, migrations, migrator_build="drift").run()
    drifted.close()

    adopted = Database("sqlite:///:memory:")
    Migrator(adopted, migrations, migrator_build="fixture").run()
    _convert_fresh_baseline_to_legacy_ledger(adopted)
    Migrator(adopted, migrations, migrator_build="adopt").run()
    before_tables = adopted.execute_one(
        """
        select count(*) as count from sqlite_master
         where type = 'table'
           and name not in ('schema_migration', 'schema_baseline_adoption')
           and name not like 'sqlite_%'
        """
    )

    restored_head = BaselineAdoptionRollback(
        adopted,
        migrations,
        migrator_build="rollback",
    ).run()

    assert restored_head == "042"
    assert SchemaMigrationLedger(adopted).read_records()[-1]["version"] == "042"
    assert SchemaMigrationLedger(adopted).read_adoptions() == []
    assert (
        adopted.execute_one(
            """
        select count(*) as count from sqlite_master
         where type = 'table'
           and name not in ('schema_migration', 'schema_baseline_adoption')
           and name not like 'sqlite_%'
        """
        )
        == before_tables
    )
    adopted.close()


def test_migrator_rolls_back_entire_failed_version_and_ledger_record(
    tmp_path: Path,
) -> None:
    (tmp_path / "001_first.sql").write_text(
        "create table first_table (id integer primary key);\n",
        encoding="utf-8",
    )
    (tmp_path / "002_broken.sql").write_text(
        """
        create table must_rollback (id integer primary key);
        insert into table_that_does_not_exist (id) values (1);
        """,
        encoding="utf-8",
    )
    database = Database("sqlite:///:memory:")

    with pytest.raises(MigrationExecutionError, match="002 failed"):
        Migrator(database, tmp_path, migrator_build="test-build").run()

    assert database.execute_one(
        "select name from sqlite_master where type='table' and name='first_table'"
    )
    assert (
        database.execute_one(
            "select name from sqlite_master where type='table' and name='must_rollback'"
        )
        is None
    )
    assert [row["version"] for row in SchemaMigrationLedger(database).list_records()] == ["001"]


def test_migrator_rejects_applied_checksum_drift_before_later_versions(
    tmp_path: Path,
) -> None:
    first = tmp_path / "001_first.sql"
    first.write_text(
        "create table first_table (id integer primary key);\n",
        encoding="utf-8",
    )
    database = Database("sqlite:///:memory:")
    Migrator(database, tmp_path, migrator_build="test-build").run()
    first.write_text(
        "create table first_table (id integer primary key, changed text);\n",
        encoding="utf-8",
    )
    (tmp_path / "002_later.sql").write_text(
        "create table must_not_apply (id integer primary key);\n",
        encoding="utf-8",
    )

    with pytest.raises(MigrationDefinitionError, match="checksum"):
        Migrator(database, tmp_path, migrator_build="test-build").run()

    assert (
        database.execute_one(
            "select name from sqlite_master where type='table' and name='must_not_apply'"
        )
        is None
    )


def test_migrator_cli_redacts_unexpected_database_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_without_exposing_connection(self: Migrator) -> None:
        raise RuntimeError("postgresql://user:must-not-leak@private-db.internal/database")

    monkeypatch.setattr(Migrator, "run", fail_without_exposing_connection)

    assert migrate_cli.main(["--build", "test-build"]) == 1
    output = capsys.readouterr().out
    assert output == ("MIGRATION_FAILED: database unavailable or migration lock failed\n")
    assert "must-not-leak" not in output
    assert "private-db.internal" not in output


def test_baseline_adoption_cli_redacts_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_without_exposing_connection(
        self: BaselineAdoptionInspector,
        *,
        migrator_build: str,
    ) -> dict[str, object]:
        raise RuntimeError("postgresql://user:must-not-leak@private-db.internal/database")

    monkeypatch.setattr(BaselineAdoptionInspector, "preflight", fail_without_exposing_connection)

    assert baseline_adoption_cli.main(["preflight", "--build", "build-2026.08.11"]) == 1
    output = capsys.readouterr().out
    assert output == (
        "BASELINE_ADOPTION_PREFLIGHT_FAILED: database unavailable or verification failed\n"
    )
    assert "must-not-leak" not in output
    assert "private-db.internal" not in output


def test_schema_head_validator_is_read_only_and_rejects_missing_ledger() -> None:
    database = Database("sqlite:///:memory:")

    with pytest.raises(
        SchemaHeadError,
        match="ledger is missing; expected head 119",
    ):
        SchemaHeadValidator(
            database,
            default_migrations_dir(),
        ).require_current()

    assert (
        database.execute_one(
            """
        select name
          from sqlite_master
         where type = 'table' and name = 'schema_migration'
        """
        )
        is None
    )
    assert (
        database.execute_one(
            """
        select name
          from sqlite_master
         where type = 'table' and name = 'agent_job'
        """
        )
        is None
    )


def test_schema_head_validator_accepts_exact_head_and_rejects_drift(
    tmp_path: Path,
) -> None:
    def _write(name: str, sql: str) -> None:
        (tmp_path / name).write_text(sql + "\n", encoding="utf-8")

    _write("001_first.sql", "create table first_table (id integer primary key);")
    database = Database("sqlite:///:memory:")
    Migrator(database, tmp_path, migrator_build="test-build").run()

    assert SchemaHeadValidator(database, tmp_path).require_current() == "001"

    _write(
        "001_first.sql",
        "create table first_table (id integer primary key, changed text);",
    )
    with pytest.raises(SchemaHeadError, match="checksum"):
        SchemaHeadValidator(database, tmp_path).require_current()


def test_schema_head_validator_rejects_database_behind_code_head(
    tmp_path: Path,
) -> None:
    first = tmp_path / "001_first.sql"
    first.write_text(
        "create table first_table (id integer primary key);\n",
        encoding="utf-8",
    )
    database = Database("sqlite:///:memory:")
    Migrator(database, tmp_path, migrator_build="test-build").run()
    (tmp_path / "002_later.sql").write_text(
        "create table later_table (id integer primary key);\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SchemaHeadError,
        match="schema head is 001; expected 002",
    ):
        SchemaHeadValidator(database, tmp_path).require_current()


@pytest.mark.parametrize(
    "factory",
    [
        lambda settings: build_api_container(settings),
        lambda settings: build_worker_container(
            settings,
            service_name="agent-worker",
        ),
        lambda settings: build_worker_container(
            settings,
            service_name="job-dispatch-worker",
        ),
        lambda settings: build_worker_container(
            settings,
            service_name="webhook-worker",
        ),
        lambda settings: build_worker_container(
            settings,
            service_name="channel-dispatch-worker",
        ),
        lambda settings: build_worker_container(
            settings,
            service_name="file-worker",
        ),
    ],
)
def test_business_runtime_startup_rejects_missing_head_without_migrating(
    tmp_path: Path,
    factory: Callable[[Settings], object],
) -> None:
    database_path = tmp_path / f"{uuid.uuid4().hex}.db"
    settings = Settings(database_dsn=f"sqlite:///{database_path}")

    with pytest.raises(SchemaHeadError, match="ledger is missing"):
        factory(settings)

    database = Database(settings.database_dsn)
    try:
        assert (
            database.execute_one(
                """
            select name
              from sqlite_master
             where type = 'table' and name = 'schema_migration'
            """
            )
            is None
        )
        assert (
            database.execute_one(
                """
            select name
              from sqlite_master
             where type = 'table' and name = 'agent_job'
            """
            )
            is None
        )
    finally:
        database.close()


@pytest.mark.parametrize(
    "name",
    [
        "1_too_short.sql",
        "001-UPPER.sql",
        "001missing.sql",
        "001_.sql",
    ],
)
def test_migration_catalog_rejects_noncanonical_names(
    tmp_path: Path,
    name: str,
) -> None:
    (tmp_path / name).write_text("select 1;\n", encoding="utf-8")

    with pytest.raises(MigrationDefinitionError, match="Invalid migration filename"):
        load_migration_catalog(tmp_path)
