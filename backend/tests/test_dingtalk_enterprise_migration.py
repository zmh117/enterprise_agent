from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.modules.api_capability.infrastructure import ApiConnectionRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


def _published_connection(database: Database, *, actor_id: str) -> dict[str, object]:
    repository = ApiConnectionRepository(database)
    connection = repository.create(
        code="ones-migration-preservation",
        name="ONES Migration Preservation",
        provider="ones",
        origin={"scheme": "https", "host": "ones.example.test", "port": 443},
        authentication={
            "schema_version": 1,
            "login": {
                "method": "POST",
                "relative_path": "/project/api/project/auth/login",
                "email_field": "email",
                "password_field": "password",
            },
            "extract": {
                "token_path": "$.user.token",
                "user_id_path": "$.user.uuid",
                "display_name_path": "$.user.name",
                "teams_path": "$.teams",
                "team_id_field": "uuid",
                "team_name_field": "name",
            },
            "inject": {"header_name": "Ones-Auth-Token", "value_prefix": ""},
        },
        actor_id=actor_id,
    )
    draft = connection["draft"]
    repository.record_verification(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=actor_id,
        status="PASSED",
        checks={"login": "passed"},
    )
    return repository.publish(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=actor_id,
    )


def test_027_fresh_schema_enforces_enterprise_and_identity_invariants() -> None:
    database = Database("sqlite:///:memory:")
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="dingtalk-enterprise-test",
        ).run()
        assert result.head == "027"
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


def test_027_upgrade_preserves_ones_identity_credential_and_team_ids(
    tmp_path: Path,
) -> None:
    migrations_dir = default_migrations_dir()
    for path in migrations_dir.glob("*.sql"):
        if not path.name.startswith("027_"):
            shutil.copy2(path, tmp_path / path.name)
    database = Database("sqlite:///:memory:")
    try:
        before = Migrator(database, tmp_path, migrator_build="pre-027").run()
        assert before.head == "026"
        timestamp = "2026-08-03T00:00:00+00:00"
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('ones-user', 'ones-user', 'ONES User', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        published = _published_connection(database, actor_id="ones-user")
        database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               connector_id, display_name, status, metadata_json, revision,
               created_at, updated_at)
            values ('ones-identity', 'ones-user', 'ones', 'ones', 'ones-subject',
                    '', 'ONES Owner', 'enabled', ?, 5, ?, ?)
            """,
            (
                json.dumps(
                    {
                        "default_team_id": "team-a",
                        "team_uuids": ["team-a", "team-b"],
                    }
                ),
                timestamp,
                timestamp,
            ),
        )
        database.execute(
            """
            insert into external_api_credential
              (id, user_id, external_identity_id, provider,
               connection_revision_id, token_ciphertext, encryption_key_id,
               status, revision, last_error_code, verified_at, created_at, updated_at)
            values ('credential-a', 'ones-user', 'ones-identity', 'ones', ?,
                    'ciphertext-preserved', 'key-a', 'ACTIVE', 7, '', ?, ?, ?)
            """,
            (published["id"], timestamp, timestamp, timestamp),
        )

        shutil.copy2(
            migrations_dir / "027_dingtalk_enterprise_identity_observations.sql",
            tmp_path / "027_dingtalk_enterprise_identity_observations.sql",
        )
        upgraded = Migrator(database, tmp_path, migrator_build="upgrade-027").run()

        assert upgraded.applied == ("027",)
        identity = database.execute_one(
            "select * from user_external_identity where id = 'ones-identity'"
        )
        credential = database.execute_one(
            "select * from external_api_credential where id = 'credential-a'"
        )
        assert identity is not None
        assert credential is not None
        assert identity["external_subject_id"] == "ones-subject"
        assert identity["status"] == "enabled"
        assert identity["revision"] == 5
        assert json.loads(identity["metadata_json"]) == {
            "default_team_id": "team-a",
            "team_uuids": ["team-a", "team-b"],
        }
        assert credential["token_ciphertext"] == "ciphertext-preserved"
        assert credential["status"] == "ACTIVE"
        assert credential["revision"] == 7
        assert credential["last_attempt_at"] is None
        assert credential["last_success_at"] is None
        assert credential["last_error_at"] is None
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
