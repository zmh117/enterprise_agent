from __future__ import annotations

from app.bootstrap import Container
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.persistence_values import now_iso
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.mcp_audit import McpAuditCoordinator
from app.modules.platform_config.application.governed_resources import ResourceVerificationOutcome
from app.services.tool_mcp import JobToolService, ToolRequestIdentity
from backend.tests.support.authorization import prepare_debug_application_access
from backend.tests.support.runtime import container


TOOL_NAME = "get_schema_directory"
TOOL_ARGUMENTS = {
    "environment": "local",
    "base": "debug-base",
    "query": "order",
    "limit": 10,
}


class _PassingMysqlVerifier:
    def verify(self, **_: object) -> ResourceVerificationOutcome:
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={"connection": "passed", "readonly": True},
        )


def publish_database_resource(runtime: Container) -> None:
    platform_config_service = runtime.platform_config_service
    platform_config_service.create_platform_secret(
        {
            "code": "tool_mcp_test_password",
            "value": "test-only-password",
        },
        actor_id="user_local_admin",
    )
    resource_service = platform_config_service.governed_resources
    resource_service.create_resource(
        {
            "code": "tool_mcp_test_database",
            "name": "Tool MCP Test Database",
            "resource_kind": "database",
            "scope_type": "base",
            "environment_code": "local",
            "base_code": "debug-base",
            "provider_type": "mysql",
            "config": {
                "host": "mysql.test.internal",
                "port": 3306,
                "database": "diagnostics",
                "username": "readonly",
            },
            "secret_refs": {
                "password_ref": "secret://platform/tool_mcp_test_password",
            },
        },
        actor_id="user_local_admin",
    )
    resource_service.verify_draft(
        "tool_mcp_test_database",
        actor_id="user_local_admin",
        verifier=_PassingMysqlVerifier(),
    )
    resource_service.publish_draft(
        "tool_mcp_test_database",
        actor_id="user_local_admin",
    )


def runtime_job(
    *, capabilities: tuple[str, ...] = (TOOL_NAME,), allow_direct_jobs: bool = True
) -> tuple[Container, AgentJob, JobToolService]:
    runtime = container(allow_direct_jobs=allow_direct_jobs)
    try:
        if "ones_work_item_search" in capabilities:
            definition = MCP_TOOL_MANIFEST["ones_work_item_search"]
            next_order = runtime.database.execute_one(
                "select coalesce(max(selection_order), -1) + 1 as value "
                "from agent_publication_mcp_tool where agent_publication_id = ?",
                ("agent_publication_default_v1",),
            )
            assert next_order is not None
            runtime.database.execute(
                """
                insert into agent_publication_mcp_tool
                  (agent_publication_id, server_code, tool_identifier, schema_hash,
                   model_description, selection_order, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "agent_publication_default_v1",
                    definition.server_code,
                    definition.identifier,
                    definition.schema_hash,
                    definition.description,
                    int(next_order["value"]),
                    now_iso(),
                ),
            )
        selection = prepare_debug_application_access(
            runtime,
            application_code="tool-mcp-application",
            role_code="tool-mcp-role",
            capabilities=capabilities,
        )
        if TOOL_NAME in capabilities:
            publish_database_resource(runtime)
        job, _ = runtime.debug_job_access_service.create_job(
            user_id="user_local_admin",
            display_name="Administrator",
            message="diagnose",
            application_id=selection["application_id"],
            execution_scope_id=selection["execution_scope_id"],
            idempotency_key="tool-mcp-job",
            correlation_id="tool-mcp-test",
            environment="local",
        )
        claimed = runtime.agent_repository.claim_job(job.id, "agent-worker-test")
        assert claimed is not None
        service = JobToolService(
            repository=runtime.agent_repository,
            tool_registry=ToolRegistry(runtime.tool_service),
            snapshot_service=runtime.mcp_tool_snapshot_service,
            audit_coordinator=McpAuditCoordinator(
                runtime.database,
                max_payload_bytes=512 * 1024,
                audit_service=runtime.audit_service,
            ),
        )
        return runtime, claimed, service
    except BaseException:
        runtime.database.close()
        raise


def request_identity(job: AgentJob, correlation_id: str) -> ToolRequestIdentity:
    return ToolRequestIdentity(
        invocation_id=f"{job.id}.attempt-{job.retry_count}",
        app_user_id=job.internal_user_id,
        project_code=job.project_code,
        agent_publication_id=job.agent_publication_id,
        application_publication_id=job.business_application_publication_id,
        correlation_id=correlation_id,
    )


def request_headers(job: AgentJob, correlation_id: str) -> dict[str, str]:
    identity = request_identity(job, correlation_id)
    return {
        "x-job-id": job.id,
        "x-invocation-id": identity.invocation_id,
        "x-app-user-id": identity.app_user_id,
        "x-project-code": identity.project_code,
        "x-agent-publication-id": identity.agent_publication_id,
        "x-application-publication-id": identity.application_publication_id,
        "x-correlation-id": identity.correlation_id,
    }
