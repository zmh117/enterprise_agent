from __future__ import annotations

import pytest

from app.bootstrap import build_test_container
from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.platform_config.infrastructure.repository import now_iso
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)


def _publish_builtin_tool(runtime: object, tool_identifier: str) -> dict[str, object]:
    runtime.database.execute(
        """
        insert into permission_policy
          (id, subject_type, subject_code, resource_type, resource_code,
           effect, action, status, priority, revision, created_at, updated_at)
        values ('test-user-local-admin-builtin-tools', 'user',
                'user_local_admin', 'builtin_tool', '*', 'allow', '*',
                'enabled', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """
    )
    handlers = runtime.platform_config_service.handlers
    handlers.reconcile(actor_id="user_local_admin")
    evidence = handlers.verify_payload(
        {
            "tool_identifier": tool_identifier,
            "handler_version": "1.0.0",
        },
        actor_id="user_local_admin",
    )
    release = handlers.publish_builtin_tool_payload(
        {
            "tool_identifier": tool_identifier,
            "handler_version": "1.0.0",
            "verification_id": evidence["id"],
            "idempotency_key": f"application-mapping-{tool_identifier}-v1",
        },
        actor_id="user_local_admin",
    )
    envelope = {
        "agent_publication_id": "agent_publication_default_v1",
        "tool_identifier": release["tool_identifier"],
        "tool_release_id": release["id"],
        "handler_version": release["handler_version"],
        "implementation_digest": release["implementation_digest"],
        "public_schema_hash": release["public_schema_hash"],
    }
    runtime.database.execute(
        """
        insert into agent_publication_builtin_tool
          (id, agent_publication_id, tool_identifier, tool_release_id,
           handler_version, implementation_digest, public_schema_hash,
           envelope_hash, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"agent_envelope_{tool_identifier}",
            envelope["agent_publication_id"],
            envelope["tool_identifier"],
            envelope["tool_release_id"],
            envelope["handler_version"],
            envelope["implementation_digest"],
            envelope["public_schema_hash"],
            snapshot_hash(envelope),
            now_iso(),
        ),
    )
    return release


def _published_database_resource(
    runtime: object,
    *,
    code: str,
    environment_id: str,
    base_id: str | None = None,
    scope_type: str = "base",
) -> str:
    timestamp = now_iso()
    resource_id = f"resource_{code}"
    revision_id = f"resource_revision_{code}_v1"
    verification_id = f"resource_verification_{code}_v1"
    content_hash = snapshot_hash({"resource": code, "revision": 1})
    runtime.database.execute(
        """
        insert into platform_resource
          (id, code, name, resource_kind, scope_type, environment_id,
           base_id, workshop_id, status, revision, created_by,
           created_at, updated_at)
        values (?, ?, ?, 'database', ?, ?, ?, null, 'enabled', 1,
                'user_local_admin', ?, ?)
        """,
        (
            resource_id,
            code,
            code,
            scope_type,
            environment_id,
            base_id,
            timestamp,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into platform_resource_verification
          (id, resource_id, draft_id, draft_revision, content_hash, status,
           provider_contract_version, checks_json, verified_by, verified_at)
        values (?, ?, null, 1, ?, 'PASSED', 'mysql_v1', '{}',
                'user_local_admin', ?)
        """,
        (verification_id, resource_id, content_hash, timestamp),
    )
    runtime.database.execute(
        """
        insert into platform_resource_revision
          (id, resource_id, revision, provider_type,
           provider_contract_version, config_json, secret_refs_json,
           content_hash, verification_id, status, published_by,
           published_at)
        values (?, ?, 1, 'mysql', 'mysql_v1', '{}', '{}', ?, ?,
                'PUBLISHED', 'user_local_admin', ?)
        """,
        (revision_id, resource_id, content_hash, verification_id, timestamp),
    )
    return revision_id


def _published_workshop_policy(
    runtime: object,
    *,
    workshop_id: str,
) -> str:
    timestamp = now_iso()
    policy_id = "workshop_policy_mapping_gl001"
    policy_revision_id = "workshop_policy_revision_mapping_gl001_v1"
    verification_id = "workshop_policy_verification_mapping_gl001_v1"
    content_hash = snapshot_hash(
        {
            "database_rule_enabled": True,
            "database_table_prefix": "GL001_",
            "redis_rule_enabled": False,
        }
    )
    runtime.database.execute(
        """
        insert into workshop_partition_policy
          (id, code, workshop_id, status, revision, created_by,
           created_at, updated_at)
        values (?, 'mapping-gl001', ?, 'enabled', 1, 'user_local_admin', ?, ?)
        """,
        (policy_id, workshop_id, timestamp, timestamp),
    )
    runtime.database.execute(
        """
        insert into workshop_partition_policy_verification
          (id, policy_id, draft_revision, content_hash, verifier_version,
           status, database_summary_json, redis_summary_json, verified_by,
           verified_at)
        values (?, ?, 1, ?, '1.0.0', 'PASSED', '{}', '{}',
                'user_local_admin', ?)
        """,
        (verification_id, policy_id, content_hash, timestamp),
    )
    runtime.database.execute(
        """
        insert into workshop_partition_policy_revision
          (id, policy_id, revision, database_rule_enabled,
           database_table_prefix, redis_rule_enabled, content_hash,
           verification_id, status, published_by, published_at)
        values (?, ?, 1, 1, 'GL001_', 0, ?, ?, 'PUBLISHED',
                'user_local_admin', ?)
        """,
        (
            policy_revision_id,
            policy_id,
            content_hash,
            verification_id,
            timestamp,
        ),
    )
    return policy_revision_id


def _publish_next_database_resource_revision(
    runtime: object,
    *,
    previous_revision_id: str,
) -> str:
    previous = runtime.database.execute_one(
        """
        select revision.resource_id, revision.provider_type,
               revision.provider_contract_version, resource.revision
          from platform_resource_revision revision
          join platform_resource resource on resource.id = revision.resource_id
         where revision.id = ?
        """,
        (previous_revision_id,),
    )
    assert previous is not None
    next_revision = int(previous["revision"]) + 1
    resource_id = str(previous["resource_id"])
    revision_id = f"{previous_revision_id}_next"
    verification_id = f"{revision_id}_verification"
    content_hash = snapshot_hash({"resource_id": resource_id, "revision": next_revision})
    timestamp = now_iso()
    runtime.database.execute(
        """
        insert into platform_resource_verification
          (id, resource_id, draft_id, draft_revision, content_hash, status,
           provider_contract_version, checks_json, verified_by, verified_at)
        values (?, ?, null, ?, ?, 'PASSED', ?, '{}', 'user_local_admin', ?)
        """,
        (
            verification_id,
            resource_id,
            next_revision,
            content_hash,
            previous["provider_contract_version"],
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into platform_resource_revision
          (id, resource_id, revision, provider_type,
           provider_contract_version, config_json, secret_refs_json,
           content_hash, verification_id, status, published_by, published_at)
        values (?, ?, ?, ?, ?, '{}', '{}', ?, ?, 'PUBLISHED',
                'user_local_admin', ?)
        """,
        (
            revision_id,
            resource_id,
            next_revision,
            previous["provider_type"],
            previous["provider_contract_version"],
            content_hash,
            verification_id,
            timestamp,
        ),
    )
    runtime.database.execute(
        "update platform_resource set revision = ?, updated_at = ? where id = ?",
        (next_revision, timestamp, resource_id),
    )
    return revision_id


def _publish_next_workshop_policy_revision(
    runtime: object,
    *,
    previous_revision_id: str,
) -> str:
    previous = runtime.database.execute_one(
        """
        select revision.policy_id, policy.revision
          from workshop_partition_policy_revision revision
          join workshop_partition_policy policy on policy.id = revision.policy_id
         where revision.id = ?
        """,
        (previous_revision_id,),
    )
    assert previous is not None
    next_revision = int(previous["revision"]) + 1
    policy_id = str(previous["policy_id"])
    revision_id = f"{previous_revision_id}_next"
    verification_id = f"{revision_id}_verification"
    content_hash = snapshot_hash(
        {"policy_id": policy_id, "revision": next_revision, "prefix": "GL001_V2_"}
    )
    timestamp = now_iso()
    runtime.database.execute(
        """
        insert into workshop_partition_policy_verification
          (id, policy_id, draft_revision, content_hash, verifier_version,
           status, database_summary_json, redis_summary_json, verified_by,
           verified_at)
        values (?, ?, ?, ?, '1.0.0', 'PASSED', '{}', '{}',
                'user_local_admin', ?)
        """,
        (
            verification_id,
            policy_id,
            next_revision,
            content_hash,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        insert into workshop_partition_policy_revision
          (id, policy_id, revision, database_rule_enabled,
           database_table_prefix, redis_rule_enabled, content_hash,
           verification_id, status, published_by, published_at)
        values (?, ?, ?, 1, 'GL001_V2_', 0, ?, ?, 'PUBLISHED',
                'user_local_admin', ?)
        """,
        (
            revision_id,
            policy_id,
            next_revision,
            content_hash,
            verification_id,
            timestamp,
        ),
    )
    runtime.database.execute(
        """
        update workshop_partition_policy
           set revision = ?, updated_at = ?
         where id = ?
        """,
        (next_revision, timestamp, policy_id),
    )
    return revision_id


def test_application_draft_and_publish_freeze_one_to_many_resource_mappings() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    release = _publish_builtin_tool(runtime, "query_database")
    environment = runtime.platform_config_service.upsert_environment(
        {"code": "mapping-test"},
        actor_id="user_local_admin",
    )
    base = runtime.platform_config_service.upsert_base(
        {
            "environment_code": "mapping-test",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    workshop = runtime.platform_config_service.upsert_workshop(
        {
            "environment_code": "mapping-test",
            "base_code": "guanlan",
            "code": "GL001",
        },
        actor_id="user_local_admin",
    )
    cloud_revision_id = _published_database_resource(
        runtime,
        code="mapping_database_cloud",
        environment_id=str(environment["id"]),
        base_id=str(base["id"]),
    )
    edge_revision_id = _published_database_resource(
        runtime,
        code="mapping_database_edge",
        environment_id=str(environment["id"]),
        base_id=str(base["id"]),
    )
    policy_revision_id = _published_workshop_policy(
        runtime,
        workshop_id=str(workshop["id"]),
    )

    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="builtin-mapping-test",
        name="Built-in Mapping Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [
        {
            "target_scope_type": "workshop",
            "environment_code": "mapping-test",
            "base_code": "guanlan",
            "workshop_code": "GL001",
        }
    ]
    payload["builtin_tools"] = [
        {
            "tool_release_id": release["id"],
            "resources": [
                {
                    "resource_slot": "database",
                    "target_scope_type": "workshop",
                    "environment_code": "mapping-test",
                    "base_code": "guanlan",
                    "workshop_code": "GL001",
                    "placement": "edge",
                    "resource_revision_id": edge_revision_id,
                    "workshop_partition_policy_revision_id": policy_revision_id,
                    "loki_scope_policy_revision_id": "",
                },
                {
                    "resource_slot": "database",
                    "target_scope_type": "workshop",
                    "environment_code": "mapping-test",
                    "base_code": "guanlan",
                    "workshop_code": "GL001",
                    "placement": "cloud",
                    "resource_revision_id": cloud_revision_id,
                    "workshop_partition_policy_revision_id": policy_revision_id,
                    "loki_scope_policy_revision_id": "",
                },
            ],
        }
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="builtin-mapping-test",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    assert [item["placement"] for item in revision["builtin_tools"][0]["resources"]] == [
        "cloud",
        "edge",
    ]
    assert {item["resource_revision_id"] for item in revision["builtin_tools"][0]["resources"]} == {
        cloud_revision_id,
        edge_revision_id,
    }
    assert {item["workshop_id"] for item in revision["builtin_tools"][0]["resources"]} == {
        workshop["id"]
    }
    assert (
        runtime.database.execute_one(
            """
        select count(*) as count
          from business_application_revision_builtin_tool_resource mapping
          join business_application_revision_builtin_tool tool
            on tool.id = mapping.application_revision_tool_id
         where tool.application_revision_id = ?
        """,
            (revision["id"],),
        )["count"]
        == 2
    )

    next_policy_revision_id = _publish_next_workshop_policy_revision(
        runtime,
        previous_revision_id=policy_revision_id,
    )
    inconsistent_application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="builtin-mapping-inconsistent-policy",
        name="Built-in Mapping Inconsistent Policy",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    inconsistent_payload = draft_payload()
    inconsistent_payload["target_paths"] = payload["target_paths"]
    inconsistent_payload["builtin_tools"] = [
        {
            "tool_release_id": release["id"],
            "resources": [
                dict(payload["builtin_tools"][0]["resources"][0]),
                {
                    **payload["builtin_tools"][0]["resources"][1],
                    "workshop_partition_policy_revision_id": next_policy_revision_id,
                },
            ],
        }
    ]
    inconsistent_revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="builtin-mapping-inconsistent-policy",
        expected_revision=int(inconsistent_application["revision"]),
        payload=inconsistent_payload,
    )
    with pytest.raises(NonRetryableExecutionError) as inconsistent_policy:
        runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="builtin-mapping-inconsistent-policy",
            revision_id=str(inconsistent_revision["id"]),
        )
    assert inconsistent_policy.value.error_code == "builtin_tool_partition_policy_inconsistent"

    validated = runtime.business_application_service.validate(
        actor_id="user_local_admin",
        code="builtin-mapping-test",
        revision_id=str(revision["id"]),
    )
    assert validated["validation"] == {"valid": True, "errors": []}
    runtime.database.execute(
        """
        update workshop_partition_policy_revision
           set status = 'DISABLED'
         where id = ?
        """,
        (policy_revision_id,),
    )
    with pytest.raises(NonRetryableExecutionError) as stale_policy:
        runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="builtin-mapping-test",
            revision_id=str(revision["id"]),
        )
    assert stale_policy.value.error_code == "builtin_tool_policy_not_published"
    runtime.database.execute(
        """
        update workshop_partition_policy_revision
           set status = 'PUBLISHED'
         where id = ?
        """,
        (policy_revision_id,),
    )
    publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="builtin-mapping-test",
        revision_id=str(revision["id"]),
    )
    repeated = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="builtin-mapping-test",
        revision_id=str(revision["id"]),
    )

    assert repeated["id"] == publication["id"]
    frozen = publication["snapshot"]["builtin_tools"]
    assert frozen[0]["tool_release_id"] == release["id"]
    assert frozen[0]["implementation_digest"] == release["implementation_digest"]
    assert [item["placement"] for item in frozen[0]["resources"]] == [
        "cloud",
        "edge",
    ]
    assert {item["workshop_partition_policy_revision_id"] for item in frozen[0]["resources"]} == {
        policy_revision_id
    }
    assert (
        runtime.database.execute_one(
            """
        select count(*) as count
          from business_application_publication_builtin_tool_resource mapping
          join business_application_publication_builtin_tool tool
            on tool.id = mapping.application_tool_id
         where tool.application_publication_id = ?
        """,
            (publication["id"],),
        )["count"]
        == 2
    )
    frozen_resolution_set = publication["snapshot"]["builtin_tool_resolution_set"]
    assert frozen_resolution_set["resolution_count"] == 2
    assert {item["resource_revision_id"] for item in frozen_resolution_set["resolutions"]} == {
        cloud_revision_id,
        edge_revision_id,
    }
    assert {
        item["workshop_partition_policy_revision_id"]
        for item in frozen_resolution_set["resolutions"]
    } == {policy_revision_id}
    assert all(
        len(str(item["resolution_hash"])) == 64 for item in frozen_resolution_set["resolutions"]
    )
    persisted_set = runtime.database.execute_one(
        """
        select resolution_count, resolution_set_hash
          from business_application_publication_builtin_tool_resolution_set
         where application_publication_id = ?
        """,
        (publication["id"],),
    )
    assert persisted_set == {
        "resolution_count": 2,
        "resolution_set_hash": frozen_resolution_set["resolution_set_hash"],
    }
    frozen_resolution_rows = runtime.database.execute(
        """
        select resolution_order, resolution_hash, resource_revision_id,
               workshop_partition_policy_revision_id
          from business_application_publication_builtin_tool_resolution
         where application_publication_id = ?
         order by resolution_order
        """,
        (publication["id"],),
    )

    next_resource_revision_id = _publish_next_database_resource_revision(
        runtime,
        previous_revision_id=cloud_revision_id,
    )
    assert next_resource_revision_id not in {
        item["resource_revision_id"] for item in frozen_resolution_set["resolutions"]
    }
    assert next_policy_revision_id not in {
        item["workshop_partition_policy_revision_id"]
        for item in frozen_resolution_set["resolutions"]
    }
    assert (
        runtime.database.execute(
            """
        select resolution_order, resolution_hash, resource_revision_id,
               workshop_partition_policy_revision_id
          from business_application_publication_builtin_tool_resolution
         where application_publication_id = ?
         order by resolution_order
        """,
            (publication["id"],),
        )
        == frozen_resolution_rows
    )
    after_new_revisions = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="builtin-mapping-test",
        revision_id=str(revision["id"]),
    )
    assert after_new_revisions["id"] == publication["id"]
    assert after_new_revisions["snapshot"]["builtin_tool_resolution_set"] == frozen_resolution_set
    runtime.database.close()


def test_application_draft_rejects_release_outside_exact_agent_envelope() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    handlers = runtime.platform_config_service.handlers
    handlers.reconcile(actor_id="user_local_admin")
    evidence = handlers.verify_payload(
        {
            "tool_identifier": "query_database",
            "handler_version": "1.0.0",
        },
        actor_id="user_local_admin",
    )
    release = handlers.publish_builtin_tool_payload(
        {
            "tool_identifier": "query_database",
            "handler_version": "1.0.0",
            "verification_id": evidence["id"],
            "idempotency_key": "application-mapping-outside-envelope-v1",
        },
        actor_id="user_local_admin",
    )
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="outside-agent-envelope",
        name="Outside Agent Envelope",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["builtin_tools"] = [{"tool_release_id": release["id"], "resources": []}]

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.save_draft(
            actor_id="user_local_admin",
            code="outside-agent-envelope",
            expected_revision=int(application["revision"]),
            payload=payload,
        )

    assert rejected.value.error_code == "builtin_tool_resource_mapping_invalid"
    assert (
        runtime.database.execute_one(
            """
        select count(*) as count
          from business_application_revision_builtin_tool
        """
        )["count"]
        == 0
    )
    runtime.database.close()


def _target_path(
    scope_type: str,
    environment_code: str,
    base_code: str = "",
    workshop_code: str = "",
) -> dict[str, str]:
    return {
        "target_scope_type": scope_type,
        "environment_code": environment_code,
        "base_code": base_code,
        "workshop_code": workshop_code,
    }


def _resource_mapping(
    *,
    scope_type: str,
    environment_code: str,
    resource_revision_id: str,
    base_code: str = "",
) -> dict[str, str]:
    return {
        "resource_slot": "database",
        "target_scope_type": scope_type,
        "environment_code": environment_code,
        "base_code": base_code,
        "workshop_code": "",
        "placement": "",
        "resource_revision_id": resource_revision_id,
        "workshop_partition_policy_revision_id": "",
        "loki_scope_policy_revision_id": "",
    }


def test_application_targets_accept_only_enabled_real_leaves() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = runtime.business_application_service.builtin_tool_composition_service
    environment_leaf = runtime.platform_config_service.upsert_environment(
        {"code": "target-environment-leaf"},
        actor_id="user_local_admin",
    )
    targets = service.prepare_targets([_target_path("environment", "target-environment-leaf")])
    assert targets[0]["environment_id"] == environment_leaf["id"]

    runtime.platform_config_service.upsert_base(
        {
            "environment_code": "target-environment-leaf",
            "code": "base-leaf",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    with pytest.raises(NonRetryableExecutionError) as non_leaf_environment:
        service.prepare_targets([_target_path("environment", "target-environment-leaf")])
    assert non_leaf_environment.value.error_code == "builtin_tool_application_target_invalid"
    base_target = service.prepare_targets(
        [_target_path("base", "target-environment-leaf", "base-leaf")]
    )
    assert base_target[0]["target_scope_type"] == "base"

    runtime.platform_config_service.upsert_workshop(
        {
            "environment_code": "target-environment-leaf",
            "base_code": "base-leaf",
            "code": "GL001",
        },
        actor_id="user_local_admin",
    )
    with pytest.raises(NonRetryableExecutionError) as non_leaf_base:
        service.prepare_targets([_target_path("base", "target-environment-leaf", "base-leaf")])
    assert non_leaf_base.value.error_code == "builtin_tool_application_target_invalid"
    workshop_target = service.prepare_targets(
        [
            _target_path(
                "workshop",
                "target-environment-leaf",
                "base-leaf",
                "GL001",
            )
        ]
    )
    assert workshop_target[0]["target_scope_type"] == "workshop"
    runtime.database.close()


def test_application_publish_rejects_missing_required_target_slot() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    release = _publish_builtin_tool(runtime, "query_database")
    runtime.platform_config_service.upsert_environment(
        {"code": "target-missing-slot"},
        actor_id="user_local_admin",
    )
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="target-missing-slot",
        name="Target Missing Slot",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [_target_path("environment", "target-missing-slot")]
    payload["builtin_tools"] = [{"tool_release_id": release["id"], "resources": []}]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="target-missing-slot",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="target-missing-slot",
            revision_id=str(revision["id"]),
        )
    assert rejected.value.error_code == "builtin_tool_resource_mapping_missing"
    assert rejected.value.diagnostics["candidate_count"] == 0
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from business_application_publication
         where application_id = ?
        """,
        (application["id"],),
    ) == {"count": 0}
    runtime.database.close()


def test_application_publish_rejects_environment_base_mapping_overlap() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    release = _publish_builtin_tool(runtime, "query_database")
    environment = runtime.platform_config_service.upsert_environment(
        {"code": "target-overlap"},
        actor_id="user_local_admin",
    )
    base = runtime.platform_config_service.upsert_base(
        {
            "environment_code": "target-overlap",
            "code": "base-a",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    environment_resource = _published_database_resource(
        runtime,
        code="overlap_environment_database",
        environment_id=str(environment["id"]),
        scope_type="environment",
    )
    base_resource = _published_database_resource(
        runtime,
        code="overlap_base_database",
        environment_id=str(environment["id"]),
        base_id=str(base["id"]),
    )
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="target-overlap",
        name="Target Overlap",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [_target_path("base", "target-overlap", "base-a")]
    payload["builtin_tools"] = [
        {
            "tool_release_id": release["id"],
            "resources": [
                _resource_mapping(
                    scope_type="environment",
                    environment_code="target-overlap",
                    resource_revision_id=environment_resource,
                ),
                _resource_mapping(
                    scope_type="base",
                    environment_code="target-overlap",
                    base_code="base-a",
                    resource_revision_id=base_resource,
                ),
            ],
        }
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="target-overlap",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="target-overlap",
            revision_id=str(revision["id"]),
        )
    assert rejected.value.error_code == "builtin_tool_resource_mapping_overlap"
    assert rejected.value.diagnostics["candidate_count"] == 2
    runtime.database.close()


def test_application_publish_rejects_mapping_outside_explicit_targets() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    release = _publish_builtin_tool(runtime, "query_database")
    environment = runtime.platform_config_service.upsert_environment(
        {"code": "target-boundary"},
        actor_id="user_local_admin",
    )
    bases = {}
    for base_code in ("base-a", "base-b"):
        bases[base_code] = runtime.platform_config_service.upsert_base(
            {
                "environment_code": "target-boundary",
                "code": base_code,
                "engine": "mysql",
            },
            actor_id="user_local_admin",
        )
    resource = _published_database_resource(
        runtime,
        code="outside_target_database",
        environment_id=str(environment["id"]),
        base_id=str(bases["base-b"]["id"]),
    )
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="target-boundary",
        name="Target Boundary",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [_target_path("base", "target-boundary", "base-a")]
    payload["builtin_tools"] = [
        {
            "tool_release_id": release["id"],
            "resources": [
                _resource_mapping(
                    scope_type="base",
                    environment_code="target-boundary",
                    base_code="base-b",
                    resource_revision_id=resource,
                )
            ],
        }
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="target-boundary",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="target-boundary",
            revision_id=str(revision["id"]),
        )
    assert rejected.value.error_code == "builtin_tool_resource_mapping_overlap"
    runtime.database.close()


def test_target_matrix_rejects_global_environment_loki_overlap() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    runtime.platform_config_service.upsert_environment(
        {"code": "target-loki-overlap"},
        actor_id="user_local_admin",
    )
    service = runtime.business_application_service.builtin_tool_composition_service
    targets = service.prepare_targets([_target_path("environment", "target-loki-overlap")])
    environment_id = str(targets[0]["environment_id"])
    mappings = [
        {
            "resource_slot": "loki",
            "target_scope_type": "global",
            "target_key": "global",
            "environment_id": None,
            "base_id": None,
            "workshop_id": None,
            "placement": None,
            "resource_revision_id": "resource_revision_global_loki",
            "workshop_partition_policy_revision_id": "",
            "loki_scope_policy_revision_id": "policy_global_loki",
            "mapping_hash": "global-loki-mapping",
        },
        {
            "resource_slot": "loki",
            "target_scope_type": "environment",
            "target_key": f"environment:{environment_id}",
            "environment_id": environment_id,
            "base_id": None,
            "workshop_id": None,
            "placement": None,
            "resource_revision_id": "resource_revision_environment_loki",
            "workshop_partition_policy_revision_id": "",
            "loki_scope_policy_revision_id": "policy_environment_loki",
            "mapping_hash": "environment-loki-mapping",
        },
    ]

    with pytest.raises(NonRetryableExecutionError) as rejected:
        service.validate_target_matrix(
            targets=targets,
            tools=[
                {
                    "tool_identifier": "query_loki",
                    "tool_release_id": "release-query-loki",
                    "handler_version": "1.0.0",
                    "implementation_digest": "digest-query-loki",
                    "resources": mappings,
                }
            ],
        )
    assert rejected.value.error_code == "builtin_tool_resource_mapping_overlap"
    assert rejected.value.diagnostics["candidate_count"] == 2
    runtime.database.close()


def test_application_publish_rejects_resource_revision_disabled_after_draft() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    release = _publish_builtin_tool(runtime, "query_database")
    environment = runtime.platform_config_service.upsert_environment(
        {"code": "target-stale-resource"},
        actor_id="user_local_admin",
    )
    resource = _published_database_resource(
        runtime,
        code="stale_database",
        environment_id=str(environment["id"]),
        scope_type="environment",
    )
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="target-stale-resource",
        name="Target Stale Resource",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [_target_path("environment", "target-stale-resource")]
    payload["builtin_tools"] = [
        {
            "tool_release_id": release["id"],
            "resources": [
                _resource_mapping(
                    scope_type="environment",
                    environment_code="target-stale-resource",
                    resource_revision_id=resource,
                )
            ],
        }
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="target-stale-resource",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    runtime.database.execute(
        "update platform_resource_revision set status = 'DISABLED' where id = ?",
        (resource,),
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="target-stale-resource",
            revision_id=str(revision["id"]),
        )
    assert rejected.value.error_code == "builtin_tool_resource_mapping_missing"
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from business_application_publication
         where application_id = ?
        """,
        (application["id"],),
    ) == {"count": 0}
    runtime.database.close()


def test_application_management_catalog_exposes_only_exact_safe_composition_facts() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    release = _publish_builtin_tool(runtime, "query_database")
    environment = runtime.platform_config_service.upsert_environment(
        {"code": "catalog-safe"},
        actor_id="user_local_admin",
    )
    base = runtime.platform_config_service.upsert_base(
        {
            "environment_code": "catalog-safe",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    workshop = runtime.platform_config_service.upsert_workshop(
        {
            "environment_code": "catalog-safe",
            "base_code": "guanlan",
            "code": "GL001",
        },
        actor_id="user_local_admin",
    )
    resource_revision_id = _published_database_resource(
        runtime,
        code="catalog_safe_database",
        environment_id=str(environment["id"]),
        base_id=str(base["id"]),
    )
    policy_revision_id = _published_workshop_policy(
        runtime,
        workshop_id=str(workshop["id"]),
    )
    runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="catalog-safe-app",
        name="Catalog Safe App",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )

    catalog = runtime.business_application_service.catalog(
        actor_id="user_local_admin",
        code="catalog-safe-app",
    )

    envelope = catalog["builtin_tools_by_agent_publication"][
        "agent_publication_default_v1"
    ]
    selected_release = next(
        item for item in envelope if item["tool_release_id"] == release["id"]
    )
    assert selected_release["tool_identifier"] == "query_database"
    assert selected_release["selectable"] is True
    assert selected_release["resource_slots"][0]["code"] == "database"
    assert set(selected_release) == {
        "tool_identifier",
        "tool_release_id",
        "release_revision",
        "tool_semantic_version",
        "handler_version",
        "implementation_digest",
        "public_schema_hash",
        "display_name",
        "model_description",
        "resource_slots",
        "release_status",
        "installation_status",
        "selectable",
    }

    resource = next(
        item
        for item in catalog["resource_revisions"]
        if item["resource_revision_id"] == resource_revision_id
    )
    assert set(resource) == {
        "resource_revision_id",
        "resource_revision",
        "resource_code",
        "resource_name",
        "resource_kind",
        "scope_type",
        "environment_code",
        "base_code",
        "workshop_code",
        "content_hash",
    }
    assert not {"config", "config_json", "secret_refs", "base_url"}.intersection(
        resource
    )
    assert any(
        item["policy_revision_id"] == policy_revision_id
        for item in catalog["workshop_policy_revisions"]
    )
    assert {
        (
            item["target_scope_type"],
            item["environment_code"],
            item["base_code"],
            item["workshop_code"],
        )
        for item in catalog["target_paths"]
        if item["environment_code"] == "catalog-safe"
    } == {("workshop", "catalog-safe", "guanlan", "GL001")}
    runtime.database.close()
