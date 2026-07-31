from __future__ import annotations

from typing import Any

import pytest

from app.modules.internal_api_platform.domain.addressing import TargetRef
from app.modules.internal_api_platform.domain.errors import (
    AuthorizationError,
)
from app.modules.internal_api_platform.domain.topology import ResourceKind
from app.modules.internal_api_platform.infrastructure.job_authorization import (
    BusinessApplicationJobAccessAuthorizer,
)
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


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
            checks={
                "connection": True,
                "readonly_account": True,
            },
        )


def _governed_application() -> tuple[
    Any,
    dict[str, Any],
    dict[str, Any],
]:
    runtime = container()
    topology = PlatformConfigRepository(runtime.database)
    topology.upsert_environment(
        code="local",
        display_name="本地环境",
    )
    base = topology.upsert_base(
        environment_code="local",
        code="governed-base",
        display_name="治理基地",
        engine="mysql",
    )
    runtime.platform_config_service.handlers.reconcile(
        actor_id="local-user"
    )
    runtime.platform_config_service.handlers.publish_payload(
        {
            "handler_id": "query_database",
            "handler_version": "1.0.0",
        },
        actor_id="local-user",
    )
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
                    "secret://platform/"
                    "governed_scope_mysql_password"
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

    applications = runtime.business_application_service
    application = applications.create(
        actor_id="user_local_admin",
        code="governed-execution-scope",
        name="Governed execution scope",
        description="Pinned Handler and Resource revision",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = applications.save_draft(
        actor_id="user_local_admin",
        code="governed-execution-scope",
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": (
                "agent_publication_default_v1"
            ),
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 30,
                "continuous_conversation_enabled": False,
                "attachments_enabled": False,
            },
            "execution_policy": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "triggers": [],
            "deliveries": [],
            "capabilities": [
                {
                    "capability_code": "query_database",
                    "version_constraint": "1.0.0",
                    "enabled": True,
                }
            ],
        },
    )
    publication = applications.publish(
        actor_id="user_local_admin",
        code="governed-execution-scope",
        revision_id=str(revision["id"]),
        handler_bindings=[
            {
                "capability_code": "query_database",
                "handler_id": "query_database",
                "handler_version": "1.0.0",
                "constraints": {},
                "resources": [
                    {
                        "resource_slot": "database",
                        "resource_revision_id": (
                            resource_revision["id"]
                        ),
                        "constraints": {
                            "max_rows": 50,
                            "max_bytes": 65_536,
                            "timeout_seconds": 5,
                        },
                    }
                ],
            }
        ],
    )
    applications.activate(
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
        description="Test governed Job scope",
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
                        "environment_id": base[
                            "environment_id"
                        ],
                        "base_id": base["id"],
                    }
                ],
            }
        ],
        confirmed=True,
        reason="测试 Job Execution Scope",
    )
    runtime.identity_repository.assign_role(
        user_id="user_local_admin",
        role_id=str(role["id"]),
        assigned_by="user_local_admin",
    )
    return runtime, publication, resource_revision


def test_job_pins_governed_handler_resource_and_scope() -> None:
    runtime, publication, resource_revision = (
        _governed_application()
    )
    try:
        agent_publication = (
            runtime.agent_config_service.publication(
                "agent_publication_default_v1"
            )
        )
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="governed-execution-scope-job",
                user_message="检查治理执行范围",
                requester_id="user_local_admin",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                external_conversation_id="governed-scope-debug",
                reply_route={
                    "type": "none",
                    "connector_id": "",
                    "target": {},
                    "options": {},
                },
                routing_context={
                    "project_code": "default",
                    "environment": "local",
                    "base": "governed-base",
                    "workshop": "",
                    "service": "",
                },
                fixed_agent_publication_id=(
                    "agent_publication_default_v1"
                ),
                fixed_agent_revision=1,
                fixed_agent_config_hash=str(
                    agent_publication["config_hash"]
                ),
                agent_code="default-diagnostic-agent",
                business_application_id=str(
                    publication["application_id"]
                ),
                business_application_code=(
                    "governed-execution-scope"
                ),
                business_application_publication_id=str(
                    publication["id"]
                ),
                business_application_config_hash=str(
                    publication["config_hash"]
                ),
                business_application_runtime_status="ready",
                conversation_mode="channel",
                session_policy={
                    "conversation_mode": "channel",
                },
            )
        )
        scope = runtime.database.execute_one(
            """
            select * from agent_job_execution_scope
             where job_id = ?
            """,
            (job.id,),
        )
        assert scope is not None
        assert scope["application_publication_id"] == publication[
            "id"
        ]
        assert scope["schema_version"] == 2
        assert len(str(scope["scope_hash"])) == 64
        binding = runtime.database.execute_one(
            """
            select * from agent_job_execution_binding
             where execution_scope_id = ?
            """,
            (scope["id"],),
        )
        assert binding is not None
        assert binding["handler_id"] == "query_database"
        assert binding["handler_version"] == "1.0.0"
        assert binding["resource_revision_id"] == (
            resource_revision["id"]
        )
        runtime.database.execute(
            "update agent_job set status = 'RUNNING' where id = ?",
            (job.id,),
        )
        authorized = BusinessApplicationJobAccessAuthorizer(
            runtime.database
        ).authorize(
            job_id=job.id,
            user_id="user_local_admin",
            project_code="default",
            application_id=str(publication["application_id"]),
            capability_code="query_database",
            target=TargetRef(
                environment="local",
                base="governed-base",
                workshop=None,
                kind=ResourceKind.DATABASE,
            ),
        )
        assert authorized.handler_version == "1.0.0"
        assert authorized.resource_revision_id == (
            resource_revision["id"]
        )
        authorizer = BusinessApplicationJobAccessAuthorizer(
            runtime.database
        )
        with pytest.raises(AuthorizationError):
            authorizer.authorize(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                application_id=str(
                    publication["application_id"]
                ),
                capability_code="query_database",
                target=TargetRef(
                    environment="local",
                    base="another-base",
                    workshop=None,
                    kind=ResourceKind.DATABASE,
                ),
            )
        runtime.database.execute(
            """
            update agent_job_execution_binding
               set handler_version = '9.9.9'
             where execution_scope_id = ?
            """,
            (scope["id"],),
        )
        with pytest.raises(AuthorizationError):
            authorizer.authorize(
                job_id=job.id,
                user_id="user_local_admin",
                project_code="default",
                application_id=str(
                    publication["application_id"]
                ),
                capability_code="query_database",
                target=TargetRef(
                    environment="local",
                    base="governed-base",
                    workshop=None,
                    kind=ResourceKind.DATABASE,
                ),
            )
    finally:
        runtime.database.close()


def test_publication_rejects_missing_required_resource_slot() -> None:
    runtime, publication, _resource_revision = (
        _governed_application()
    )
    try:
        application = runtime.business_application_repository.get_by_id(
            str(publication["application_id"])
        )
        revision = runtime.business_application_service.save_draft(
            actor_id="user_local_admin",
            code=str(application["code"]),
            expected_revision=int(application["revision"]),
            payload={
                "agent_publication_id": (
                    "agent_publication_default_v1"
                ),
                "workflow_publication_id": "",
                "session_policy": {
                    "conversation_mode": "channel",
                    "recent_message_limit": 20,
                    "retention_days": 30,
                    "continuous_conversation_enabled": False,
                    "attachments_enabled": False,
                },
                "execution_policy": {
                    "max_turns": 12,
                    "timeout_seconds": 300,
                    "max_tool_calls": 30,
                },
                "triggers": [],
                "deliveries": [],
                "capabilities": [
                    {
                        "capability_code": "query_database",
                        "version_constraint": "1.0.0",
                        "enabled": True,
                    }
                ],
            },
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="resource slots",
        ):
            runtime.business_application_service.publish(
                actor_id="user_local_admin",
                code=str(application["code"]),
                revision_id=str(revision["id"]),
                handler_bindings=[
                    {
                        "capability_code": "query_database",
                        "handler_id": "query_database",
                        "handler_version": "1.0.0",
                        "constraints": {},
                        "resources": [],
                    }
                ],
            )
        assert runtime.database.execute_one(
            """
            select id from business_application_publication
             where revision_id = ?
            """,
            (revision["id"],),
        ) is None
    finally:
        runtime.database.close()


def test_business_agent_can_validate_database_query_capability() -> None:
    runtime = container()
    try:
        runtime.database.execute(
            """
            update agent_definition
               set classification = 'business'
             where id = 'agent_default_diagnostic'
            """
        )
        application = runtime.business_application_service.create(
            actor_id="user_local_admin",
            code="ordinary-business-agent",
            name="Ordinary business Agent",
            description="Uses governed read-only database query",
            project_code="default",
            owner_user_id="user_local_admin",
        )
        revision = runtime.business_application_service.save_draft(
            actor_id="user_local_admin",
            code="ordinary-business-agent",
            expected_revision=int(application["revision"]),
            payload={
                "agent_publication_id": (
                    "agent_publication_default_v1"
                ),
                "workflow_publication_id": "",
                "session_policy": {
                    "conversation_mode": "channel",
                    "recent_message_limit": 20,
                    "retention_days": 30,
                    "continuous_conversation_enabled": False,
                    "attachments_enabled": False,
                },
                "execution_policy": {
                    "max_turns": 12,
                    "timeout_seconds": 300,
                    "max_tool_calls": 30,
                },
                "triggers": [],
                "deliveries": [],
                "capabilities": [
                    {
                        "capability_code": "query_database",
                        "version_constraint": "1.0.0",
                        "enabled": True,
                    }
                ],
            },
        )
        validated = runtime.business_application_service.validate(
            actor_id="user_local_admin",
            code="ordinary-business-agent",
            revision_id=str(revision["id"]),
        )
        assert validated["validation"] == {
            "valid": True,
            "errors": [],
        }
        catalog = runtime.business_application_service.catalog(
            actor_id="user_local_admin",
            code="ordinary-business-agent",
        )
        assert "query_database" in {
            item["code"] for item in catalog["capabilities"]
        }
    finally:
        runtime.database.close()
