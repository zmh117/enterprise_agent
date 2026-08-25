from __future__ import annotations

import hashlib

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


def _insert_topology(database: Database) -> None:
    database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values ('environment-resource-test', 'resource_test', 'Resource Test',
                'enabled', '2026-07-28T00:00:00+00:00',
                '2026-07-28T00:00:00+00:00')
        """
    )
    database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values ('base-resource-test', 'environment-resource-test',
                'resource_base', 'Resource Base', 'mysql', 'enabled',
                '2026-07-28T00:00:00+00:00',
                '2026-07-28T00:00:00+00:00')
        """
    )


def _insert_resource(database: Database, *, resource_id: str, code: str) -> None:
    database.execute(
        """
        insert into platform_resource
          (id, code, name, resource_kind, scope_type, environment_id,
           base_id, status, created_by, created_at, updated_at)
        values (?, ?, ?, 'database', 'base', 'environment-resource-test',
                'base-resource-test', 'enabled', 'test',
                '2026-07-28T00:00:00+00:00',
                '2026-07-28T00:00:00+00:00')
        """,
        (resource_id, code, code),
    )


def test_governed_resource_schema_has_stable_revision_records_without_legacy_mapping() -> None:
    database = Database("sqlite:///:memory:")
    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="resource-schema-test",
    ).run()

    assert result.head == "120"
    tables = {
        row["name"]
        for row in database.execute("select name from sqlite_master where type = 'table'")
    }
    assert {
        "platform_resource",
        "platform_resource_draft",
        "platform_resource_verification",
        "platform_resource_revision",
    }.issubset(tables)
    assert {
        "business_application_resource_binding",
        "business_application_publication_handler",
        "business_application_publication_resource",
        "platform_resource_activation",
        "runtime_snapshot_generation",
        "tool_resource_runtime_state",
        "business_application_runtime_state",
        "agent_job_execution_binding",
        "agent_tool_binding",
        "tool_definition",
        "agent_job_execution_scope",
        "business_application_revision_target",
        "business_application_publication_target",
        "permission_policy",
        "platform_access_grant",
        "legacy_authorization_cleanup_operation",
    }.isdisjoint(tables)
    agent_columns = {row["name"] for row in database.execute("pragma table_info(agent_definition)")}
    job_columns = {row["name"] for row in database.execute("pragma table_info(agent_job)")}
    assert "classification" in agent_columns
    assert {"execution_scope_id", "execution_scope_hash"}.isdisjoint(job_columns)
    draft_columns = {
        row["name"] for row in database.execute("pragma table_info(platform_resource_draft)")
    }
    revision_columns = {
        row["name"] for row in database.execute("pragma table_info(platform_resource_revision)")
    }
    assert "scope_bindings_json" in draft_columns
    assert "scope_bindings_json" in revision_columns
    database.close()


def test_resource_scope_draft_and_revision_constraints_fail_closed() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="resource-constraint-test",
    ).run()
    _insert_topology(database)
    _insert_resource(
        database,
        resource_id="resource-one",
        code="resource_one",
    )
    _insert_resource(
        database,
        resource_id="resource-two",
        code="resource_two",
    )

    with pytest.raises(Exception):
        database.execute(
            """
            insert into platform_resource
              (id, code, resource_kind, scope_type, environment_id,
               status, created_at, updated_at)
            values ('resource-invalid', 'resource_invalid', 'database',
                    'base', 'environment-resource-test', 'enabled',
                    '2026-07-28T00:00:00+00:00',
                    '2026-07-28T00:00:00+00:00')
            """
        )

    content_hash = hashlib.sha256(b"resource-one-v1").hexdigest()
    database.execute(
        """
        insert into platform_resource_draft
          (id, resource_id, draft_revision, provider_type, config_json,
           secret_refs_json, content_hash, status, created_at, updated_at)
        values ('draft-one', 'resource-one', 1, 'mysql', '{}', '{}', ?,
                'VERIFIED', '2026-07-28T00:00:00+00:00',
                '2026-07-28T00:00:00+00:00')
        """,
        (content_hash,),
    )
    with pytest.raises(Exception):
        database.execute(
            """
            insert into platform_resource_draft
              (id, resource_id, draft_revision, provider_type, config_json,
               secret_refs_json, content_hash, status, created_at, updated_at)
            values ('draft-one-duplicate', 'resource-one', 2, 'mysql',
                    '{}', '{}', ?, 'DRAFT',
                    '2026-07-28T00:00:00+00:00',
                    '2026-07-28T00:00:00+00:00')
            """,
            (content_hash,),
        )
    database.execute(
        """
        insert into platform_resource_verification
          (id, resource_id, draft_id, draft_revision, content_hash, status,
           provider_contract_version, checks_json, verified_at)
        values ('verification-one', 'resource-one', 'draft-one', 1, ?,
                'PASSED', 'database.v1', '{}',
                '2026-07-28T00:00:00+00:00')
        """,
        (content_hash,),
    )
    database.execute(
        """
        insert into platform_resource_revision
          (id, resource_id, revision, provider_type, provider_contract_version,
           config_json, secret_refs_json, content_hash, verification_id,
           status, published_by, published_at)
        values ('resource-revision-one', 'resource-one', 1, 'mysql',
                'database.v1', '{}', '{}', ?, 'verification-one',
                'PUBLISHED', 'test', '2026-07-28T00:00:00+00:00')
        """,
        (content_hash,),
    )

    database.execute("delete from platform_resource_draft where id = 'draft-one'")
    verification = database.execute_one(
        "select draft_id from platform_resource_verification where id = ?",
        ("verification-one",),
    )
    assert verification == {"draft_id": None}

    with pytest.raises(Exception):
        database.execute("delete from platform_resource where id = 'resource-one'")
    database.close()


def test_global_resource_scope_migration_preserves_foreign_keys() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="global-resource-scope-test",
    ).run()
    database.execute(
        """
        insert into platform_resource
          (id, code, name, resource_kind, scope_type, environment_id,
           base_id, workshop_id, status, revision, created_by,
           created_at, updated_at)
        values ('global-loki', 'global_loki', 'Global Loki', 'loki',
                'global', null, null, null, 'enabled', 1, 'test',
                '2026-08-06T00:00:00Z', '2026-08-06T00:00:00Z')
        """
    )
    assert database.execute_one(
        "select environment_id from platform_resource where id = 'global-loki'"
    ) == {"environment_id": None}
    assert database.execute("pragma foreign_key_check") == []
    with pytest.raises(Exception):
        database.execute(
            """
            insert into platform_resource_revision
              (id, resource_id, revision, provider_type,
               provider_contract_version, config_json, secret_refs_json,
               content_hash, verification_id, status, published_by,
               published_at)
            values ('bad-revision', 'missing-resource', 1, 'loki', 'loki_v1',
                    '{}', '{}', ?, 'missing-verification', 'PUBLISHED',
                    'test', '2026-08-06T00:00:00Z')
            """,
            (hashlib.sha256(b"bad").hexdigest(),),
        )
    database.close()
