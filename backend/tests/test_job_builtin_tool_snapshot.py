from __future__ import annotations

import json

import pytest

from app.bootstrap import build_test_container
from app.modules.internal_api_platform.domain.addressing import TargetRef
from app.modules.internal_api_platform.domain.errors import AuthorizationError
from app.modules.internal_api_platform.domain.topology import ResourceKind
from app.modules.internal_api_platform.infrastructure.job_authorization import (
    BusinessApplicationJobAccessAuthorizer,
)
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.shared.exceptions import NonRetryableExecutionError, ToolPolicyError
from app.shared.exceptions import RetryableExecutionError
from app.modules.job.application.job_dispatch_operations import (
    JobDispatchOperationsService,
)
from backend.tests.test_application_builtin_tool_resource_mapping import (
    _publish_next_database_resource_revision,
    _publish_builtin_tool,
    _published_database_resource,
    _published_workshop_policy,
)
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)


def _published_application(
    runtime: object,
    *,
    placements: tuple[str, ...] = ("cloud", "edge"),
    tool_identifiers: tuple[str, ...] = ("query_database",),
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    releases = {
        tool_identifier: _publish_builtin_tool(runtime, tool_identifier)
        for tool_identifier in tool_identifiers
    }
    for tool_identifier in tool_identifiers:
        runtime.database.execute(
            """
            insert into permission_policy
              (id, subject_type, subject_code, resource_type, resource_code,
               effect, action, status, priority, revision, created_at,
               updated_at)
            values (?, 'user', 'user_local_admin', 'tool', ?, 'allow', 'use',
                    'enabled', 100, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            on conflict(id) do nothing
            """,
            (
                f"test-user-local-admin-tool-use-{tool_identifier}",
                tool_identifier,
            ),
        )
    environment = runtime.platform_config_service.upsert_environment(
        {"code": "job-snapshot"},
        actor_id="user_local_admin",
    )
    base = runtime.platform_config_service.upsert_base(
        {
            "environment_code": "job-snapshot",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    workshop = runtime.platform_config_service.upsert_workshop(
        {
            "environment_code": "job-snapshot",
            "base_code": "guanlan",
            "code": "GL001",
        },
        actor_id="user_local_admin",
    )
    cloud_revision_id = _published_database_resource(
        runtime,
        code="job_snapshot_database_cloud",
        environment_id=str(environment["id"]),
        base_id=str(base["id"]),
    )
    edge_revision_id = _published_database_resource(
        runtime,
        code="job_snapshot_database_edge",
        environment_id=str(environment["id"]),
        base_id=str(base["id"]),
    )
    policy_revision_id = _published_workshop_policy(
        runtime,
        workshop_id=str(workshop["id"]),
    )
    resources_by_placement = {
        "cloud": cloud_revision_id,
        "edge": edge_revision_id,
    }
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="job-builtin-snapshot",
        name="Job Built-in Snapshot",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [
        {
            "target_scope_type": "workshop",
            "environment_code": "job-snapshot",
            "base_code": "guanlan",
            "workshop_code": "GL001",
        }
    ]
    resource_mappings = [
        {
            "resource_slot": "database",
            "target_scope_type": "workshop",
            "environment_code": "job-snapshot",
            "base_code": "guanlan",
            "workshop_code": "GL001",
            "placement": placement,
            "resource_revision_id": resource_revision_id,
            "workshop_partition_policy_revision_id": (policy_revision_id),
            "loki_scope_policy_revision_id": "",
        }
        for placement, resource_revision_id in (
            (value, resources_by_placement[value]) for value in placements
        )
    ]
    payload["builtin_tools"] = [
        {
            "tool_release_id": releases[tool_identifier]["id"],
            "resources": [dict(mapping) for mapping in resource_mappings]
            if tool_identifier in {"get_schema_directory", "query_database"}
            else [],
        }
        for tool_identifier in tool_identifiers
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="job-builtin-snapshot",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="job-builtin-snapshot",
        revision_id=str(revision["id"]),
    )
    runtime.business_application_service.activate(
        actor_id="user_local_admin",
        code="job-builtin-snapshot",
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    role = runtime.authorization_center_service.create_role(
        actor_id="user_local_admin",
        code="job-builtin-snapshot-role",
        name="Job Built-in Snapshot Role",
        description="",
        purpose_tags=["业务诊断"],
    )["role"]
    runtime.authorization_center_service.replace_business_access(
        actor_id="user_local_admin",
        role_id=str(role["id"]),
        expected_revision=1,
        applications=[
            {
                "application_id": application["id"],
                "capability_codes": list(tool_identifiers),
                "scopes": [
                    {
                        "environment_id": environment["id"],
                        "base_id": base["id"],
                    }
                ],
            }
        ],
        confirmed=True,
        reason="验证 Job Built-in Tool Snapshot",
    )
    runtime.identity_repository.assign_role(
        user_id="user_local_admin",
        role_id=str(role["id"]),
        assigned_by="user_local_admin",
    )
    return (
        application,
        publication,
        {
            "environment_id": environment["id"],
            "base_id": base["id"],
            "workshop_id": workshop["id"],
            "release": releases.get("query_database") or releases[tool_identifiers[0]],
            "releases": releases,
            "policy_revision_id": policy_revision_id,
            "resource_revision_ids": {resources_by_placement[value] for value in placements},
            "resource_revision_by_placement": {
                value: resources_by_placement[value] for value in placements
            },
        },
    )


def _command(
    runtime: object,
    application: dict[str, object],
    publication: dict[str, object],
    facts: dict[str, object],
    *,
    idempotency_key: str,
    workshop: str = "GL001",
    user_message: str = "检查 GL001 数据",
) -> CreateAgentJobCommand:
    agent = runtime.agent_config_service.publication("agent_publication_default_v1")
    return CreateAgentJobCommand(
        idempotency_key=idempotency_key,
        user_message=user_message,
        requester_id="user_local_admin",
        source_channel="debug_api",
        source_connector_id="connector-debug-api",
        external_conversation_id=f"conversation-{idempotency_key}",
        reply_route={
            "type": "none",
            "connector_id": "",
            "target": {},
            "options": {},
        },
        routing_context={
            "project_code": "default",
            "environment": "job-snapshot",
            "base": "guanlan",
            "workshop": workshop,
            "environment_id": facts["environment_id"],
            "base_id": facts["base_id"],
            "workshop_id": (facts["workshop_id"] if workshop == "GL001" else ""),
        },
        fixed_agent_publication_id="agent_publication_default_v1",
        fixed_agent_revision=1,
        fixed_agent_config_hash=str(agent["config_hash"]),
        agent_code="default-diagnostic-agent",
        business_application_id=str(application["id"]),
        business_application_code="job-builtin-snapshot",
        business_application_publication_id=str(publication["id"]),
        business_application_config_hash=str(publication["config_hash"]),
        business_application_runtime_status="ready",
        conversation_mode="channel",
        session_policy={"conversation_mode": "channel"},
    )


def test_job_creation_atomically_freezes_exact_builtin_tool_snapshot() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-valid",
            )
        )

        frozen = runtime.builtin_tool_snapshot_service.verify(job.id)
        snapshot = frozen["snapshot"]
        assert snapshot["schema_version"] == 3
        assert snapshot["application_publication"]["id"] == publication["id"]
        assert snapshot["target"]["target_key"].endswith(str(facts["workshop_id"]))
        assert len(snapshot["bindings"]) == 1
        binding = snapshot["bindings"][0]
        assert binding["tool_release_id"] == facts["release"]["id"]
        assert binding["available_placements"] == ["cloud", "edge"]
        assert {item["resource_revision_id"] for item in binding["candidates"]} == facts[
            "resource_revision_ids"
        ]
        assert {
            item["workshop_partition_policy_revision_id"] for item in binding["candidates"]
        } == {facts["policy_revision_id"]}
        persisted = runtime.database.execute_one(
            """
            select available_placements_json, resource_revision_id,
                   workshop_partition_policy_revision_id
              from agent_job_builtin_tool_binding
             where snapshot_id = ?
            """,
            (frozen["id"],),
        )
        assert persisted is not None
        assert json.loads(persisted["available_placements_json"]) == [
            "cloud",
            "edge",
        ]
        assert persisted["resource_revision_id"] is None
        assert persisted["workshop_partition_policy_revision_id"] == facts["policy_revision_id"]
        dispatch = runtime.database.execute_one(
            "select status from job_dispatch_outbox where job_id = ?",
            (job.id,),
        )
        assert dispatch == {"status": "PENDING"}

        repeated = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-valid",
            )
        )
        assert repeated.id == job.id
        assert (
            runtime.builtin_tool_snapshot_service.verify(job.id)["snapshot_hash"]
            == frozen["snapshot_hash"]
        )
    finally:
        runtime.database.close()


def test_job_target_ambiguity_rolls_back_job_and_dispatch() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        with pytest.raises(NonRetryableExecutionError) as rejected:
            runtime.create_agent_job_service.execute(
                _command(
                    runtime,
                    application,
                    publication,
                    facts,
                    idempotency_key="job-builtin-snapshot-invalid-target",
                    workshop="GL002",
                )
            )
        assert rejected.value.error_code == "job_builtin_tool_target_resolution_invalid"
        assert runtime.database.execute_one(
            "select count(*) as count from agent_job where idempotency_key = ?",
            ("job-builtin-snapshot-invalid-target",),
        ) == {"count": 0}
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from job_dispatch_outbox dispatch
              join agent_job job on job.id = dispatch.job_id
             where job.idempotency_key = ?
            """,
            ("job-builtin-snapshot-invalid-target",),
        ) == {"count": 0}
    finally:
        runtime.database.close()


def test_job_target_uses_the_only_published_target_when_scope_is_omitted() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        target = {
            "target_scope_type": "environment",
            "target_key": "environment:env-test",
            "environment_id": "env-test",
            "environment_code": "test",
            "base_id": "",
            "base_code": "",
            "workshop_id": "",
            "workshop_code": "",
        }

        resolved = runtime.builtin_tool_snapshot_service._resolve_target(
            targets=[target],
            routing_context={"project_code": "default"},
        )

        assert resolved == target
    finally:
        runtime.database.close()


def test_job_target_without_scope_still_rejects_multiple_published_targets() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        targets = [
            {
                "target_scope_type": "environment",
                "target_key": f"environment:env-{code}",
                "environment_id": f"env-{code}",
                "environment_code": code,
                "base_id": "",
                "base_code": "",
                "workshop_id": "",
                "workshop_code": "",
            }
            for code in ("test", "prod")
        ]

        with pytest.raises(NonRetryableExecutionError) as rejected:
            runtime.builtin_tool_snapshot_service._resolve_target(
                targets=targets,
                routing_context={"project_code": "default"},
            )

        assert rejected.value.error_code == "job_builtin_tool_target_resolution_invalid"
    finally:
        runtime.database.close()


def test_dispatch_rejects_tampered_builtin_tool_snapshot() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-tampered",
            )
        )
        runtime.database.execute(
            """
            update agent_job_builtin_tool_snapshot
               set snapshot_json = '{}'
             where job_id = ?
            """,
            (job.id,),
        )

        result = runtime.job_dispatcher.publish_pending(limit=1)

        assert result.published == 0
        assert result.failed == 1
        assert (
            runtime.database.execute_one(
                "select status from job_dispatch_outbox where job_id = ?",
                (job.id,),
            )["status"]
            == "RETRY_WAIT"
        )
    finally:
        runtime.database.close()


def test_agent_tool_catalog_uses_complete_exact_governance_intersection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-catalog",
            )
        )

        business_decision = runtime.business_authorization_service.decide(
            user_id="user_local_admin",
            application_id=str(application["id"]),
            capability_code="query_database",
            environment="job-snapshot",
            base="guanlan",
            workshop="GL001",
            stage="test_tool_exposure",
        )
        assert business_decision["allowed"], business_decision

        def reject_legacy_permission_gate(**_: object) -> None:
            pytest.fail(
                "business application tools must use business RBAC instead of "
                "the legacy permission gate"
            )

        monkeypatch.setattr(
            runtime.permission_service,
            "assert_builtin_tool_use_grant",
            reject_legacy_permission_gate,
        )

        context = runtime.agent_executor.context_builder.build(job)
        assert context.allowed_tools == ["query_database"]
        assert runtime.tool_service.is_tool_visible_for_job(
            job_id=job.id,
            tool_name="query_database",
        )
        assert not runtime.tool_service.is_tool_visible_for_job(
            job_id=job.id,
            tool_name="query_redis_get",
        )

        with pytest.raises(ToolPolicyError) as target_override:
            runtime.tool_service.call_tool(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                tool_name="query_database",
                arguments={
                    "environment": "job-snapshot",
                    "base": "guanlan",
                    "workshop": "GL002",
                    "sql": "select * from GL001_ORDER",
                },
            )
        assert target_override.value.error_code == "builtin_tool_target_override_rejected"

        with pytest.raises(ToolPolicyError) as readonly_policy:
            runtime.tool_service.call_tool(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                tool_name="query_database",
                arguments={
                    "environment": "job-snapshot",
                    "base": "guanlan",
                    "workshop": "GL001",
                    "sql": "delete from GL001_ORDER",
                },
            )
        assert readonly_policy.value.safe_message == "只允许执行 SELECT 或 WITH 查询"
    finally:
        runtime.database.close()


def test_internal_platform_authorizes_only_exact_job_snapshot_facts() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(
            runtime,
            placements=("cloud",),
        )
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-internal-platform",
            )
        )
        runtime.database.execute(
            "update agent_job set status = 'RUNNING' where id = ?",
            (job.id,),
        )
        authorizer = BusinessApplicationJobAccessAuthorizer(runtime.database)
        tool_call_id = runtime.agent_repository.add_tool_call(
            job_id=job.id,
            tool_name="query_database",
            request_payload={"placement": "cloud"},
            response_summary={"status": "STARTED"},
            status="STARTED",
            duration_ms=0,
            risk_level="medium",
        )
        target = TargetRef(
            environment="job-snapshot",
            base="guanlan",
            workshop="GL001",
            kind=ResourceKind.DATABASE,
        )

        authorized = authorizer.authorize(
            job_id=job.id,
            user_id="user_local_admin",
            project_code="default",
            application_id=str(application["id"]),
            capability_code="query_database",
            target=target,
            placement="cloud",
            tool_call_id=tool_call_id,
            correlation_id="tool-call-exact-facts",
        )

        assert authorized.schema_version == 3
        assert authorized.snapshot_id
        assert authorized.tool_execution_binding_id
        assert authorized.tool_release_id == facts["release"]["id"]
        assert authorized.handler_version == "1.0.0"
        assert authorized.implementation_digest == facts["release"]["implementation_digest"]
        assert authorized.actual_placement == "cloud"
        assert authorized.resource_revision_id in facts["resource_revision_ids"]
        assert authorized.workshop_partition_policy_revision_id == facts["policy_revision_id"]
        assert authorized.database_table_prefix == "GL001_"

        with pytest.raises(AuthorizationError):
            authorizer.authorize(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                application_id=str(application["id"]),
                capability_code="query_database",
                target=TargetRef(
                    environment="job-snapshot",
                    base="guanlan",
                    workshop="GL002",
                    kind=ResourceKind.DATABASE,
                ),
                placement="cloud",
                tool_call_id=tool_call_id,
                correlation_id="tool-call-exact-facts",
            )

        runtime.database.execute(
            """
            update builtin_tool_installation
               set installation_status = 'DRIFTED'
             where tool_identifier = 'query_database'
               and handler_version = '1.0.0'
            """
        )
        with pytest.raises(AuthorizationError):
            authorizer.authorize(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                application_id=str(application["id"]),
                capability_code="query_database",
                target=target,
                placement="cloud",
                tool_call_id=tool_call_id,
                correlation_id="tool-call-exact-facts",
            )
    finally:
        runtime.database.close()


def test_internal_platform_rejects_job_when_exact_snapshot_is_missing() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(
            runtime,
            placements=("cloud",),
        )
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-required",
            )
        )
        runtime.database.execute(
            "update agent_job set status = 'RUNNING' where id = ?",
            (job.id,),
        )
        snapshot = runtime.database.execute_one(
            "select id from agent_job_builtin_tool_snapshot where job_id = ?",
            (job.id,),
        )
        assert snapshot is not None
        runtime.database.execute(
            "delete from agent_job_builtin_tool_binding where snapshot_id = ?",
            (snapshot["id"],),
        )
        runtime.database.execute(
            "delete from agent_job_builtin_tool_snapshot where id = ?",
            (snapshot["id"],),
        )

        with pytest.raises(AuthorizationError):
            BusinessApplicationJobAccessAuthorizer(runtime.database).authorize(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                application_id=str(application["id"]),
                capability_code="query_database",
                target=TargetRef(
                    environment="job-snapshot",
                    base="guanlan",
                    workshop="GL001",
                    kind=ResourceKind.DATABASE,
                ),
                placement="cloud",
            )
    finally:
        runtime.database.close()


def test_tool_call_placement_is_explicit_deterministic_and_audited() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-placement",
            )
        )
        runtime.database.execute(
            "update agent_job set status = 'RUNNING' where id = ?",
            (job.id,),
        )
        authorizer = BusinessApplicationJobAccessAuthorizer(runtime.database)
        target = TargetRef(
            environment="job-snapshot",
            base="guanlan",
            workshop="GL001",
            kind=ResourceKind.DATABASE,
        )

        ambiguous_call_id = runtime.agent_repository.add_tool_call(
            job_id=job.id,
            tool_name="query_database",
            request_payload={},
            response_summary={"status": "STARTED"},
            status="STARTED",
            duration_ms=0,
            risk_level="medium",
        )
        with pytest.raises(AuthorizationError):
            authorizer.authorize(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                application_id=str(application["id"]),
                capability_code="query_database",
                target=target,
                tool_call_id=ambiguous_call_id,
                correlation_id="placement-ambiguous",
            )
        denied = runtime.database.execute_one(
            """
            select actual_placement, resource_revision_id,
                   authorization_decision, decision_reason_code
              from agent_tool_call_builtin_tool_fact
             where tool_call_id = ?
            """,
            (ambiguous_call_id,),
        )
        assert denied == {
            "actual_placement": None,
            "resource_revision_id": None,
            "authorization_decision": "DENIED",
            "decision_reason_code": "placement_required",
        }

        edge_call_id = runtime.agent_repository.add_tool_call(
            job_id=job.id,
            tool_name="query_database",
            request_payload={"placement": "edge"},
            response_summary={"status": "STARTED"},
            status="STARTED",
            duration_ms=0,
            risk_level="medium",
        )
        authorized = authorizer.authorize(
            job_id=job.id,
            user_id="user_local_admin",
            project_code="default",
            application_id=str(application["id"]),
            capability_code="query_database",
            target=target,
            placement="edge",
            tool_call_id=edge_call_id,
            correlation_id="placement-edge",
        )
        assert authorized.actual_placement == "edge"
        edge_fact = runtime.database.execute_one(
            """
            select tool_release_id, handler_version,
                   implementation_digest, actual_placement,
                   resource_revision_id,
                   workshop_partition_policy_revision_id,
                   authorization_decision, decision_reason_code,
                   correlation_id, effective_scope_hash,
                   effective_selector_hash
              from agent_tool_call_builtin_tool_fact
             where tool_call_id = ?
            """,
            (edge_call_id,),
        )
        assert edge_fact is not None
        assert edge_fact["tool_release_id"] == facts["release"]["id"]
        assert edge_fact["handler_version"] == "1.0.0"
        assert edge_fact["implementation_digest"] == facts["release"]["implementation_digest"]
        assert edge_fact["actual_placement"] == "edge"
        assert edge_fact["resource_revision_id"] == (authorized.resource_revision_id)
        assert edge_fact["workshop_partition_policy_revision_id"] == facts["policy_revision_id"]
        assert edge_fact["authorization_decision"] == "ALLOWED"
        assert edge_fact["decision_reason_code"] == ("exact_job_snapshot_allowed")
        assert edge_fact["correlation_id"] == "placement-edge"
        assert len(edge_fact["effective_scope_hash"]) == 64
        assert len(edge_fact["effective_selector_hash"]) == 64
    finally:
        runtime.database.close()


def test_existing_job_keeps_original_snapshot_after_application_upgrade() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-upgrade",
            )
        )
        original = runtime.builtin_tool_snapshot_service.verify(job.id)
        original_candidates = original["snapshot"]["bindings"][0]["candidates"]
        original_resources = {value["resource_revision_id"] for value in original_candidates}
        next_cloud_revision = _publish_next_database_resource_revision(
            runtime,
            previous_revision_id=str(facts["resource_revision_by_placement"]["cloud"]),
        )
        current_application = runtime.business_application_repository.get_by_id(
            str(application["id"])
        )
        payload = draft_payload(
            capabilities=[
                {
                    "capability_code": "query_database",
                    "version_constraint": "",
                    "enabled": True,
                }
            ]
        )
        payload["target_paths"] = [
            {
                "target_scope_type": "workshop",
                "environment_code": "job-snapshot",
                "base_code": "guanlan",
                "workshop_code": "GL001",
            }
        ]
        payload["builtin_tools"] = [
            {
                "tool_release_id": facts["release"]["id"],
                "resources": [
                    {
                        "resource_slot": "database",
                        "target_scope_type": "workshop",
                        "environment_code": "job-snapshot",
                        "base_code": "guanlan",
                        "workshop_code": "GL001",
                        "placement": placement,
                        "resource_revision_id": resource_revision_id,
                        "workshop_partition_policy_revision_id": facts["policy_revision_id"],
                        "loki_scope_policy_revision_id": "",
                    }
                    for placement, resource_revision_id in (
                        ("cloud", next_cloud_revision),
                        (
                            "edge",
                            facts["resource_revision_by_placement"]["edge"],
                        ),
                    )
                ],
            }
        ]
        upgraded_revision = runtime.business_application_service.save_draft(
            actor_id="user_local_admin",
            code="job-builtin-snapshot",
            expected_revision=int(current_application["revision"]),
            payload=payload,
        )
        upgraded_publication = runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="job-builtin-snapshot",
            revision_id=str(upgraded_revision["id"]),
        )
        runtime.business_application_service.activate(
            actor_id="user_local_admin",
            code="job-builtin-snapshot",
            environment="local",
            publication_id=str(upgraded_publication["id"]),
            expected_revision=1,
        )

        replayed = runtime.builtin_tool_snapshot_service.verify(job.id)
        assert replayed["snapshot_hash"] == original["snapshot_hash"]
        assert replayed["snapshot"]["application_publication"]["id"] == publication["id"]
        assert {
            value["resource_revision_id"]
            for value in replayed["snapshot"]["bindings"][0]["candidates"]
        } == original_resources
        assert next_cloud_revision not in original_resources

        dispatch = runtime.job_dispatcher.publish_pending(limit=1)
        assert dispatch.published == 1
        assert dispatch.failed == 0
    finally:
        runtime.database.close()


@pytest.mark.parametrize(
    ("failure_kind", "failure_value", "expected_error_code"),
    [
        (
            "release",
            "DISABLED",
            "job_builtin_tool_release_not_callable",
        ),
        (
            "installation",
            "MISSING",
            "job_builtin_tool_implementation_drifted",
        ),
        (
            "installation",
            "DRIFTED",
            "job_builtin_tool_implementation_drifted",
        ),
    ],
)
def test_dispatch_retry_fails_closed_when_frozen_implementation_unavailable(
    failure_kind: str,
    failure_value: str,
    expected_error_code: str,
) -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key=(f"job-builtin-snapshot-{failure_kind}-{failure_value.lower()}"),
            )
        )
        if failure_kind == "release":
            runtime.database.execute(
                "update builtin_tool_release set status = ? where id = ?",
                (failure_value, facts["release"]["id"]),
            )
        else:
            runtime.database.execute(
                """
                update builtin_tool_installation
                   set installation_status = ?
                 where tool_identifier = 'query_database'
                   and handler_version = '1.0.0'
                """,
                (failure_value,),
            )

        result = runtime.job_dispatcher.publish_pending(limit=1)

        assert result.published == 0
        assert result.failed == 1
        event = runtime.database.execute_one(
            """
            select status, last_error_code
              from job_dispatch_outbox where job_id = ?
            """,
            (job.id,),
        )
        assert event is not None
        assert event["status"] == "RETRY_WAIT"
        assert event["last_error_code"] == expected_error_code
    finally:
        runtime.database.close()


def test_retry_and_explicit_replay_revalidate_original_snapshot() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    try:
        application, publication, facts = _published_application(runtime)
        job = runtime.create_agent_job_service.execute(
            _command(
                runtime,
                application,
                publication,
                facts,
                idempotency_key="job-builtin-snapshot-retry-replay",
            )
        )
        runtime.database.execute(
            "update agent_job set status = 'RUNNING' where id = ?",
            (job.id,),
        )
        runtime.database.execute(
            "update builtin_tool_release set status = 'DISABLED' where id = ?",
            (facts["release"]["id"],),
        )

        action = runtime.retry_service.handle_failure(
            runtime.agent_repository.get_job(job.id),
            RetryableExecutionError(
                "temporary upstream failure",
                safe_message="临时上游失败",
            ),
            "retry-original-snapshot",
        )

        assert action == "dead"
        assert runtime.agent_repository.get_job(job.id).status.value == ("FAILED")

        replay_runtime = build_test_container(
            control_plane_settings(),
            migrate=True,
            seed=True,
        )
        try:
            replay_application, replay_publication, replay_facts = _published_application(
                replay_runtime
            )
            replay_job = replay_runtime.create_agent_job_service.execute(
                _command(
                    replay_runtime,
                    replay_application,
                    replay_publication,
                    replay_facts,
                    idempotency_key=("job-builtin-snapshot-explicit-replay"),
                )
            )
            replay_runtime.database.execute(
                """
                update job_dispatch_outbox
                   set status = 'DEAD', dead_at = CURRENT_TIMESTAMP
                 where job_id = ?
                """,
                (replay_job.id,),
            )
            replay_runtime.database.execute(
                """
                update builtin_tool_release set status = 'DISABLED'
                 where id = ?
                """,
                (replay_facts["release"]["id"],),
            )
            operations = JobDispatchOperationsService(
                repository=replay_runtime.agent_repository,
                audit_service=replay_runtime.audit_service,
                builtin_tool_snapshot_service=(replay_runtime.builtin_tool_snapshot_service),
            )
            with pytest.raises(NonRetryableExecutionError) as rejected:
                operations.replay(
                    job_id=replay_job.id,
                    actor_id="user_local_admin",
                    reason="验证精确快照重放",
                )
            assert rejected.value.error_code == ("job_builtin_tool_release_not_callable")
            assert (
                replay_runtime.database.execute_one(
                    """
                    select status from job_dispatch_outbox
                     where job_id = ?
                    """,
                    (replay_job.id,),
                )["status"]
                == "DEAD"
            )
        finally:
            replay_runtime.database.close()
    finally:
        runtime.database.close()
