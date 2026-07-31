from __future__ import annotations

import hashlib

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


def _migrated_database() -> Database:
    database = Database("sqlite:///:memory:")
    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="governed-api-schema-test",
    ).run()
    assert result.head == "025"
    return database


def test_governed_api_schema_contains_separate_control_plane_aggregates() -> None:
    database = _migrated_database()
    try:
        tables = {
            str(row["name"])
            for row in database.execute("select name from sqlite_master where type = 'table'")
        }
        assert {
            "api_connection",
            "api_connection_draft",
            "api_connection_verification",
            "api_connection_revision",
            "api_authentication_profile",
            "api_authentication_profile_draft",
            "api_authentication_profile_revision",
            "api_capability",
            "api_handler",
            "api_capability_draft",
            "api_capability_verification",
            "api_capability_revision",
            "api_handler_revision",
            "api_compiled_mapping_plan",
            "api_capability_release",
            "external_api_credential",
            "external_api_verification_challenge",
            "agent_publication_api_capability",
            "business_application_publication_api_capability",
            "agent_job_external_subject",
            "agent_tool_call_api_provenance",
            "agent_tool_call_http_attempt",
        }.issubset(tables)
    finally:
        database.close()


def test_capability_identifier_and_release_constraints_fail_closed() -> None:
    database = _migrated_database()
    timestamp = "2026-07-31T00:00:00+00:00"
    try:
        with pytest.raises(Exception):
            database.execute(
                """
                insert into api_capability
                  (id, identifier, name, created_by, created_at, updated_at)
                values ('capability-invalid', 'ones.work_item.search',
                        'Invalid', 'test', ?, ?)
                """,
                (timestamp, timestamp),
            )
        database.execute(
            """
            insert into api_capability
              (id, identifier, name, created_by, created_at, updated_at)
            values ('capability-valid', 'cap__ones__work_item__search',
                    'Search', 'test', ?, ?)
            """,
            (timestamp, timestamp),
        )
        with pytest.raises(Exception):
            database.execute(
                """
                insert into api_capability
                  (id, identifier, name, created_by, created_at, updated_at)
                values ('capability-duplicate',
                        'cap__ones__work_item__search',
                        'Duplicate', 'test', ?, ?)
                """,
                (timestamp, timestamp),
            )
    finally:
        database.close()


def test_runtime_lineage_is_joinable_without_secret_or_raw_body_columns() -> None:
    database = _migrated_database()
    try:

        def columns(table: str) -> set[str]:
            return {str(row["name"]) for row in database.execute(f"pragma table_info({table})")}

        assert {
            "job_id",
            "correlation_id",
        }.issubset(columns("channel_ingress_event"))
        assert {
            "internal_user_id",
            "agent_publication_id",
            "business_application_publication_id",
        }.issubset(columns("agent_job"))
        assert {
            "job_id",
            "external_identity_id",
            "external_user_id",
            "default_team_id",
            "snapshot_hash",
        }.issubset(columns("agent_job_external_subject"))
        assert {
            "tool_call_id",
            "user_id",
            "application_publication_id",
            "agent_publication_id",
            "capability_release_id",
            "data_classification",
            "normalized_result_hash",
        }.issubset(columns("agent_tool_call_api_provenance"))
        assert {
            "tool_call_id",
            "job_id",
            "capability_release_id",
            "correlation_id",
            "status_class",
            "request_hash",
            "response_hash",
        }.issubset(columns("agent_tool_call_http_attempt"))
        assert {
            "job_id",
            "application_publication_id",
            "correlation_id",
        }.issubset(columns("delivery_outbox"))

        persisted_runtime_columns = (
            columns("agent_job_external_subject")
            | columns("agent_tool_call_api_provenance")
            | columns("agent_tool_call_http_attempt")
        )
        assert (
            not {
                "password",
                "token",
                "cookie",
                "authorization",
                "authentication_header",
                "raw_request",
                "raw_response",
                "request_body",
                "response_body",
            }
            & persisted_runtime_columns
        )
    finally:
        database.close()


def test_personal_credential_schema_has_one_current_ones_credential() -> None:
    database = _migrated_database()
    timestamp = "2026-07-31T00:00:00+00:00"
    digest = hashlib.sha256(b"connection").hexdigest()
    try:
        database.execute(
            """
            insert into api_connection
              (id, code, name, provider, created_by, created_at, updated_at)
            values ('connection-ones', 'ones', 'ONES', 'ones',
                    'user_local_admin', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into api_authentication_profile
              (id, connection_id, code, name, created_by, created_at, updated_at)
            values ('profile-ones', 'connection-ones', 'ones-login',
                    'ONES Login', 'user_local_admin', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into api_authentication_profile_revision
              (id, profile_id, revision, config_json, content_hash,
               published_by, published_at)
            values ('profile-revision-1', 'profile-ones', 1, '{}', ?,
                    'user_local_admin', ?)
            """,
            (digest, timestamp),
        )
        database.execute(
            """
            insert into api_connection_draft
              (id, connection_id, origin_scheme, origin_host, origin_port,
               content_hash, created_by, updated_by, created_at, updated_at)
            values ('connection-draft-1', 'connection-ones', 'https',
                    'ones.example.test', 443, ?, 'user_local_admin',
                    'user_local_admin', ?, ?)
            """,
            (digest, timestamp, timestamp),
        )
        database.execute(
            """
            insert into api_authentication_profile_draft
              (id, profile_id, config_json, content_hash,
               created_by, updated_by, created_at, updated_at)
            values ('profile-draft-1', 'profile-ones', '{}', ?,
                    'user_local_admin', 'user_local_admin', ?, ?)
            """,
            (digest, timestamp, timestamp),
        )
        database.execute(
            """
            insert into api_connection_verification
              (id, connection_id, connection_draft_id,
               connection_draft_revision, profile_draft_id,
               profile_draft_revision, content_hash, status,
               verified_by, verified_at)
            values ('connection-verification-1', 'connection-ones',
                    'connection-draft-1', 1, 'profile-draft-1', 1, ?,
                    'PASSED', 'user_local_admin', ?)
            """,
            (digest, timestamp),
        )
        database.execute(
            """
            insert into api_connection_revision
              (id, connection_id, revision, origin_scheme, origin_host,
               origin_port, connect_timeout_ms, read_timeout_ms,
               max_response_bytes, authentication_profile_revision_id,
               content_hash, verification_id, published_by, published_at)
            values ('connection-revision-1', 'connection-ones', 1, 'https',
                    'ones.example.test', 443, 3000, 10000, 1048576,
                    'profile-revision-1', ?, 'connection-verification-1',
                    'user_local_admin', ?)
            """,
            (digest, timestamp),
        )
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values ('user-governed-api', 'governed-api-user',
                    'Governed API User', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               display_name, status, verified_at, metadata_json,
               created_at, updated_at)
            values ('identity-ones', 'user-governed-api', 'ones', 'default',
                    'ones-user', 'ONES User', 'enabled', ?, '{}', ?, ?)
            """,
            (timestamp, timestamp, timestamp),
        )
        database.execute(
            """
            insert into external_api_credential
              (id, user_id, external_identity_id, provider,
               connection_revision_id, token_ciphertext, encryption_key_id,
               status, verified_at, created_at, updated_at)
            values ('credential-one', 'user-governed-api',
                    'identity-ones', 'ones',
                    'connection-revision-1', 'ciphertext-one', 'key-1',
                    'ACTIVE', ?, ?, ?)
            """,
            (timestamp, timestamp, timestamp),
        )
        with pytest.raises(Exception):
            database.execute(
                """
                insert into external_api_credential
                  (id, user_id, external_identity_id, provider,
                   connection_revision_id, token_ciphertext,
                   encryption_key_id, status, verified_at, created_at,
                   updated_at)
                values ('credential-two', 'user-governed-api',
                        'identity-ones', 'ones',
                        'connection-revision-1', 'ciphertext-two', 'key-1',
                        'INVALID', ?, ?, ?)
                """,
                (timestamp, timestamp, timestamp),
            )
    finally:
        database.close()
