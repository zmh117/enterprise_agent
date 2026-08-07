from __future__ import annotations

from typing import Any

import pytest

from app.bootstrap import build_test_container
from app.modules.internal_api_platform.domain.addressing import TargetRef
from app.modules.internal_api_platform.domain.errors import AuthorizationError
from app.modules.internal_api_platform.domain.topology import ResourceKind
from app.modules.internal_api_platform.infrastructure.job_authorization import (
    BusinessApplicationJobAccessAuthorizer,
)
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_application_builtin_tool_resource_mapping import (
    _publish_builtin_tool,
)
from backend.tests.helpers import container
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)
from backend.tests.test_job_builtin_tool_snapshot import (
    _command,
    _published_application,
)


class PassingMysqlVerifier:
    def verify(
        self,
        *,
        resource: dict[str, object],
        draft: dict[str, object],
    ) -> ResourceVerificationOutcome:
        del resource, draft
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={"connection": True, "readonly_account": True},
        )


def _governed_application() -> tuple[
    Any,
    dict[str, Any],
    dict[str, Any],
]:
    runtime = container()
    runtime.database.execute(
        """
        insert into permission_policy
          (id, subject_type, subject_code, resource_type, resource_code,
           effect, action, status, priority, revision, created_at, updated_at)
        values ('test-governed-scope-project-use', 'user',
                'user_local_admin', 'project', 'default', 'allow', 'use',
                'enabled', 100, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
               ('test-governed-scope-tool-use', 'user',
                'user_local_admin', 'tool', 'query_database', 'allow', 'use',
                'enabled', 100, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """
    )
    topology = PlatformConfigRepository(runtime.database)
    environment = topology.upsert_environment(
        code="local",
        display_name="本地环境",
    )
    base = topology.upsert_base(
        environment_code="local",
        code="governed-base",
        display_name="治理基地",
        engine="mysql",
    )
    release = _publish_builtin_tool(runtime, "query_database")
    runtime.platform_config_service.create_platform_secret(
        {
            "code": "governed_scope_mysql_password",
            "value": "governed-scope-password",
        },
        actor_id="local-user",
    )
    resources = runtime.platform_config_service.governed_resources
    resources.create_resource(
        {
            "code": "governed_scope_mysql",
            "name": "Governed Scope MySQL",
            "resource_kind": "database",
            "scope_type": "base",
            "environment_code": "local",
            "base_code": "governed-base",
            "provider_type": "mysql",
            "config": {
                "host": "mysql.internal",
                "port": 3306,
                "database": "diagnostic",
                "username": "reader",
            },
            "secret_refs": {
                "password_ref": (
                    "secret://platform/governed_scope_mysql_password"
                )
            },
        },
        actor_id="local-user",
    )
    resources.verify_draft(
        "governed_scope_mysql",
        actor_id="local-user",
        verifier=PassingMysqlVerifier(),
    )
    resource_revision = resources.publish_draft(
        "governed_scope_mysql",
        actor_id="local-user",
    )

    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="governed-execution-scope",
        name="Governed execution scope",
        description="Pinned exact Tool and Resource revision",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [
        {
            "target_scope_type": "base",
            "environment_code": "local",
            "base_code": "governed-base",
            "workshop_code": "",
        }
    ]
    payload["builtin_tools"] = [
        {
            "tool_release_id": release["id"],
            "resources": [
                {
                    "resource_slot": "database",
                    "target_scope_type": "base",
                    "environment_code": "local",
                    "base_code": "governed-base",
                    "workshop_code": "",
                    "placement": "",
                    "resource_revision_id": resource_revision["id"],
                    "workshop_partition_policy_revision_id": "",
                    "loki_scope_policy_revision_id": "",
                }
            ],
        }
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="governed-execution-scope",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="governed-execution-scope",
        revision_id=str(revision["id"]),
    )
    runtime.business_application_service.activate(
        actor_id="user_local_admin",
        code="governed-execution-scope",
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    role = runtime.authorization_center_service.create_role(
        actor_id="user_local_admin",
        code="governed-execution-scope-role",
        name="Governed execution scope role",
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
                "capability_codes": ["query_database"],
                "scopes": [
                    {
                        "environment_id": environment["id"],
                        "base_id": base["id"],
                    }
                ],
            }
        ],
        confirmed=True,
        reason="测试精确 Job Execution Scope",
    )
    runtime.identity_repository.assign_role(
        user_id="user_local_admin",
        role_id=str(role["id"]),
        assigned_by="user_local_admin",
    )
    return runtime, publication, resource_revision


def test_governed_resource_dependency_summary_uses_exact_publication_mapping() -> None:
    runtime, publication, _resource_revision = _governed_application()
    try:
        resource = next(
            item
            for item in (
                runtime.platform_config_service.governed_resources.list_resources()
            )
            if item["code"] == "governed_scope_mysql"
        )
        assert resource["affected_applications"] == [
            {
                "publication_id": str(publication["id"]),
                "application_id": str(publication["application_id"]),
                "application_code": "governed-execution-scope",
                "application_name": "Governed execution scope",
                "runtime_status": "NOT_ACTIVE",
            }
        ]
    finally:
        runtime.database.close()


def test_job_pins_exact_builtin_tool_resource_and_scope() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
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
            idempotency_key="governed-execution-scope-job",
        )
    )
    frozen = runtime.builtin_tool_snapshot_service.verify(job.id)
    assert frozen["snapshot"]["schema_version"] == 3
    assert frozen["snapshot"]["application_publication"]["id"] == publication["id"]
    binding = frozen["snapshot"]["bindings"][0]
    assert binding["tool_identifier"] == "query_database"
    assert binding["handler_version"] == "1.0.0"
    assert binding["tool_release_id"] == facts["release"]["id"]
    assert binding["candidates"][0]["resource_revision_id"] in facts[
        "resource_revision_ids"
    ]

    runtime.database.execute(
        "update agent_job set status = 'RUNNING' where id = ?",
        (job.id,),
    )
    tool_call_id = runtime.agent_repository.add_tool_call(
        job_id=job.id,
        tool_name="query_database",
        request_payload={"placement": "cloud"},
        response_summary={"status": "STARTED"},
        status="STARTED",
        duration_ms=0,
        risk_level="medium",
    )
    authorizer = BusinessApplicationJobAccessAuthorizer(runtime.database)
    authorized = authorizer.authorize(
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
        tool_call_id=tool_call_id,
    )
    assert authorized.handler_version == "1.0.0"
    assert authorized.resource_revision_id in facts["resource_revision_ids"]

    with pytest.raises(AuthorizationError):
        authorizer.authorize(
            job_id=job.id,
            user_id="user_local_admin",
            project_code="default",
            application_id=str(application["id"]),
            capability_code="query_database",
            target=TargetRef(
                environment="job-snapshot",
                base="another-base",
                workshop=None,
                kind=ResourceKind.DATABASE,
            ),
        )
    runtime.database.close()


def test_publication_rejects_missing_required_exact_resource_slot() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    release = _publish_builtin_tool(runtime, "query_database")
    runtime.platform_config_service.upsert_environment(
        {"code": "missing-resource"},
        actor_id="user_local_admin",
    )
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="missing-exact-resource",
        name="Missing exact resource",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["target_paths"] = [
        {
            "target_scope_type": "environment",
            "environment_code": "missing-resource",
            "base_code": "",
            "workshop_code": "",
        }
    ]
    payload["builtin_tools"] = [
        {"tool_release_id": release["id"], "resources": []}
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="missing-exact-resource",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.business_application_service.publish(
            actor_id="user_local_admin",
            code="missing-exact-resource",
            revision_id=str(revision["id"]),
        )
    assert rejected.value.error_code == "builtin_tool_resource_mapping_missing"
    runtime.database.close()


def test_business_agent_can_publish_exact_database_tool() -> None:
    runtime = build_test_container(
        control_plane_settings(),
        migrate=True,
        seed=True,
    )
    runtime.database.execute(
        """
        update agent_definition
           set classification = 'business'
         where id = 'agent_default_diagnostic'
        """
    )
    application, publication, _facts = _published_application(
        runtime,
        placements=("cloud",),
    )
    assert publication["snapshot"]["builtin_tools"][0]["tool_identifier"] == (
        "query_database"
    )
    catalog = runtime.business_application_service.catalog(
        actor_id="user_local_admin",
        code=str(application["code"]),
    )
    envelopes = catalog["builtin_tools_by_agent_publication"][
        "agent_publication_default_v1"
    ]
    assert "query_database" in {
        item["tool_identifier"] for item in envelopes if item["selectable"]
    }
    runtime.database.close()
