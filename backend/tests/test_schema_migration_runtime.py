from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable
from pathlib import Path
import shutil
import uuid

import pytest

from app.bootstrap import build_api_container, build_worker_container
from app.cli import migrate as migrate_cli
from app.modules.internal_api_platform.app import build_service
from app.modules.local_internal_api_platform.app import create_app as create_local_tools_app
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import (
    LEGACY_BASELINE_HEAD,
    MigrationDefinitionError,
    MigrationExecutionError,
    Migrator,
    SchemaMigrationLedger,
    SchemaHeadError,
    SchemaHeadValidator,
    legacy_baseline_artifacts,
    load_migration_catalog,
    migration_checksum,
    normalized_migration_sql,
)
from app.modules.identity.infrastructure import IdentityRepository


def test_repository_migration_catalog_has_unique_ordered_versions_and_checksums() -> None:
    catalog = load_migration_catalog(default_migrations_dir())

    assert len({item.version for item in catalog}) == len(catalog)
    assert len({item.name for item in catalog}) == len(catalog)
    assert [item.version for item in catalog][8:11] == ["009", "009a", "010"]
    assert catalog[-1].version == "033"
    assert all(len(item.checksum) == 64 for item in catalog)

    baseline = legacy_baseline_artifacts(catalog)
    assert baseline == tuple(artifact for artifact in catalog if artifact.version <= "018")
    assert baseline[-1].version == LEGACY_BASELINE_HEAD


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


def test_existing_schema_gets_atomic_compatible_checksum_baseline() -> None:
    database = Database("sqlite:///:memory:")
    database.run_migrations(default_migrations_dir())
    catalog = load_migration_catalog(default_migrations_dir())
    ledger = SchemaMigrationLedger(database)
    baseline = legacy_baseline_artifacts(catalog)

    inserted = ledger.baseline_legacy(catalog, migrator_build="test-build")
    records = ledger.list_records()

    assert inserted == len(baseline)
    assert [row["version"] for row in records] == [artifact.version for artifact in baseline]
    assert [row["checksum"] for row in records] == [artifact.checksum for artifact in baseline]
    assert ledger.baseline_legacy(catalog, migrator_build="other-build") == 0

    drifted = (
        replace(catalog[0], checksum="f" * 64),
        *catalog[1:],
    )
    with pytest.raises(MigrationDefinitionError, match="does not match"):
        ledger.baseline_legacy(drifted, migrator_build="test-build")


def test_compatibility_baseline_refuses_incomplete_schema_without_ledger_rows() -> None:
    database = Database("sqlite:///:memory:")
    database.execute_script((default_migrations_dir() / "001_initial_agent.sql").read_text())
    catalog = load_migration_catalog(default_migrations_dir())
    ledger = SchemaMigrationLedger(database)

    with pytest.raises(MigrationDefinitionError, match="missing"):
        ledger.baseline_legacy(catalog, migrator_build="test-build")

    assert ledger.list_records() == []


def test_one_shot_migrator_applies_fresh_database_and_is_idempotent() -> None:
    database = Database("sqlite:///:memory:")
    migrator = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="test-build",
    )

    first = migrator.run()
    second = migrator.run()

    assert first.head == "033"
    assert first.baselined == 0
    assert first.applied[-11:] == (
        "023",
        "024",
        "025",
        "026",
        "027",
        "028",
        "029",
        "030",
        "031",
        "032",
        "033",
    )
    assert second.head == "033"
    assert second.baselined == 0
    assert second.applied == ()
    assert len(SchemaMigrationLedger(database).list_records()) == len(
        load_migration_catalog(default_migrations_dir())
    )


def test_pre_028_backup_can_be_restored_and_reupgraded_without_data_loss(
    tmp_path: Path,
) -> None:
    migrations_dir = default_migrations_dir()
    pre_change_dir = tmp_path / "pre-change-migrations"
    pre_change_dir.mkdir()
    for path in migrations_dir.glob("*.sql"):
        if int(path.name[:3]) < 28:
            shutil.copy2(path, pre_change_dir / path.name)

    database_path = tmp_path / "runtime.db"
    backup_path = tmp_path / "runtime-pre-028.backup.db"
    database_dsn = f"sqlite:///{database_path}"
    database = Database(database_dsn)
    try:
        before = Migrator(
            database,
            pre_change_dir,
            migrator_build="pre-028-backup-rehearsal",
        ).run()
        assert before.head == "027"
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('backup-user', 'backup-user', 'Backup User', 'enabled',
                    '2026-08-06T00:00:00Z', '2026-08-06T00:00:00Z')
            """
        )
    finally:
        database.close()
    shutil.copy2(database_path, backup_path)

    upgraded = Database(database_dsn)
    try:
        result = Migrator(
            upgraded,
            migrations_dir,
            migrator_build="028-033-upgrade-rehearsal",
        ).run()
        assert result.applied == ("028", "029", "030", "031", "032", "033")
        assert upgraded.execute_one(
            "select username from app_user where id = 'backup-user'"
        ) == {"username": "backup-user"}
        assert upgraded.execute_one(
            """
            select name from sqlite_master
             where type = 'table' and name = 'builtin_tool_release'
            """
        ) == {"name": "builtin_tool_release"}
    finally:
        upgraded.close()

    shutil.copy2(backup_path, database_path)
    restored = Database(database_dsn)
    try:
        records = SchemaMigrationLedger(restored).list_records()
        assert records[-1]["version"] == "027"
        assert restored.execute_one(
            "select username from app_user where id = 'backup-user'"
        ) == {"username": "backup-user"}
        assert restored.execute_one(
            """
            select name from sqlite_master
             where type = 'table' and name = 'builtin_tool_release'
            """
        ) is None

        reapplied = Migrator(
            restored,
            migrations_dir,
            migrator_build="restored-028-033-reupgrade-rehearsal",
        ).run()
        assert reapplied.applied == ("028", "029", "030", "031", "032", "033")
        assert reapplied.head == "033"
        assert restored.execute_one(
            "select username from app_user where id = 'backup-user'"
        ) == {"username": "backup-user"}
    finally:
        restored.close()


def test_025_upgrade_preserves_existing_ones_identity_without_fabricating_credential(
    tmp_path: Path,
) -> None:
    migrations_dir = default_migrations_dir()
    for path in migrations_dir.glob("*.sql"):
        if path.name not in {
            "025_governed_api_capabilities.sql",
            "026_allow_plain_http_api_connections.sql",
            "027_dingtalk_enterprise_identity_observations.sql",
            "028_govern_builtin_readonly_tools.sql",
            "029_loki_global_resource_scope.sql",
            "030_builtin_tool_legacy_removal_gate.sql",
            "031_direct_agent_tool_snapshot.sql",
            "032_exact_builtin_tool_resource_reset.sql",
            "033_loki_scope_verification_per_draft.sql",
        }:
            shutil.copy2(path, tmp_path / path.name)

    database = Database("sqlite:///:memory:")
    try:
        before = Migrator(
            database,
            tmp_path,
            migrator_build="pre-governed-api-test",
        ).run()
        assert before.head == "024"
        timestamp = "2026-07-31T00:00:00+00:00"
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('legacy-ones-user', 'legacy-ones-user', 'Legacy ONES User',
                    'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               display_name, status, verified_at, metadata_json,
               created_at, updated_at)
            values ('legacy-ones-identity', 'legacy-ones-user', 'ones',
                    'ones', 'legacy-ones-subject', 'Legacy ONES',
                    'enabled', ?, '{}', ?, ?)
            """,
            (timestamp, timestamp, timestamp),
        )

        shutil.copy2(
            migrations_dir / "025_governed_api_capabilities.sql",
            tmp_path / "025_governed_api_capabilities.sql",
        )
        upgraded = Migrator(
            database,
            tmp_path,
            migrator_build="governed-api-upgrade-test",
        ).run()

        assert upgraded.head == "025"
        assert upgraded.applied == ("025",)
        identity = IdentityRepository(database).get_external_identity("legacy-ones-identity")
        assert identity["external_subject_id"] == "legacy-ones-subject"
        assert identity["status"] == "enabled"
        assert identity["credential_status"] == "missing"
        assert database.execute_one(
            """
                select count(*) as count
                  from external_api_credential
                 where user_id = 'legacy-ones-user'
                """
        ) == {"count": 0}
    finally:
        database.close()


def test_026_upgrade_renames_plain_http_authorization_without_data_loss(
    tmp_path: Path,
) -> None:
    migrations_dir = default_migrations_dir()
    for path in migrations_dir.glob("*.sql"):
        if path.name not in {
            "026_allow_plain_http_api_connections.sql",
            "027_dingtalk_enterprise_identity_observations.sql",
            "028_govern_builtin_readonly_tools.sql",
            "029_loki_global_resource_scope.sql",
            "030_builtin_tool_legacy_removal_gate.sql",
            "031_direct_agent_tool_snapshot.sql",
            "032_exact_builtin_tool_resource_reset.sql",
            "033_loki_scope_verification_per_draft.sql",
        }:
            shutil.copy2(path, tmp_path / path.name)

    database = Database("sqlite:///:memory:")
    try:
        before = Migrator(
            database,
            tmp_path,
            migrator_build="pre-plain-http-test",
        ).run()
        assert before.head == "025"
        database.execute(
            """
            insert into api_connection
              (id, code, name, provider, created_by, created_at, updated_at)
            values ('connection-http', 'ones-http', 'ONES HTTP', 'ones',
                    'test', '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z')
            """
        )
        database.execute(
            """
            insert into api_connection_draft
              (id, connection_id, origin_scheme, origin_host, origin_port,
               allow_insecure_local_http, content_hash, created_by, updated_by,
               created_at, updated_at)
            values ('draft-http', 'connection-http', 'http',
                    'ones.internal.example', 80, 1, ?, 'test', 'test',
                    '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z')
            """,
            ("a" * 64,),
        )

        shutil.copy2(
            migrations_dir / "026_allow_plain_http_api_connections.sql",
            tmp_path / "026_allow_plain_http_api_connections.sql",
        )
        upgraded = Migrator(
            database,
            tmp_path,
            migrator_build="plain-http-upgrade-test",
        ).run()

        assert upgraded.head == "026"
        assert upgraded.applied == ("026",)
        assert database.execute_one(
            """
            select allow_plain_http from api_connection_draft
             where id = 'draft-http'
            """
        ) == {"allow_plain_http": 1}
        columns = {
            str(row["name"]) for row in database.execute("pragma table_info(api_connection_draft)")
        }
        assert "allow_plain_http" in columns
        assert "allow_insecure_local_http" not in columns
    finally:
        database.close()


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


def test_schema_head_validator_is_read_only_and_rejects_missing_ledger() -> None:
    database = Database("sqlite:///:memory:")

    with pytest.raises(
        SchemaHeadError,
        match="ledger is missing; expected head 033",
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
            service_name="attachment-worker",
        ),
        lambda settings: build_service(settings),
        lambda settings: create_local_tools_app(settings),
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
