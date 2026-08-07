from __future__ import annotations

import hashlib

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


EXPECTED_TABLES = {
    "builtin_tool_manifest_projection",
    "builtin_tool_installation",
    "builtin_tool_verification",
    "builtin_tool_release",
    "builtin_tool_lifecycle_audit",
    "agent_publication_builtin_tool",
    "business_application_revision_target",
    "business_application_publication_target",
    "business_application_publication_builtin_tool",
    "business_application_publication_builtin_tool_resource",
    "business_application_publication_builtin_tool_resolution_set",
    "business_application_publication_builtin_tool_resolution",
    "workshop_partition_policy",
    "workshop_partition_policy_draft",
    "workshop_partition_policy_draft_redis_prefix",
    "workshop_partition_policy_verification",
    "workshop_partition_policy_revision",
    "workshop_partition_policy_revision_redis_prefix",
    "loki_scope_policy",
    "loki_scope_policy_draft",
    "loki_scope_policy_draft_condition",
    "loki_scope_policy_verification",
    "loki_scope_policy_revision",
    "loki_scope_policy_revision_condition",
    "agent_job_builtin_tool_snapshot",
    "agent_job_builtin_tool_binding",
    "agent_tool_call_builtin_tool_fact",
    "builtin_tool_legacy_migration",
    "builtin_tool_legacy_write_audit",
}


def _migrated_database() -> Database:
    database = Database("sqlite:///:memory:")
    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="builtin-tool-schema-test",
    ).run()
    assert result.head == "033"
    return database


def _install_verified_release(database: Database) -> None:
    digest = hashlib.sha256(b"query-database-implementation").hexdigest()
    manifest_hash = hashlib.sha256(b"query-database-manifest").hexdigest()
    schema_hash = hashlib.sha256(b"query-database-public-schema").hexdigest()
    timestamp = "2026-08-06T00:00:00+00:00"
    database.execute(
        """
        insert into builtin_tool_manifest_projection
          (tool_identifier, handler_version, implementation_digest,
           tool_semantic_version, manifest_hash, public_schema_hash,
           manifest_json, verifier_plan_json, verifier_version, observed_at)
        values ('query_database', '1.0.0', ?, '1.0.0', ?, ?, '{}', '{}',
                'query-database-verifier.v1', ?)
        """,
        (digest, manifest_hash, schema_hash, timestamp),
    )
    database.execute(
        """
        insert into builtin_tool_installation
          (tool_identifier, handler_version, implementation_digest,
           installation_status, first_seen_at, last_seen_at)
        values ('query_database', '1.0.0', ?, 'INSTALLED', ?, ?)
        """,
        (digest, timestamp, timestamp),
    )
    database.execute(
        """
        insert into builtin_tool_verification
          (id, tool_identifier, handler_version, implementation_digest,
           verifier_version, normalized_input_hash, status,
           result_summary_json, verified_by, verified_at)
        values ('verification-query-database', 'query_database', '1.0.0', ?,
                'query-database-verifier.v1', ?, 'PASSED', '{}', 'test', ?)
        """,
        (digest, hashlib.sha256(b"verification-input").hexdigest(), timestamp),
    )
    database.execute(
        """
        insert into builtin_tool_release
          (id, tool_identifier, release_revision, tool_semantic_version,
           handler_version, implementation_digest, manifest_hash,
           public_schema_hash, verification_id, status, idempotency_key,
           published_by, published_at)
        values ('release-query-database-v1', 'query_database', 1, '1.0.0',
                '1.0.0', ?, ?, ?, 'verification-query-database', 'ACTIVE',
                'publish-query-database-v1', 'test', ?)
        """,
        (digest, manifest_hash, schema_hash, timestamp),
    )


def _insert_publications(database: Database) -> None:
    timestamp = "2026-08-06T00:00:00+00:00"
    database.execute(
        """
        insert into agent_definition
          (id, code, name, project_code, status, created_by, created_at,
           updated_at)
        values ('agent-schema-test', 'agent-schema-test', 'Agent Schema Test',
                'default', 'enabled', 'test', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_revision
          (id, agent_id, revision, status, config_json, config_hash,
           validation_json, created_by, created_at, updated_at)
        values ('agent-revision-schema-test', 'agent-schema-test', 1,
                'published', '{}', 'agent-config-hash', '{}', 'test', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_publication
          (id, agent_id, revision_id, revision, schema_version, snapshot_json,
           config_hash, status, published_by, published_at)
        values ('agent-publication-schema-test', 'agent-schema-test',
                'agent-revision-schema-test', 1, 1, '{}',
                'agent-config-hash', 'active', 'test', ?)
        """,
        (timestamp,),
    )
    database.execute(
        """
        insert into business_application
          (id, code, name, project_code, status, created_by, created_at,
           updated_at)
        values ('application-schema-test', 'application-schema-test',
                'Application Schema Test', 'default', 'enabled', 'test', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, agent_publication_id,
           config_hash, created_by, created_at, updated_at)
        values ('application-revision-schema-test', 'application-schema-test',
                1, 'published', 'agent-publication-schema-test',
                'application-config-hash', 'test', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, schema_version,
           snapshot_json, config_hash, published_by, published_at)
        values ('application-publication-schema-test',
                'application-schema-test', 'application-revision-schema-test',
                1, 1, '{}', 'application-config-hash', 'test', ?)
        """,
        (timestamp,),
    )


def test_028_adds_governed_builtin_tool_and_policy_schema() -> None:
    database = _migrated_database()
    try:
        tables = {
            row["name"]
            for row in database.execute("select name from sqlite_master where type = 'table'")
        }
        views = {
            row["name"]
            for row in database.execute("select name from sqlite_master where type = 'view'")
        }
        assert EXPECTED_TABLES.issubset(tables)
        assert "builtin_tool_legacy_reference_report" in views
    finally:
        database.close()


def test_release_identity_lifecycle_foreign_keys_and_publish_idempotency_fail_closed() -> None:
    database = _migrated_database()
    try:
        _install_verified_release(database)

        with pytest.raises(Exception):
            database.execute(
                """
                insert into builtin_tool_installation
                  (tool_identifier, handler_version, implementation_digest,
                   installation_status, first_seen_at, last_seen_at)
                values ('query_database', '1.0.0', ?, 'INSTALLED', ?, ?)
                """,
                (
                    hashlib.sha256(b"different-implementation").hexdigest(),
                    "2026-08-06T00:00:00+00:00",
                    "2026-08-06T00:00:00+00:00",
                ),
            )

        release = database.execute_one(
            "select status, release_revision from builtin_tool_release where id = ?",
            ("release-query-database-v1",),
        )
        assert release == {"status": "ACTIVE", "release_revision": 1}

        with pytest.raises(Exception):
            database.execute(
                """
                insert into builtin_tool_release
                  (id, tool_identifier, release_revision,
                   tool_semantic_version, handler_version,
                   implementation_digest, manifest_hash, public_schema_hash,
                   verification_id, status, idempotency_key, published_by,
                   published_at)
                select 'release-query-database-duplicate', tool_identifier, 2,
                       tool_semantic_version, handler_version,
                       implementation_digest, manifest_hash,
                       public_schema_hash, verification_id, 'ACTIVE',
                       idempotency_key, 'test', published_at
                  from builtin_tool_release
                 where id = 'release-query-database-v1'
                """
            )

        with pytest.raises(Exception):
            database.execute(
                """
                insert into builtin_tool_release
                  (id, tool_identifier, release_revision,
                   tool_semantic_version, handler_version,
                   implementation_digest, manifest_hash, public_schema_hash,
                   verification_id, status, idempotency_key, published_by,
                   published_at)
                select 'release-query-database-invalid', tool_identifier, 2,
                       tool_semantic_version, handler_version,
                       implementation_digest, manifest_hash,
                       public_schema_hash, verification_id, 'PUBLISHED',
                       'publish-invalid-status', 'test', published_at
                  from builtin_tool_release
                 where id = 'release-query-database-v1'
                """
            )

        with pytest.raises(Exception):
            database.execute(
                """
                delete from builtin_tool_installation
                 where tool_identifier = 'query_database'
                   and handler_version = '1.0.0'
                """
            )
    finally:
        database.close()


def test_partition_loki_mapping_and_job_fact_constraints_are_structural() -> None:
    database = _migrated_database()
    try:
        mapping_columns = {
            row["name"]
            for row in database.execute(
                "pragma table_info(business_application_publication_builtin_tool_resource)"
            )
        }
        assert {
            "target_scope_type",
            "target_key",
            "placement",
            "resource_revision_id",
            "workshop_partition_policy_revision_id",
            "loki_scope_policy_revision_id",
            "mapping_hash",
        }.issubset(mapping_columns)

        resolution_columns = {
            row["name"]
            for row in database.execute(
                "pragma table_info(business_application_publication_builtin_tool_resolution)"
            )
        }
        assert {
            "application_publication_id",
            "application_tool_id",
            "tool_release_id",
            "implementation_digest",
            "resource_slot",
            "target_key",
            "target_hash",
            "placement",
            "resource_revision_id",
            "resource_content_hash",
            "workshop_partition_policy_revision_id",
            "workshop_partition_policy_hash",
            "loki_scope_policy_revision_id",
            "loki_scope_policy_hash",
            "mapping_hash",
            "resolution_hash",
            "resolution_order",
        }.issubset(resolution_columns)
        resolution_set_columns = {
            row["name"]
            for row in database.execute(
                "pragma table_info(business_application_publication_builtin_tool_resolution_set)"
            )
        }
        assert {
            "application_publication_id",
            "schema_version",
            "resolution_count",
            "resolution_set_hash",
        }.issubset(resolution_set_columns)

        tool_call_columns = {
            row["name"]
            for row in database.execute("pragma table_info(agent_tool_call_builtin_tool_fact)")
        }
        assert {
            "actual_placement",
            "tool_release_id",
            "handler_version",
            "implementation_digest",
            "resource_revision_id",
            "workshop_partition_policy_revision_id",
            "loki_scope_policy_revision_id",
            "effective_scope_hash",
            "authorization_decision",
            "correlation_id",
        }.issubset(tool_call_columns)

        timestamp = "2026-08-06T00:00:00+00:00"
        partition_hash = hashlib.sha256(b"partition-draft").hexdigest()
        loki_policy_hash = hashlib.sha256(b"loki-draft").hexdigest()
        database.execute(
            """
            insert into platform_environment
              (id, code, display_name, status, created_at, updated_at)
            values ('environment-policy-test', 'policy_test', 'Policy Test',
                    'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into platform_base
              (id, environment_id, code, display_name, engine, status,
               created_at, updated_at)
            values ('base-policy-test', 'environment-policy-test',
                    'base_policy_test', 'Base Policy Test', 'mysql',
                    'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into platform_workshop
              (id, base_id, code, display_name, status, created_at, updated_at)
            values ('workshop-policy-test', 'base-policy-test', 'GL001',
                    'GL001', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into workshop_partition_policy
              (id, code, workshop_id, status, created_by, created_at,
               updated_at)
            values ('partition-policy-test', 'partition_policy_test',
                    'workshop-policy-test', 'enabled', 'test', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into workshop_partition_policy_draft
              (policy_id, draft_revision, database_rule_enabled,
               database_table_prefix, redis_rule_enabled, content_hash,
               status, updated_by, updated_at)
            values ('partition-policy-test', 1, 1, 'GL001_', 1, ?, 'DRAFT',
                    'test', ?)
            """,
            (partition_hash, timestamp),
        )
        prefix = "cr999.crmes.CRMES_TEST_GL#GL001@$"
        database.execute(
            """
            insert into workshop_partition_policy_draft_redis_prefix
              (policy_id, prefix, position)
            values ('partition-policy-test', ?, 0)
            """,
            (prefix,),
        )
        with pytest.raises(Exception):
            database.execute(
                """
                insert into workshop_partition_policy_draft_redis_prefix
                  (policy_id, prefix, position)
                values ('partition-policy-test', ?, 1)
                """,
                (prefix,),
            )

        database.execute(
            """
            insert into workshop_partition_policy_verification
              (id, policy_id, draft_revision, content_hash, verifier_version,
               status, database_summary_json, redis_summary_json,
               verified_by, verified_at)
            values ('partition-verification-test', 'partition-policy-test', 1,
                    ?, 'partition-verifier.v1', 'PASSED', '{}', '{}', 'test', ?)
            """,
            (partition_hash, timestamp),
        )
        database.execute(
            """
            insert into workshop_partition_policy_revision
              (id, policy_id, revision, database_rule_enabled,
               database_table_prefix, redis_rule_enabled, content_hash,
               verification_id, status, published_by, published_at)
            values ('partition-revision-test', 'partition-policy-test', 1, 1,
                    'GL001_', 1, ?, 'partition-verification-test',
                    'PUBLISHED', 'test', ?)
            """,
            (partition_hash, timestamp),
        )
        database.execute(
            """
            insert into workshop_partition_policy_revision_redis_prefix
              (policy_revision_id, prefix, position)
            values ('partition-revision-test', ?, 0)
            """,
            (prefix,),
        )

        with pytest.raises(Exception):
            database.execute(
                """
                update workshop_partition_policy_draft
                   set database_table_prefix = 'GL%001_'
                 where policy_id = 'partition-policy-test'
                """
            )

        resource_hash = hashlib.sha256(b"loki-resource-revision").hexdigest()
        database.execute(
            """
            insert into platform_resource
              (id, code, name, resource_kind, scope_type, environment_id,
               status, created_by, created_at, updated_at)
            values ('loki-resource-test', 'loki_resource_test', 'Loki Test',
                    'loki', 'environment', 'environment-policy-test',
                    'enabled', 'test', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into platform_resource_verification
              (id, resource_id, draft_revision, content_hash, status,
               provider_contract_version, checks_json, verified_by,
               verified_at)
            values ('loki-resource-verification-test', 'loki-resource-test',
                    1, ?, 'PASSED', 'loki.v1', '{}', 'test', ?)
            """,
            (resource_hash, timestamp),
        )
        database.execute(
            """
            insert into platform_resource_revision
              (id, resource_id, revision, provider_type,
               provider_contract_version, config_json, secret_refs_json,
               content_hash, verification_id, status, published_by,
               published_at)
            values ('loki-resource-revision-test', 'loki-resource-test', 1,
                    'loki', 'loki.v1', '{}', '{}', ?,
                    'loki-resource-verification-test', 'PUBLISHED', 'test', ?)
            """,
            (resource_hash, timestamp),
        )

        database.execute(
            """
            insert into loki_scope_policy
              (id, code, environment_id, base_id, status, created_by,
               created_at, updated_at)
            values ('loki-policy-test', 'loki_policy_test',
                    'environment-policy-test', 'base-policy-test', 'enabled',
                    'test', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into loki_scope_policy_draft
              (policy_id, draft_revision, resource_revision_id, content_hash,
               status, updated_by, updated_at)
            values ('loki-policy-test', 1, 'loki-resource-revision-test', ?,
                    'DRAFT', 'test', ?)
            """,
            (loki_policy_hash, timestamp),
        )
        database.execute(
            """
            insert into loki_scope_policy_draft_condition
              (policy_id, label_key, label_value, position)
            values ('loki-policy-test', 'customer', 'sanjiu', 0)
            """
        )
        with pytest.raises(Exception):
            database.execute(
                """
                insert into loki_scope_policy_draft_condition
                  (policy_id, label_key, label_value, position)
                values ('loki-policy-test', 'customer', 'other', 1)
                """
            )

        database.execute(
            """
            insert into loki_scope_policy_verification
              (id, policy_id, draft_revision, resource_revision_id, content_hash,
               verifier_version, status, match_count, truncated,
               zero_match_warning, result_summary_json, verified_by,
               verified_at)
            values ('loki-policy-verification-test', 'loki-policy-test', 1,
                    'loki-resource-revision-test', ?, 'loki-verifier.v1',
                    'PASSED', 0, 0, 1, '{}', 'test', ?)
            """,
            (loki_policy_hash, timestamp),
        )
        database.execute(
            """
            insert into loki_scope_policy_revision
              (id, policy_id, revision, resource_revision_id, content_hash,
               verification_id, status, health_status, published_by,
               published_at)
            values ('loki-policy-revision-test', 'loki-policy-test', 1,
                    'loki-resource-revision-test', ?,
                    'loki-policy-verification-test', 'PUBLISHED', 'EMPTY',
                    'test', ?)
            """,
            (loki_policy_hash, timestamp),
        )
        database.execute(
            """
            insert into loki_scope_policy_revision_condition
              (policy_revision_id, label_key, label_value, position)
            values ('loki-policy-revision-test', 'customer', 'sanjiu', 0)
            """
        )
    finally:
        database.close()


def test_agent_application_envelopes_allow_exact_one_to_many_resource_mappings() -> None:
    database = _migrated_database()
    try:
        _install_verified_release(database)
        _insert_publications(database)
        timestamp = "2026-08-06T00:00:00+00:00"
        digest = hashlib.sha256(b"query-database-implementation").hexdigest()
        schema_hash = hashlib.sha256(b"query-database-public-schema").hexdigest()
        database.execute(
            """
            insert into agent_publication_builtin_tool
              (id, agent_publication_id, tool_identifier, tool_release_id,
               handler_version, implementation_digest, public_schema_hash,
               envelope_hash, created_at)
            values ('agent-envelope-query-database',
                    'agent-publication-schema-test', 'query_database',
                    'release-query-database-v1', '1.0.0', ?, ?, ?, ?)
            """,
            (
                digest,
                schema_hash,
                hashlib.sha256(b"agent-envelope").hexdigest(),
                timestamp,
            ),
        )
        database.execute(
            """
            insert into business_application_publication_builtin_tool
              (id, application_publication_id, agent_publication_id,
               agent_publication_tool_id, tool_identifier, tool_release_id,
               handler_version, implementation_digest, public_schema_hash,
               allowlist_hash, created_at)
            values ('application-tool-query-database',
                    'application-publication-schema-test',
                    'agent-publication-schema-test',
                    'agent-envelope-query-database', 'query_database',
                    'release-query-database-v1', '1.0.0', ?, ?, ?, ?)
            """,
            (
                digest,
                schema_hash,
                hashlib.sha256(b"application-allowlist").hexdigest(),
                timestamp,
            ),
        )
        database.execute(
            """
            insert into platform_environment
              (id, code, display_name, status, created_at, updated_at)
            values ('environment-mapping-test', 'mapping_test',
                    'Mapping Test', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into platform_base
              (id, environment_id, code, display_name, engine, status,
               created_at, updated_at)
            values ('base-mapping-test', 'environment-mapping-test',
                    'mapping_base', 'Mapping Base', 'mysql', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        resource_hash = hashlib.sha256(b"mapping-resource").hexdigest()
        database.execute(
            """
            insert into platform_resource
              (id, code, name, resource_kind, scope_type, environment_id,
               base_id, status, created_by, created_at, updated_at)
            values ('resource-mapping-test', 'resource_mapping_test',
                    'Resource Mapping Test', 'database', 'base',
                    'environment-mapping-test', 'base-mapping-test',
                    'enabled', 'test', ?, ?)
            """,
            (timestamp, timestamp),
        )
        database.execute(
            """
            insert into platform_resource_verification
              (id, resource_id, draft_revision, content_hash, status,
               provider_contract_version, checks_json, verified_by,
               verified_at)
            values ('resource-mapping-verification', 'resource-mapping-test',
                    1, ?, 'PASSED', 'database.v1', '{}', 'test', ?)
            """,
            (resource_hash, timestamp),
        )
        database.execute(
            """
            insert into platform_resource_revision
              (id, resource_id, revision, provider_type,
               provider_contract_version, config_json, secret_refs_json,
               content_hash, verification_id, status, published_by,
               published_at)
            values ('resource-mapping-revision', 'resource-mapping-test', 1,
                    'mysql', 'database.v1', '{}', '{}', ?,
                    'resource-mapping-verification', 'PUBLISHED', 'test', ?)
            """,
            (resource_hash, timestamp),
        )

        for placement in ("cloud", "edge"):
            database.execute(
                """
                insert into business_application_publication_builtin_tool_resource
                  (id, application_tool_id, resource_slot, target_scope_type,
                   target_key, environment_id, base_id, placement,
                   placement_key, resource_revision_id, mapping_hash,
                   created_at)
                values (?, 'application-tool-query-database', 'database',
                        'base', 'environment-mapping-test/base-mapping-test',
                        'environment-mapping-test', 'base-mapping-test', ?, ?,
                        'resource-mapping-revision', ?, ?)
                """,
                (
                    f"mapping-{placement}",
                    placement,
                    placement,
                    hashlib.sha256(f"mapping-{placement}".encode()).hexdigest(),
                    timestamp,
                ),
            )

        assert database.execute_one(
            """
            select count(*) as count
              from business_application_publication_builtin_tool_resource
             where application_tool_id = 'application-tool-query-database'
               and resource_slot = 'database'
            """
        ) == {"count": 2}

        with pytest.raises(Exception):
            database.execute(
                """
                insert into business_application_publication_builtin_tool_resource
                  (id, application_tool_id, resource_slot, target_scope_type,
                   target_key, environment_id, base_id, placement,
                   placement_key, resource_revision_id, mapping_hash,
                   created_at)
                values ('mapping-invalid-placement',
                        'application-tool-query-database', 'database', 'base',
                        'environment-mapping-test/base-mapping-test',
                        'environment-mapping-test', 'base-mapping-test',
                        'none', 'none', 'resource-mapping-revision', ?, ?)
                """,
                (hashlib.sha256(b"mapping-invalid").hexdigest(), timestamp),
            )
    finally:
        database.close()


def test_application_targets_enforce_exact_topology_parentage_and_shape() -> None:
    database = _migrated_database()
    try:
        _insert_publications(database)
        timestamp = "2026-08-06T00:00:00+00:00"
        for environment_id in ("environment-target-a", "environment-target-b"):
            database.execute(
                """
                insert into platform_environment
                  (id, code, display_name, status, created_at, updated_at)
                values (?, ?, ?, 'enabled', ?, ?)
                """,
                (
                    environment_id,
                    environment_id,
                    environment_id,
                    timestamp,
                    timestamp,
                ),
            )
        for base_id in ("base-target-a", "base-target-b"):
            database.execute(
                """
                insert into platform_base
                  (id, environment_id, code, display_name, engine, status,
                   created_at, updated_at)
                values (?, 'environment-target-a', ?, ?, 'mysql', 'enabled',
                        ?, ?)
                """,
                (base_id, base_id, base_id, timestamp, timestamp),
            )
        database.execute(
            """
            insert into platform_workshop
              (id, base_id, code, display_name, status, created_at, updated_at)
            values ('workshop-target-a', 'base-target-a', 'GL001', 'GL001',
                    'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
        target_hash = hashlib.sha256(b"application-target").hexdigest()

        with pytest.raises(Exception):
            database.execute(
                """
                insert into business_application_revision_target
                  (id, application_revision_id, target_scope_type, target_key,
                   environment_id, target_hash, target_order, created_at)
                values ('revision-target-invalid-shape',
                        'application-revision-schema-test', 'base',
                        'invalid-shape', 'environment-target-a', ?, 0, ?)
                """,
                (target_hash, timestamp),
            )

        with pytest.raises(Exception):
            database.execute(
                """
                insert into business_application_revision_target
                  (id, application_revision_id, target_scope_type, target_key,
                   environment_id, base_id, target_hash, target_order,
                   created_at)
                values ('revision-target-wrong-environment',
                        'application-revision-schema-test', 'base',
                        'wrong-environment', 'environment-target-b',
                        'base-target-a', ?, 0, ?)
                """,
                (target_hash, timestamp),
            )

        with pytest.raises(Exception):
            database.execute(
                """
                insert into business_application_revision_target
                  (id, application_revision_id, target_scope_type, target_key,
                   environment_id, base_id, workshop_id, target_hash,
                   target_order, created_at)
                values ('revision-target-wrong-base',
                        'application-revision-schema-test', 'workshop',
                        'wrong-base', 'environment-target-a', 'base-target-b',
                        'workshop-target-a', ?, 0, ?)
                """,
                (target_hash, timestamp),
            )

        database.execute(
            """
            insert into business_application_revision_target
              (id, application_revision_id, target_scope_type, target_key,
               environment_id, base_id, workshop_id, target_hash,
               target_order, created_at)
            values ('revision-target-valid', 'application-revision-schema-test',
                    'workshop', 'environment-target-a/base-target-a/GL001',
                    'environment-target-a', 'base-target-a',
                    'workshop-target-a', ?, 0, ?)
            """,
            (target_hash, timestamp),
        )
        database.execute(
            """
            insert into business_application_publication_target
              (id, application_publication_id, target_scope_type, target_key,
               environment_id, base_id, workshop_id, target_hash, created_at)
            values ('publication-target-valid',
                    'application-publication-schema-test', 'workshop',
                    'environment-target-a/base-target-a/GL001',
                    'environment-target-a', 'base-target-a',
                    'workshop-target-a', ?, ?)
            """,
            (target_hash, timestamp),
        )
        assert database.execute_one(
            """
            select count(*) as count
              from business_application_publication_target
             where application_publication_id =
                   'application-publication-schema-test'
            """
        ) == {"count": 1}
    finally:
        database.close()


def test_028_is_additive_and_legacy_report_is_queryable() -> None:
    migration_sql = (
        (default_migrations_dir() / "028_govern_builtin_readonly_tools.sql")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "\nupdate " not in migration_sql
    assert "\ndelete " not in migration_sql
    assert "\ninsert " not in migration_sql
    assert "drop table" not in migration_sql
    assert "drop column" not in migration_sql

    database = _migrated_database()
    try:
        rows = database.execute(
            """
            select metric, reference_count
              from builtin_tool_legacy_reference_report
             order by metric
            """
        )
        assert {row["metric"] for row in rows} == {
            "active_agent_name_binding",
            "all_agent_name_binding",
            "new_legacy_write_attempt",
            "recoverable_job_without_exact_snapshot",
        }
        assert all(int(row["reference_count"]) == 0 for row in rows)
    finally:
        database.close()
