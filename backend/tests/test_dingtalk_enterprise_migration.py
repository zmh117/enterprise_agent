from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import MigrationExecutionError, Migrator
from app.shared.schema_baseline import LEGACY_MANIFEST_FILENAME


TIMESTAMP = "2026-08-03T00:00:00+00:00"


def _catalog_through(tmp_path: Path, head: int) -> Path:
    source = default_migrations_dir()
    target = tmp_path / f"migrations-through-{head}"
    target.mkdir()
    shutil.copy2(source / LEGACY_MANIFEST_FILENAME, target / LEGACY_MANIFEST_FILENAME)
    for path in source.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= head:
            shutil.copy2(path, target / path.name)
    return target


def _seed_enterprise_and_users(database: Database) -> None:
    for user_id in ("enterprise-admin", "user-a", "user-b"):
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values (?, ?, ?, 'enabled', ?, ?)
            """,
            (user_id, user_id, user_id, TIMESTAMP, TIMESTAMP),
        )
    database.execute(
        """
        insert into dingtalk_enterprise
          (id, name, corp_id, status, verification_event_id, verified_at,
           created_by, created_at, updated_at)
        values ('enterprise-a', '企业 A', 'corp-a', 'ACTIVE', 'event-a', ?,
                'enterprise-admin', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )


def test_027_fresh_schema_enforces_enterprise_and_identity_invariants() -> None:
    database = Database("sqlite:///:memory:")
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="dingtalk-enterprise-test",
        ).run()
        assert result.head == "130"
        _seed_enterprise_and_users(database)
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                insert into dingtalk_enterprise
                  (id, name, corp_id, status, verification_event_id, verified_at,
                   created_by, created_at, updated_at)
                values ('enterprise-b', '企业 B', 'corp-a', 'ACTIVE', 'event-b', ?,
                        'enterprise-admin', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
        database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               connector_id, display_name, status, metadata_json,
               dingtalk_enterprise_id, created_at, updated_at)
            values ('identity-a', 'user-a', 'dingtalk', 'enterprise-a', 'staff-a',
                    '', 'Nick', 'enabled', '{}', 'enterprise-a', ?, ?)
            """,
            (TIMESTAMP, TIMESTAMP),
        )
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                insert into user_external_identity
                  (id, user_id, provider, tenant_code, external_subject_id,
                   connector_id, display_name, status, metadata_json,
                   dingtalk_enterprise_id, created_at, updated_at)
                values ('identity-same-staff', 'enterprise-admin', 'dingtalk',
                        'enterprise-a', 'staff-a', '', 'Other', 'enabled', '{}',
                        'enterprise-a', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                insert into user_external_identity
                  (id, user_id, provider, tenant_code, external_subject_id,
                   connector_id, display_name, status, metadata_json,
                   dingtalk_enterprise_id, created_at, updated_at)
                values ('identity-same-user', 'user-a', 'dingtalk',
                        'enterprise-a', 'staff-b', '', 'Other', 'enabled', '{}',
                        'enterprise-a', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )
    finally:
        database.close()


def test_130_upgrades_clean_129_database_and_restores_both_indexes(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'clean-129.db'}")
    try:
        Migrator(
            database,
            _catalog_through(tmp_path, 129),
            migrator_build="dingtalk-index-before",
        ).run()

        assert {
            str(row["name"])
            for row in database.execute("pragma index_list(user_external_identity)")
        }.isdisjoint(
            {
                "idx_dingtalk_identity_enterprise_subject",
                "idx_dingtalk_identity_user_enterprise_current",
            }
        )

        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="dingtalk-index-after",
        ).run()

        assert result.head == "130"
        assert result.applied == ("130",)
        assert {
            "idx_dingtalk_identity_enterprise_subject",
            "idx_dingtalk_identity_user_enterprise_current",
        }.issubset(
            {
                str(row["name"])
                for row in database.execute("pragma index_list(user_external_identity)")
            }
        )
    finally:
        database.close()


@pytest.mark.parametrize("duplicate_kind", ["enterprise_subject", "user_enterprise"])
def test_130_fails_closed_without_mutating_duplicate_129_data(
    tmp_path: Path,
    duplicate_kind: str,
) -> None:
    database = Database(f"sqlite:///{tmp_path / f'duplicate-{duplicate_kind}.db'}")
    try:
        Migrator(
            database,
            _catalog_through(tmp_path, 129),
            migrator_build="dingtalk-duplicate-before",
        ).run()
        _seed_enterprise_and_users(database)
        if duplicate_kind == "enterprise_subject":
            identities = (
                ("identity-a", "user-a", "tenant-a", "staff-a"),
                ("identity-b", "user-b", "tenant-b", "staff-a"),
            )
        else:
            identities = (
                ("identity-a", "user-a", "tenant-a", "staff-a"),
                ("identity-b", "user-a", "tenant-a", "staff-b"),
            )
        for identity_id, user_id, tenant_code, subject_id in identities:
            database.execute(
                """
                insert into user_external_identity
                  (id, user_id, provider, tenant_code, external_subject_id,
                   connector_id, display_name, status, metadata_json,
                   dingtalk_enterprise_id, created_at, updated_at)
                values (?, ?, 'dingtalk', ?, ?, '', 'Nick', 'enabled', '{}',
                        'enterprise-a', ?, ?)
                """,
                (
                    identity_id,
                    user_id,
                    tenant_code,
                    subject_id,
                    TIMESTAMP,
                    TIMESTAMP,
                ),
            )

        with pytest.raises(MigrationExecutionError, match="Migration 130 failed"):
            Migrator(
                database,
                default_migrations_dir(),
                migrator_build="dingtalk-duplicate-after",
            ).run()

        assert database.execute_one(
            "select version from schema_migration order by version desc limit 1"
        ) == {"version": "129"}
        assert database.execute_one("select count(*) as count from user_external_identity") == {
            "count": 2
        }
        assert {
            str(row["name"])
            for row in database.execute("pragma index_list(user_external_identity)")
        }.isdisjoint(
            {
                "idx_dingtalk_identity_enterprise_subject",
                "idx_dingtalk_identity_user_enterprise_current",
            }
        )
    finally:
        database.close()


def test_baseline_contains_dingtalk_enterprise_schema_without_fixture_data() -> None:
    sql = (default_migrations_dir() / "100_baseline_v1.sql").read_text(encoding="utf-8")
    repair_sql = (default_migrations_dir() / "130_restore_dingtalk_identity_indexes.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE dingtalk_enterprise" in sql
    assert "CREATE TABLE dingtalk_identity_application_observation" in sql
    assert "INSERT INTO dingtalk_enterprise" not in sql.upper()
    assert "idx_dingtalk_identity_enterprise_subject" in repair_sql
    assert "idx_dingtalk_identity_user_enterprise_current" in repair_sql
    assert repair_sql.count("CREATE UNIQUE INDEX IF NOT EXISTS") == 2
