from __future__ import annotations

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.domain.runtime import AgentRunRequest
from app.modules.agent.infrastructure.claude_code_agent_client import ClaudeCodeAgentClient
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.audit.application.audit_service import AuditService
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository


class AgentExecutor:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
        status_service: JobStatusService,
        context_builder: AgentContextBuilder,
        claude_client: ClaudeCodeAgentClient,
        tool_registry: ToolRegistry,
        result_service: AgentResultService,
        callback_client: DingTalkCallbackClient,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.status_service = status_service
        self.context_builder = context_builder
        self.claude_client = claude_client
        self.tool_registry = tool_registry
        self.result_service = result_service
        self.callback_client = callback_client

    def execute(
        self,
        job_id: str,
        *,
        worker_id: str = "agent-worker",
        fail_on_error: bool = True,
    ) -> str:
        claimed = self.status_service.claim(job_id, worker_id)
        if claimed is None:
            job = self.repository.get_job(job_id)
            if job.status == JobStatus.SUCCEEDED and job.result:
                return job.result
            return ""
        job = claimed
        self.audit_service.record(
            "worker.claimed",
            status="SUCCEEDED",
            summary="Worker claimed Agent job",
            job_id=job.id,
            actor_id=worker_id,
        )
        self.repository.add_step(
            job_id=job.id,
            step_type="started",
            title="Agent execution started",
            content="Read-only diagnostic runtime started.",
        )
        try:
            context = self.context_builder.build(job)
            self.repository.add_step(
                job_id=job.id,
                step_type="tool_call",
                title="Context search completed",
                content="Relevant ER and business-flow context retrieved.",
            )
            result = self.claude_client.run(AgentRunRequest(job_id=job.id, context=context))
            self.result_service.save_result(job, result.final_answer)
            self.status_service.succeed(job.id, result.final_answer)
            session = self.repository.get_session(job.session_id)
            self.callback_client.send_markdown(
                conversation_id=session.dingding_conversation_id,
                title="Agent diagnostic report",
                text=result.final_answer,
            )
            self.audit_service.record(
                "dingtalk.callback",
                status="SUCCEEDED",
                summary="Final report callback sent",
                job_id=job.id,
                actor_id=worker_id,
            )
            return result.final_answer
        except Exception as exc:
            safe_message = getattr(exc, "safe_message", str(exc))
            self.repository.add_step(
                job_id=job.id,
                step_type="error",
                title="Agent execution failed",
                content=safe_message,
            )
            if fail_on_error:
                self.status_service.fail(job.id, safe_message)
            raise
