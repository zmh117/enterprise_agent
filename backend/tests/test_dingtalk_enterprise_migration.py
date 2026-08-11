from __future__ import annotations

import sqlite3

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


def test_027_fresh_schema_enforces_enterprise_and_identity_invariants() -> None:
    database = Database("sqlite:///:memory:")
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="dingtalk-enterprise-test",
        ).run()
        assert result.head == "038"
        timestamp = "2026-08-03T00:00:00+00:00"
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('enterprise-admin', 'enterprise-admin', 'Admin',
                    'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into dingtalk_enterprise
              (id, name, corp_id, status, verification_event_id, verified_at,
               created_by, created_at, updated_at)
            values ('enterprise-a', '企业 A', 'corp-a', 'ACTIVE', 'event-a', ?,
                    'enterprise-admin', ?, ?)
            """,
            (timestamp, timestamp, timestamp),
        )
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                insert into dingtalk_enterprise
                  (id, name, corp_id, status, verification_event_id, verified_at,
                   created_by, created_at, updated_at)
                values ('enterprise-b', '企业 B', 'corp-a', 'ACTIVE', 'event-b', ?,
                        'enterprise-admin', ?, ?)
                """,
                (timestamp, timestamp, timestamp),
            )
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('user-a', 'user-a', 'User A', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
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
            (timestamp, timestamp),
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
                (timestamp, timestamp),
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
                (timestamp, timestamp),
            )
    finally:
        database.close()


def test_027_migration_contains_no_test_data_cleanup() -> None:
    sql = (
        default_migrations_dir()
        / "027_dingtalk_enterprise_identity_observations.sql"
    ).read_text(encoding="utf-8").lower()

    assert "delete from" not in sql
    assert "drop table" not in sql
    assert "drop column" not in sql
