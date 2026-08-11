from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.admin.domain import ADMIN_CAPABILITIES
from app.modules.agent_config.application.builtin_tool_envelope import (
    AgentBuiltinToolEnvelopeService,
)
from app.modules.agent.infrastructure.tool_manifest import (
    TOOL_DEFINITIONS,
)
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    ResourceSlotDefinition,
    build_builtin_handler_registry,
)
from app.modules.platform_config.application.handler_governance import (
    HandlerGovernanceService,
)
from app.modules.platform_config.infrastructure.handler_governance_repository import (
    HandlerGovernanceRepository,
)
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.modules.permission.application.permission_service import PermissionService
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.exceptions import ToolPolicyError
from backend.tests.helpers import container


def test_builtin_tool_management_permissions_are_fine_grained_and_independent() -> None:
    by_code = {item.code: item for item in ADMIN_CAPABILITIES}
    expected = {
        "builtin_tools.read": "read",
        "builtin_tools.reconcile": "reconcile",
        "builtin_tools.verify": "verify",
        "builtin_tools.publish": "publish",
        "builtin_tools.lifecycle": "lifecycle",
    }
    assert expected.keys() <= by_code.keys()
    for code, action in expected.items():
        capability = by_code[code]
        assert capability.resource_type == "builtin_tool"
        assert capability.resource_code == "*"
        assert capability.action == action
        assert not set(capability.dependencies).intersection(
            {
                "tools.manage",
                "agents.publish",
                "applications.publish",
            }
        )
    assert by_code["builtin_tools.read"].dependencies == ()
    for code in expected.keys() - {"builtin_tools.read"}:
        assert by_code[code].dependencies == ("builtin_tools.read",)


def test_builtin_tool_role_binding_closes_only_its_read_dependency() -> None:
    runtime = container()
    try:
        created = runtime.authorization_center_service.create_role(
            actor_id="user_local_admin",
            code="builtin-tool-verifier",
            name="内置工具验证员",
            description="",
            purpose_tags=["平台治理"],
        )
        result = runtime.authorization_center_service.replace_admin_capabilities(
            actor_id="user_local_admin",
            role_id=str(created["role"]["id"]),
            expected_revision=1,
            bindings=[
                {
                    "capability_code": "builtin_tools.verify",
                    "resource_code": "*",
                }
            ],
            confirmed=True,
            reason="验证内置工具",
        )
        assert {item["capability_code"] for item in result["bindings"]} == {
            "builtin_tools.read",
            "builtin_tools.verify",
        }
    finally:
        runtime.database.close()


def test_runtime_tool_use_grant_targets_stable_identifier_and_keeps_data_scope(
    monkeypatch,
) -> None:
    runtime = container()
    service = PermissionService(
        ConfigurationRepository(runtime.database),
        authorization_evaluator=runtime.authorization_evaluator,
    )
    try:
        monkeypatch.setattr(service, "_is_allowed", lambda **_kwargs: True)

        class Decision:
            allowed = True
            reason = "allowed"

        monkeypatch.setattr(
            service.authorization_evaluator,
            "decide_platform_scope",
            lambda **_kwargs: Decision(),
        )
        service.assert_builtin_tool_allowed(
            user_id="user-local-test",
            tool_identifier="query_database",
            project_code="default",
            scope={"environment": "sanjiu", "base": "guanlan"},
        )

        with pytest.raises(ToolPolicyError, match="stable Identifier"):
            service.assert_builtin_tool_allowed(
                user_id="user-local-test",
                tool_identifier="builtin_tool_release_fake",
                project_code="default",
                scope={"environment": "sanjiu", "base": "guanlan"},
            )

        class Denied:
            allowed = False
            reason = "scope_not_granted"

        monkeypatch.setattr(
            service.authorization_evaluator,
            "decide_platform_scope",
            lambda **_kwargs: Denied(),
        )
        with pytest.raises(ToolPolicyError, match="Platform scope denied"):
            service.assert_builtin_tool_allowed(
                user_id="user-local-test",
                tool_identifier="query_database",
                project_code="default",
                scope={"environment": "sanjiu", "base": "forbidden"},
            )
    finally:
        runtime.database.close()


def test_builtin_handler_registry_is_stable_versioned_and_schema_complete() -> None:
    first = build_builtin_handler_registry()
    second = build_builtin_handler_registry()
    definitions = first.definitions()

    assert {item.handler_id for item in definitions} == set(TOOL_DEFINITIONS)
    assert all(item.handler_version == "1.0.0" for item in definitions)
    assert {(item.handler_id, item.implementation_digest) for item in definitions} == {
        (item.handler_id, item.implementation_digest) for item in second.definitions()
    }
    from app.modules.agent.infrastructure.mcp_tool_registry import (
        ToolRegistry,
    )

    assert {item.handler_id for item in definitions} == set(ToolRegistry.READONLY_TOOLS)
    for definition in definitions:
        assert definition.input_schema == TOOL_DEFINITIONS[definition.handler_id]["schema"]
        assert definition.output_schema["type"] == "object"
        assert definition.risk_level in {"LOW", "MEDIUM", "HIGH"}
        assert definition.required_permissions
        assert len(definition.implementation_digest) == 64
        for slot in definition.resource_slots:
            assert slot.resource_kind in {"database", "redis", "loki"}

    query_database = first.require("query_database", "1.0.0")
    assert query_database.visibility == "application"
    assert query_database in first.application_catalog()
    assert {item.handler_id for item in first.application_catalog()} == set(TOOL_DEFINITIONS)


def test_builtin_tool_manifest_contract_has_stable_identity_hashes_and_verifier_plan() -> None:
    first = build_builtin_handler_registry()
    second = build_builtin_handler_registry()

    for definition in first.definitions():
        same = second.require(
            definition.tool_identifier,
            definition.handler_version,
        )
        assert definition.tool_identifier == definition.handler_id
        assert definition.tool_semantic_version == "1.0.0"
        assert len(definition.public_schema_hash) == 64
        assert len(definition.manifest_hash) == 64
        assert definition.public_schema_hash == same.public_schema_hash
        assert definition.manifest_hash == same.manifest_hash
        assert definition.verifier_plan.verifier_id
        assert definition.verifier_plan.verifier_version == "1.0.0"
        assert definition.verifier_plan.checks
        assert definition.verifier_plan.max_duration_ms > 0
        assert definition.verifier_plan.max_result_bytes > 0
        assert definition.safety_boundary.read_only is True
        assert definition.safety_boundary.allowed_effects
        assert definition.safety_boundary.required_guards
        manifest = definition.manifest()
        assert manifest["tool_identifier"] == definition.tool_identifier
        assert manifest["tool_semantic_version"] == "1.0.0"
        assert manifest["handler_version"] == "1.0.0"
        assert manifest["public_schema_hash"] == definition.public_schema_hash
        assert manifest["verifier_plan"] == definition.verifier_plan.public()
        assert manifest["safety_boundary"] == definition.safety_boundary.public()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda definition: replace(
            definition,
            input_schema={
                **definition.input_schema,
                "properties": {
                    **definition.input_schema["properties"],
                    "arbitrary_target": {"type": "string"},
                },
            },
        ),
        lambda definition: replace(definition, risk_level="HIGH"),
        lambda definition: replace(
            definition,
            required_permissions=(
                *definition.required_permissions,
                "tool_resources.read",
            ),
        ),
        lambda definition: replace(
            definition,
            resource_slots=(
                ResourceSlotDefinition(
                    code="database",
                    resource_kind="database",
                    allowed_scope_types=(
                        "environment",
                        "base",
                        "workshop",
                    ),
                ),
            ),
        ),
    ],
)
def test_reusing_identifier_for_safety_boundary_expansion_is_rejected(mutate) -> None:
    definition = build_builtin_handler_registry().require(
        "get_schema_directory",
        "1.0.0",
    )
    if definition.resource_slots:
        definition = replace(
            definition,
            resource_slots=(
                replace(
                    definition.resource_slots[0],
                    allowed_scope_types=("base",),
                ),
            ),
        )
    expanded = mutate(definition)

    with pytest.raises(HandlerRegistryError, match="stable Identifier"):
        HandlerRegistry.assert_no_safety_boundary_expansion(
            definition,
            expanded,
        )


@pytest.mark.parametrize(
    "identifier",
    ["cap__ones__work_item__search", "legacy-v1"],
)
def test_builtin_tool_manifest_rejects_reserved_identifier_namespace(
    identifier: str,
) -> None:
    definition = build_builtin_handler_registry().require(
        "query_database",
        "1.0.0",
    )
    with pytest.raises(HandlerRegistryError, match="reserved"):
        HandlerRegistry((replace(definition, handler_id=identifier),))


def test_builtin_tool_manifest_rejects_non_semver_tool_or_handler_version() -> None:
    definition = build_builtin_handler_registry().require(
        "query_database",
        "1.0.0",
    )
    with pytest.raises(HandlerRegistryError, match="semantic version"):
        HandlerRegistry((replace(definition, tool_semantic_version="v1"),))
    with pytest.raises(HandlerRegistryError, match="Handler version"):
        HandlerRegistry((replace(definition, handler_version="latest"),))


@pytest.mark.parametrize(
    "payload",
    [
        {"python": "print('unsafe')"},
        {"metadata": {"script": "run.sh"}},
        {"sql_template": "select * from anything"},
        {"implementation": {"source": "dynamic"}},
        {"metadata": {"entry": "https://untrusted.invalid/handler"}},
    ],
)
def test_registry_rejects_database_dynamic_implementation_payload(
    payload: dict[str, object],
) -> None:
    with pytest.raises(HandlerRegistryError):
        HandlerRegistry.reject_dynamic_governance_payload(payload)


def test_handler_installation_publication_and_status_are_governed() -> None:
    runtime = container()
    service = runtime.platform_config_service.handlers
    try:
        summary = service.reconcile(actor_id="admin")
        assert summary == {
            "installed": len(TOOL_DEFINITIONS),
            "drifted": 0,
            "missing": 0,
        }
        assert service.reconcile(actor_id="admin") == summary
        assert runtime.database.execute_one(
            "select count(*) as count from builtin_tool_manifest_projection"
        ) == {"count": len(TOOL_DEFINITIONS)}
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from builtin_tool_installation
             where installation_status = 'INSTALLED'
            """
        ) == {"count": len(TOOL_DEFINITIONS)}
        assert runtime.database.execute_one(
            "select count(*) as count from builtin_tool_release"
        ) == {"count": 0}
        publication = service.publish_payload(
            {
                "handler_id": "query_loki",
                "handler_version": "1.0.0",
            },
            actor_id="admin",
        )
        assert publication["status"] == "PUBLISHED"
        disabled = service.set_publication_status(
            str(publication["id"]),
            "disabled",
            actor_id="admin",
        )
        assert disabled["status"] == "DISABLED"
        archived = service.set_publication_status(
            str(publication["id"]),
            "archived",
            actor_id="admin",
        )
        assert archived["status"] == "ARCHIVED"
        with pytest.raises(
            NonRetryableExecutionError,
            match="cannot be re-enabled",
        ):
            service.set_publication_status(
                str(publication["id"]),
                "published",
                actor_id="admin",
            )
        with pytest.raises(
            NonRetryableExecutionError,
            match="already governed",
        ):
            service.publish_payload(
                {
                    "handler_id": "query_loki",
                    "handler_version": "1.0.0",
                },
                actor_id="admin",
            )
    finally:
        runtime.database.close()


def test_same_handler_version_digest_drift_blocks_publication() -> None:
    runtime = container()
    original = build_builtin_handler_registry()
    original_service = runtime.platform_config_service.handlers
    try:
        original_service.reconcile(actor_id="admin")
        definition = original.require("query_redis_get", "1.0.0")
        drifted_registry = HandlerRegistry(
            (
                replace(
                    definition,
                    implementation_key=(definition.implementation_key + ":changed"),
                ),
            )
        )
        drifted_service = HandlerGovernanceService(
            HandlerGovernanceRepository(runtime.database),
            runtime.platform_config_service.repository,
            runtime.platform_config_service.permission_service,
            registry=drifted_registry,
        )
        summary = drifted_service.reconcile(actor_id="admin")
        assert summary["drifted"] == 1
        assert summary["missing"] == len(TOOL_DEFINITIONS) - 1
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from builtin_tool_installation
             where installation_status = 'MISSING'
            """
        ) == {"count": len(TOOL_DEFINITIONS) - 1}
        installation = drifted_service.repository.get_installation(
            "query_redis_get",
            "1.0.0",
        )
        assert installation["installation_status"] == "DRIFTED"
        builtin_installation = runtime.database.execute_one(
            """
            select installation_status, implementation_digest
              from builtin_tool_installation
             where tool_identifier = 'query_redis_get'
               and handler_version = '1.0.0'
            """
        )
        assert builtin_installation is not None
        assert builtin_installation["installation_status"] == "DRIFTED"
        assert builtin_installation["implementation_digest"] == definition.implementation_digest
        with pytest.raises(
            NonRetryableExecutionError,
            match="digest drifted",
        ):
            drifted_service.verify_payload(
                {
                    "tool_identifier": "query_redis_get",
                    "handler_version": "1.0.0",
                },
                actor_id="admin",
            )
        with pytest.raises(
            NonRetryableExecutionError,
            match="digest drifted",
        ):
            drifted_service.publish_payload(
                {
                    "handler_id": "query_redis_get",
                    "handler_version": "1.0.0",
                },
                actor_id="admin",
            )
    finally:
        runtime.database.close()


def test_fixed_builtin_tool_verifier_persists_bounded_exact_idempotent_evidence() -> None:
    runtime = container()
    service = runtime.platform_config_service.handlers
    try:
        service.reconcile(actor_id="admin")
        payload = {
            "tool_identifier": "query_database",
            "handler_version": "1.0.0",
        }
        first = service.verify_payload(
            payload,
            actor_id="admin",
            correlation_id="verifier-test",
        )
        second = service.verify_payload(
            payload,
            actor_id="admin",
            correlation_id="verifier-test-repeated",
        )

        definition = build_builtin_handler_registry().require(
            "query_database",
            "1.0.0",
        )
        assert second["id"] == first["id"]
        assert first["status"] == "PASSED"
        assert first["tool_identifier"] == "query_database"
        assert first["handler_version"] == "1.0.0"
        assert first["implementation_digest"] == definition.implementation_digest
        assert first["verifier_version"] == definition.verifier_plan.verifier_version
        assert len(first["normalized_input_hash"]) == 64
        assert first["result_summary"] == {
            "check_count": len(definition.verifier_plan.checks),
            "checks": [
                {"code": code, "status": "PASSED"} for code in definition.verifier_plan.checks
            ],
            "truncated": False,
        }
        assert runtime.database.execute_one(
            "select count(*) as count from builtin_tool_verification"
        ) == {"count": 1}
        assert runtime.database.execute_one(
            "select count(*) as count from builtin_tool_release"
        ) == {"count": 0}

        with pytest.raises(
            NonRetryableExecutionError,
            match="manual verification",
        ):
            service.verify_payload(
                {**payload, "status": "PASSED"},
                actor_id="admin",
            )
    finally:
        runtime.database.close()


def test_builtin_tool_release_publish_is_evidence_gated_exact_and_idempotent() -> None:
    runtime = container()
    service = runtime.platform_config_service.handlers
    try:
        service.reconcile(actor_id="admin")
        evidence = service.verify_payload(
            {
                "tool_identifier": "query_database",
                "handler_version": "1.0.0",
            },
            actor_id="admin",
        )
        payload = {
            "tool_identifier": "query_database",
            "handler_version": "1.0.0",
            "verification_id": evidence["id"],
            "idempotency_key": "publish-query-database-v1",
        }
        first = service.publish_builtin_tool_payload(
            payload,
            actor_id="admin",
            correlation_id="publish-test",
        )
        second = service.publish_builtin_tool_payload(
            payload,
            actor_id="admin",
            correlation_id="publish-test-repeated",
        )

        definition = build_builtin_handler_registry().require(
            "query_database",
            "1.0.0",
        )
        assert second["id"] == first["id"]
        assert first["status"] == "ACTIVE"
        assert first["release_revision"] == 1
        assert first["tool_identifier"] == definition.tool_identifier
        assert first["tool_semantic_version"] == definition.tool_semantic_version
        assert first["handler_version"] == definition.handler_version
        assert first["implementation_digest"] == definition.implementation_digest
        assert first["manifest_hash"] == definition.manifest_hash
        assert first["public_schema_hash"] == definition.public_schema_hash
        assert first["verification_id"] == evidence["id"]
        assert runtime.database.execute_one(
            "select count(*) as count from builtin_tool_release"
        ) == {"count": 1}
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from builtin_tool_lifecycle_audit
             where tool_release_id = ? and new_status = 'ACTIVE'
            """,
            (first["id"],),
        ) == {"count": 1}

        redis_evidence = service.verify_payload(
            {
                "tool_identifier": "query_redis_get",
                "handler_version": "1.0.0",
            },
            actor_id="admin",
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="idempotency key",
        ):
            service.publish_builtin_tool_payload(
                {
                    "tool_identifier": "query_redis_get",
                    "handler_version": "1.0.0",
                    "verification_id": redis_evidence["id"],
                    "idempotency_key": "publish-query-database-v1",
                },
                actor_id="admin",
            )

        with pytest.raises(
            NonRetryableExecutionError,
            match="verification evidence",
        ):
            service.publish_builtin_tool_payload(
                {
                    "tool_identifier": "query_loki",
                    "handler_version": "1.0.0",
                    "verification_id": "missing-evidence",
                    "idempotency_key": "publish-query-loki-v1",
                },
                actor_id="admin",
            )
    finally:
        runtime.database.close()


def test_agent_envelope_rejects_two_active_releases_for_one_identifier() -> None:
    runtime = container()
    current_registry = build_builtin_handler_registry()
    current = current_registry.require("query_database", "1.0.0")
    next_version = replace(
        current,
        handler_version="1.1.0",
        tool_semantic_version="1.1.0",
        implementation_key=f"{current.implementation_key}:v1.1.0",
    )
    registry = HandlerRegistry((*current_registry.definitions(), next_version))
    service = HandlerGovernanceService(
        HandlerGovernanceRepository(runtime.database),
        runtime.platform_config_service.repository,
        runtime.platform_config_service.permission_service,
        registry=registry,
    )
    try:
        service.reconcile(actor_id="admin")
        releases = []
        for definition in (current, next_version):
            evidence = service.verify_payload(
                {
                    "tool_identifier": definition.tool_identifier,
                    "handler_version": definition.handler_version,
                },
                actor_id="admin",
            )
            releases.append(
                service.publish_builtin_tool_payload(
                    {
                        "tool_identifier": definition.tool_identifier,
                        "handler_version": definition.handler_version,
                        "verification_id": evidence["id"],
                        "idempotency_key": (f"agent-envelope-{definition.handler_version}"),
                    },
                    actor_id="admin",
                )
            )

        envelopes = AgentBuiltinToolEnvelopeService(
            HandlerGovernanceRepository(runtime.database),
            registry=registry,
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="multiple Releases",
        ):
            envelopes.prepare([str(item["id"]) for item in releases])
    finally:
        runtime.database.close()


def test_builtin_tool_release_lifecycle_separates_health_and_protects_dependencies() -> None:
    runtime = container()
    service = runtime.platform_config_service.handlers
    try:
        service.reconcile(actor_id="admin")
        evidence = service.verify_payload(
            {
                "tool_identifier": "query_database",
                "handler_version": "1.0.0",
            },
            actor_id="admin",
        )
        release = service.publish_builtin_tool_payload(
            {
                "tool_identifier": "query_database",
                "handler_version": "1.0.0",
                "verification_id": evidence["id"],
                "idempotency_key": "lifecycle-query-database-v1",
            },
            actor_id="admin",
        )
        timestamp = "2026-08-06T00:00:00+00:00"
        runtime.database.execute(
            """
            insert into agent_definition
              (id, code, name, project_code, status, created_by, created_at,
               updated_at)
            values ('agent-lifecycle-test', 'agent-lifecycle-test',
                    'Agent Lifecycle Test', 'default', 'enabled', 'test', ?, ?)
            """,
            (timestamp, timestamp),
        )
        runtime.database.execute(
            """
            insert into agent_revision
              (id, agent_id, revision, status, config_json, config_hash,
               validation_json, created_by, created_at, updated_at)
            values ('agent-lifecycle-revision', 'agent-lifecycle-test', 1,
                    'published', '{}', 'lifecycle-config', '{}', 'test', ?, ?)
            """,
            (timestamp, timestamp),
        )
        runtime.database.execute(
            """
            insert into agent_publication
              (id, agent_id, revision_id, revision, schema_version,
               snapshot_json, config_hash, status, published_by, published_at)
            values ('agent-lifecycle-publication', 'agent-lifecycle-test',
                    'agent-lifecycle-revision', 1, 1, '{}',
                    'lifecycle-config', 'active', 'test', ?)
            """,
            (timestamp,),
        )
        runtime.database.execute(
            """
            insert into agent_publication_builtin_tool
              (id, agent_publication_id, tool_identifier, tool_release_id,
               handler_version, implementation_digest, public_schema_hash,
               envelope_hash, created_at)
            values ('agent-lifecycle-envelope',
                    'agent-lifecycle-publication', 'query_database', ?,
                    '1.0.0', ?, ?, ?, ?)
            """,
            (
                release["id"],
                release["implementation_digest"],
                release["public_schema_hash"],
                "a" * 64,
                timestamp,
            ),
        )

        deprecated = service.set_builtin_tool_release_status(
            str(release["id"]),
            "DEPRECATED",
            reason_code="SOFT_DEPRECATION",
            actor_id="admin",
        )
        assert deprecated["status"] == "DEPRECATED"
        with pytest.raises(
            NonRetryableExecutionError,
            match="active dependencies",
        ):
            service.set_builtin_tool_release_status(
                str(release["id"]),
                "ARCHIVED",
                reason_code="ARCHIVE_TEST",
                actor_id="admin",
            )

        disabled = service.set_builtin_tool_release_status(
            str(release["id"]),
            "DISABLED",
            reason_code="EMERGENCY_DISABLE",
            actor_id="admin",
        )
        assert disabled["status"] == "DISABLED"
        restored = service.set_builtin_tool_release_status(
            str(release["id"]),
            "ACTIVE",
            reason_code="VERIFIED_RESTORE",
            verification_id=str(evidence["id"]),
            actor_id="admin",
        )
        assert restored["status"] == "ACTIVE"

        definition = build_builtin_handler_registry().require(
            "query_database",
            "1.0.0",
        )
        drifted_service = HandlerGovernanceService(
            HandlerGovernanceRepository(runtime.database),
            runtime.platform_config_service.repository,
            runtime.platform_config_service.permission_service,
            registry=HandlerRegistry(
                (
                    replace(
                        definition,
                        implementation_key=definition.implementation_key + ":drifted",
                    ),
                )
            ),
        )
        drifted_service.reconcile(actor_id="admin")
        assert runtime.database.execute_one(
            "select status from builtin_tool_release where id = ?",
            (release["id"],),
        ) == {"status": "ACTIVE"}

        service.set_builtin_tool_release_status(
            str(release["id"]),
            "DISABLED",
            reason_code="DISABLE_AFTER_DRIFT",
            actor_id="admin",
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="installation digest drifted",
        ):
            service.set_builtin_tool_release_status(
                str(release["id"]),
                "ACTIVE",
                reason_code="INVALID_RESTORE",
                verification_id=str(evidence["id"]),
                actor_id="admin",
            )

        runtime.database.execute(
            """
            update agent_publication
               set status = 'inactive'
             where id = 'agent-lifecycle-publication'
            """
        )
        archived = service.set_builtin_tool_release_status(
            str(release["id"]),
            "ARCHIVED",
            reason_code="DEPENDENCIES_DRAINED",
            actor_id="admin",
        )
        assert archived["status"] == "ARCHIVED"
        with pytest.raises(
            NonRetryableExecutionError,
            match="terminal",
        ):
            service.set_builtin_tool_release_status(
                str(release["id"]),
                "ACTIVE",
                reason_code="INVALID_ARCHIVE_RESTORE",
                verification_id=str(evidence["id"]),
                actor_id="admin",
            )
    finally:
        runtime.database.close()


def test_handler_tables_store_manifest_metadata_not_dynamic_implementation() -> None:
    runtime = container()
    service = runtime.platform_config_service.handlers
    try:
        service.reconcile(actor_id="admin")
        columns = {
            row["name"]
            for row in runtime.database.execute("pragma table_info(handler_installation)")
        }
        assert {
            "implementation_digest",
            "input_schema_json",
            "output_schema_json",
            "required_permissions_json",
            "resource_slots_json",
        }.issubset(columns)
        assert not columns.intersection(
            {
                "python",
                "script",
                "source",
                "sql",
                "sql_template",
                "url",
            }
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="Dynamic Handler",
        ):
            service.publish_payload(
                {
                    "handler_id": "query_loki",
                    "handler_version": "1.0.0",
                    "implementation": {"url": "https://untrusted.invalid/handler"},
                },
                actor_id="admin",
            )
        persisted = str(service.repository.list_installations())
        assert "untrusted.invalid" not in persisted
    finally:
        runtime.database.close()
