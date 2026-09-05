from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.schema_baseline import LEGACY_MANIFEST_FILENAME


TIMESTAMP = "2026-08-14T00:00:00+00:00"


def _catalog_through(tmp_path: Path, head: int) -> Path:
    source = default_migrations_dir()
    target = tmp_path / f"migrations-through-{head}"
    target.mkdir()
    shutil.copy2(source / LEGACY_MANIFEST_FILENAME, target / LEGACY_MANIFEST_FILENAME)
    for path in source.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= head:
            shutil.copy2(path, target / path.name)
    return target


def _insert_publication(database: Database) -> None:
    database.execute(
        """
        insert into business_application
          (id, code, name, project_code, status, revision,
           created_by, created_at, updated_at)
        values ('application-workspace', 'workspace', 'Workspace', 'default',
                'enabled', 1, 'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, created_by, created_at, updated_at)
        values ('application-workspace-revision', 'application-workspace', 1,
                'published', 'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, schema_version,
           snapshot_json, config_hash, published_by, published_at)
        values ('application-workspace-publication', 'application-workspace',
                'application-workspace-revision', 1, 1, '{}', ?, 'user-a', ?)
        """,
        ("a" * 64, TIMESTAMP),
    )


def _insert_session(database: Database) -> None:
    database.execute(
        """
        insert into agent_session
          (id, source_channel, source_connector_id, external_conversation_id,
           requester_id, project_code, session_key, created_at, updated_at)
        values ('session-workspace', 'dingding_stream', 'connector-a', 'conversation-a',
                'user-a', 'default', 'direct:user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )


def test_workspace_expand_schema_enforces_active_owner_and_version_constraints() -> None:
    database = Database("sqlite:///:memory:")
    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="task-file-workspace-schema-test",
    ).run()
    assert result.head == "130"
    tables = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'table'")
    }
    assert {
        "task_workspace",
        "managed_file",
        "managed_file_version",
        "task_workspace_file",
        "file_external_reference",
        "agent_job_file_snapshot",
        "agent_job_file_request",
        "agent_job_file_snapshot_item",
        "file_materialization_transfer",
        "file_commit_intent",
        "file_object_staging",
        "file_conflict_candidate",
        "file_retention_fact",
        "file_cleanup_fact",
        "file_domain_outbox",
        "message_attachment_file_binding",
    } <= tables
    managed_file_columns = {
        str(row["name"]) for row in database.execute("pragma table_info(managed_file)")
    }
    snapshot_item_columns = {
        str(row["name"])
        for row in database.execute("pragma table_info(agent_job_file_snapshot_item)")
    }
    assert "source_received_at" in managed_file_columns
    assert {"source_received_at", "version_created_at"} <= snapshot_item_columns
    snapshot_sql_row = database.execute_one(
        "select sql from sqlite_master where type = 'table' and name = 'agent_job_file_snapshot'"
    )
    assert snapshot_sql_row is not None
    assert "schema_version = 5" in str(snapshot_sql_row["sql"])
    delivery_columns = {
        str(row["name"]) for row in database.execute("pragma table_info(delivery_outbox)")
    }
    assert {
        "delivery_kind",
        "file_id",
        "file_version_id",
        "file_content_sha256",
        "principal_user_id",
        "session_id",
        "agent_publication_id",
    } <= delivery_columns

    _insert_session(database)
    _insert_publication(database)
    workspace_values = (
        "tenant-a",
        "session-workspace",
        "PRIVATE_USER",
        "user-a",
        "application-workspace-publication",
        "2026-08-18T00:00:00+08:00",
        TIMESTAMP,
        TIMESTAMP,
    )
    database.execute(
        """
        insert into task_workspace
          (id, tenant_id, session_id, owner_type, owner_user_id,
           business_application_publication_id, expires_at,
           created_by, created_at, updated_at)
        values ('workspace-a', ?, ?, ?, ?, ?, ?, 'user-a', ?, ?)
        """,
        workspace_values,
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into task_workspace
              (id, tenant_id, session_id, owner_type, owner_user_id,
               business_application_publication_id, expires_at,
               created_by, created_at, updated_at)
            values ('workspace-duplicate', ?, ?, ?, ?, ?, ?, 'user-a', ?, ?)
            """,
            workspace_values,
        )

    database.execute(
        """
        insert into managed_file
          (id, tenant_id, owner_type, owner_user_id, display_name,
           created_by, created_at, updated_at)
        values ('file-a', 'tenant-a', 'PRIVATE_USER', 'user-a', 'evidence.txt',
                'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file_version
          (id, file_id, version_number, version_kind, media_type, encoding,
           size_bytes, content_sha256, object_key, source_kind, created_by, created_at)
        values ('version-a-1', 'file-a', 1, 'WORKING', 'text/plain', 'utf-8',
                8, ?, 'objects/version-a-1', 'AGENT_GENERATED', 'user-a', ?)
        """,
        ("b" * 64, TIMESTAMP),
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into managed_file_version
              (id, file_id, version_number, version_kind, media_type, encoding,
               size_bytes, content_sha256, object_key, source_kind, created_by, created_at)
            values ('version-a-duplicate', 'file-a', 1, 'WORKING', 'text/plain', 'utf-8',
                    8, ?, 'objects/version-a-duplicate', 'AGENT_GENERATED', 'user-a', ?)
            """,
            ("c" * 64, TIMESTAMP),
        )


def test_bounded_workspace_migration_backfills_catalog_and_adds_governed_facts(
    tmp_path: Path,
) -> None:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        _catalog_through(tmp_path, 117),
        migrator_build="bounded-workspace-before",
    ).run()
    _insert_session(database)
    _insert_publication(database)
    database.execute(
        """
        insert into task_workspace
          (id, tenant_id, session_id, owner_type, owner_user_id,
           business_application_publication_id, expires_at,
           created_by, created_at, updated_at)
        values ('workspace-before-118', 'tenant-a', 'session-workspace',
                'PRIVATE_USER', 'user-a', 'application-workspace-publication',
                '2026-08-18T00:00:00+08:00', 'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file
          (id, tenant_id, owner_type, owner_user_id, display_name,
           created_by, created_at, updated_at)
        values ('file-before-118', 'tenant-a', 'PRIVATE_USER', 'user-a',
                'before.txt', 'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file_version
          (id, file_id, version_number, version_kind, media_type, encoding,
           size_bytes, content_sha256, object_key, source_kind, created_by, created_at,
           format_code)
        values ('version-before-118', 'file-before-118', 1, 'WORKING',
                'text/plain', 'utf-8', 8, ?, 'objects/version-before-118',
                'AGENT_GENERATED', 'user-a', ?, 'TXT')
        """,
        ("d" * 64, TIMESTAMP),
    )
    database.execute(
        """
        update managed_file set current_version_id = 'version-before-118'
         where id = 'file-before-118'
        """
    )
    database.execute(
        """
        insert into task_workspace_file
          (id, workspace_id, file_id, selected_version_id, logical_name,
           role, created_at, updated_at)
        values ('workspace-link-before-118', 'workspace-before-118',
                'file-before-118', 'version-before-118', 'before.txt',
                'WORKING', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )

    upgraded = Migrator(
        database,
        _catalog_through(tmp_path, 118),
        migrator_build="bounded-workspace-after",
    ).run()

    assert upgraded.applied == ("118",)
    tables = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'table'")
    }
    assert {
        "task_workspace_catalog_revision",
        "task_workspace_catalog_member",
        "agent_job_file_working_set_item",
        "task_workspace_quota_reservation",
    } <= tables
    assert database.execute_one(
        """
        select revision from task_workspace_catalog_revision
         where workspace_id = 'workspace-before-118'
        """
    ) == {"revision": 0}
    assert database.execute_one(
        """
        select file_id, version_id, logical_name, format_code,
               readability_status, valid_from_revision, valid_to_revision
          from task_workspace_catalog_member
         where workspace_id = 'workspace-before-118'
        """
    ) == {
        "file_id": "file-before-118",
        "version_id": "version-before-118",
        "logical_name": "before.txt",
        "format_code": "TXT",
        "readability_status": "DIRECT_TEXT",
        "valid_from_revision": 0,
        "valid_to_revision": None,
    }
    snapshot_sql = database.execute_one(
        "select sql from sqlite_master where type = 'table' and name = 'agent_job_file_snapshot'"
    )
    assert snapshot_sql is not None
    assert "schema_version IN (1, 2, 3, 4, 5)" in str(snapshot_sql["sql"])
    definition_columns = {
        str(row["name"])
        for row in database.execute("pragma table_info(platform_runtime_config_definition)")
    }
    assert "tenant_compatible" in definition_columns


def test_job_manifest_and_commit_constraints_are_job_and_version_bound() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="file-manifest-test").run()
    _insert_session(database)
    _insert_publication(database)
    database.execute(
        """
        insert into task_workspace
          (id, tenant_id, session_id, owner_type, owner_user_id,
           business_application_publication_id, expires_at,
           created_by, created_at, updated_at)
        values ('workspace-a', 'tenant-a', 'session-workspace', 'PRIVATE_USER', 'user-a',
                'application-workspace-publication', '2026-08-18T00:00:00+08:00',
                'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id, task_workspace_id)
        values ('job-workspace', 'session-workspace', 'job-workspace-key', 'RUNNING', ?,
                'dingding_stream', 'connector-a', 'user-a', 'workspace-a')
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into managed_file
          (id, tenant_id, owner_type, owner_user_id, display_name,
           created_by, created_at, updated_at)
        values ('file-a', 'tenant-a', 'PRIVATE_USER', 'user-a', 'evidence.txt',
                'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file_version
          (id, file_id, version_number, version_kind, media_type, encoding,
           size_bytes, content_sha256, object_key, source_kind, created_by, created_at)
        values ('version-a-1', 'file-a', 1, 'WORKING', 'text/plain', 'utf-8',
                8, ?, 'objects/version-a-1', 'AGENT_GENERATED', 'user-a', ?)
        """,
        ("b" * 64, TIMESTAMP),
    )
    database.execute(
        """
        insert into agent_job_file_snapshot
          (id, job_id, workspace_id, tenant_id, principal_user_id,
           business_application_publication_id, retention_period,
           manifest_hash, created_at)
        values ('snapshot-a', 'job-workspace', 'workspace-a', 'tenant-a', 'user-a',
                'application-workspace-publication', 'WEEK', ?, ?)
        """,
        ("d" * 64, TIMESTAMP),
    )
    database.execute(
        """
        insert into agent_job_file_snapshot_item
          (id, snapshot_id, ordinal, file_id, version_id, display_name,
           source_kind, allowed_actions_json, auto_materialize, created_at)
        values ('snapshot-item-a', 'snapshot-a', 0, 'file-a', 'version-a-1',
                'evidence.txt', 'CURRENT_MESSAGE', '["READ","EDIT"]', 1, ?)
        """,
        (TIMESTAMP,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into agent_job_file_snapshot_item
              (id, snapshot_id, ordinal, file_id, version_id, display_name,
               source_kind, created_at)
            values ('snapshot-item-duplicate', 'snapshot-a', 0, 'file-a',
                    'version-a-1', 'evidence.txt', 'CURRENT_MESSAGE', ?)
            """,
            (TIMESTAMP,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into file_commit_intent
              (id, commit_id, job_id, workspace_id, target_file_id,
               sandbox_entry_handle, display_name, user_intent, delivery_mode,
               metadata_hash, expires_at, created_at, updated_at)
            values ('intent-invalid', 'commit-invalid', 'job-workspace', 'workspace-a',
                    'file-a', 'entry-a', 'evidence.txt', 'MODIFY', 'DEFAULT', ?,
                    '2026-08-14T00:10:00+00:00', ?, ?)
            """,
            ("e" * 64, TIMESTAMP, TIMESTAMP),
        )


def test_attachment_retention_backfill_uses_360_days_and_only_marks_cleanup(
    tmp_path: Path,
) -> None:
    database = Database("sqlite:///:memory:")
    through_106 = _catalog_through(tmp_path, 106)
    Migrator(database, through_106, migrator_build="attachment-retention-predecessor").run()
    _insert_session(database)
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id)
        values ('job-old-attachment', 'session-workspace', 'job-old-attachment-key',
                'SUCCEEDED', '2020-01-01T00:00:00+00:00',
                'dingding_stream', 'connector-a', 'user-a')
        """
    )
    database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-old-attachment', 'session-workspace', 'job-old-attachment',
                'user', '', '2020-01-01T00:00:00+00:00', 1)
        """
    )
    database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name,
           status, object_bucket, object_key, created_at, updated_at)
        values ('attachment-old', 'message-old-attachment', 'job-old-attachment', 1,
                'document', 'old.md', 'READY', 'private', 'attachments/old',
                '2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00')
        """
    )

    upgraded = Migrator(
        database,
        _catalog_through(tmp_path, 118),
        migrator_build="attachment-retention-upgrade",
    ).run()

    assert upgraded.applied == (
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
    )
    attachment = database.execute_one(
        """
        select retention_days, expires_at, object_key, status
          from message_attachment where id = 'attachment-old'
        """
    )
    assert attachment == {
        "retention_days": 360,
        "expires_at": "2020-12-26 00:00:00",
        "object_key": "attachments/old",
        "status": "READY",
    }
    cleanup = database.execute_one(
        """
        select resource_type, resource_id, reason, status
          from file_cleanup_fact where resource_id = 'attachment-old'
        """
    )
    assert cleanup == {
        "resource_type": "ATTACHMENT_CONTENT",
        "resource_id": "attachment-old",
        "reason": "RETENTION_EXPIRED",
        "status": "PENDING",
    }


def test_source_received_time_backfill_uses_attachment_record_without_object_access(
    tmp_path: Path,
) -> None:
    database = Database("sqlite:///:memory:")
    through_109 = _catalog_through(tmp_path, 109)
    Migrator(database, through_109, migrator_build="file-time-predecessor").run()
    _insert_session(database)
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id)
        values ('job-file-time', 'session-workspace', 'job-file-time-key',
                'SUCCEEDED', ?, 'dingding_stream', 'connector-a', 'user-a')
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into agent_message
          (id, session_id, job_id, role, content, created_at, sequence_no)
        values ('message-file-time', 'session-workspace', 'job-file-time',
                'user', '', ?, 1)
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into message_attachment
          (id, message_id, job_id, ordinal, media_type, file_name, status,
           created_at, updated_at)
        values ('attachment-file-time', 'message-file-time', 'job-file-time', 1,
                'document', 'source.txt', 'READY', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file
          (id, tenant_id, owner_type, owner_user_id, display_name, status,
           created_by, created_at, updated_at)
        values ('file-time', 'tenant-a', 'PRIVATE_USER', 'user-a', 'source.txt',
                'ACTIVE', 'file-worker', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file_version
          (id, file_id, version_number, version_kind, status, media_type,
           encoding, size_bytes, content_sha256, object_key, source_kind,
           created_by, created_at)
        values ('version-file-time', 'file-time', 1, 'ATTACHMENT', 'AVAILABLE',
                'text/plain', 'utf-8', 5, ?, 'opaque/version-file-time',
                'MESSAGE_ATTACHMENT', 'file-worker', ?)
        """,
        ("a" * 64, TIMESTAMP),
    )
    database.execute(
        """
        insert into message_attachment_file_binding
          (attachment_id, file_id, version_id, retention_expires_at, created_at)
        values ('attachment-file-time', 'file-time', 'version-file-time',
                '2027-08-14T00:00:00+00:00', ?)
        """,
        (TIMESTAMP,),
    )

    upgraded = Migrator(
        database,
        _catalog_through(tmp_path, 118),
        migrator_build="file-time-upgrade",
    ).run()

    assert upgraded.applied == ("110", "111", "112", "113", "114", "115", "116", "117", "118")
    assert database.execute_one(
        "select source_received_at from managed_file where id = 'file-time'"
    ) == {"source_received_at": TIMESTAMP}
