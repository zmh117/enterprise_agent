"""知识 MCP 的协议身份适配，不读取 ONES 凭据或签发 Token。"""

from collections.abc import Mapping
from typing import Any

from app.modules.knowledge.application.retrieval_budget import RetrievalBudget
from app.modules.knowledge.infrastructure.reader_access import KnowledgePrincipalAccess
from app.modules.mcp_audit import McpAuditContext
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database
from app.shared.mcp_server_policy import KNOWLEDGE_MCP_SERVER_CODE
from services.knowledge_mcp_server.errors import failure
from services.knowledge_mcp_server.execution import CallControl


class KnowledgeMcpAuth:
    def __init__(self, database: Database, access: KnowledgePrincipalAccess) -> None:
        self.database, self.access = database, access

    def budget(self, job_id: str, control: CallControl) -> RetrievalBudget:
        def current_job() -> dict[str, Any]:
            control.check()
            row = self.database.execute_one(
                "select retry_count,locked_at,execution_policy_json from agent_job "
                "where id=? and status='RUNNING'",
                (job_id,),
            )
            if not row:
                raise failure("knowledge_mcp_context_invalid")
            return row

        return RetrievalBudget(current_job, deadline_ms=control.deadline_ms)

    def resolve(self, token: str, tool: str, headers: Mapping[str, str]) -> McpAuditContext:
        access = self.access.authenticate(token, tool)
        job = self.database.execute_one(
            "select id,session_id,retry_count,project_code,internal_user_id,agent_publication_id,"
            "business_application_publication_id from agent_job where id=? and status='RUNNING'",
            (access.job_id,),
        )
        if not job:
            raise failure("knowledge_mcp_context_invalid")
        expected = {
            "x-job-id": access.job_id,
            "x-app-user-id": access.actor_id,
            "x-project-code": job["project_code"],
            "x-agent-publication-id": job["agent_publication_id"],
            "x-application-publication-id": access.application_publication_id,
            "x-invocation-id": f"{access.job_id}.attempt-{int(job['retry_count'])}",
            "x-correlation-id": f"job:{access.job_id}",
        }
        if (
            any(headers.get(key) != value for key, value in expected.items())
            or job["internal_user_id"] != access.actor_id
            or job["business_application_publication_id"] != access.application_publication_id
        ):
            raise failure("knowledge_mcp_context_invalid")
        return McpAuditContext(
            correlation_id=expected["x-correlation-id"],
            job_id=access.job_id,
            session_id=job["session_id"],
            invocation_id=expected["x-invocation-id"],
            actor_user_id=access.actor_id,
            server_code=KNOWLEDGE_MCP_SERVER_CODE,
            tool_identifier=tool,
            tool_schema_hash=MCP_TOOL_MANIFEST[tool].schema_hash,
            agent_publication_id=job["agent_publication_id"],
            application_publication_id=access.application_publication_id,
        )
