from __future__ import annotations

import json

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.domain.runtime import AgentRunRequest
from app.modules.agent.infrastructure.claude_code_agent_client import ClaudeCodeAgentClient
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.audit.application.audit_service import AuditService
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
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
        delivery_service: ResultDeliveryService,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.status_service = status_service
        self.context_builder = context_builder
        self.claude_client = claude_client
        self.tool_registry = tool_registry
        self.result_service = result_service
        self.delivery_service = delivery_service

    def execute(
        self,
        job_id: str,
        *,
        worker_id: str = "agent-worker",
        correlation_id: str = "",
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
            payload={"correlation_id": correlation_id, "retry_count": job.retry_count},
        )
        if job.retry_count > 0:
            self.audit_service.record(
                "job.retry.released",
                status="SUCCEEDED",
                summary="Due Agent job retry returned to a worker",
                job_id=job.id,
                actor_id=worker_id,
                payload={"correlation_id": correlation_id, "retry_count": job.retry_count},
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
            result = self.claude_client.run(
                AgentRunRequest(
                    job_id=job.id,
                    user_id=job.user_id,
                    project_code=job.project_code,
                    context=context,
                )
            )
            self._persist_tool_events(job.id, result.tool_events)
            self.repository.add_step(
                job_id=job.id,
                step_type="model_completed",
                title="Model execution completed",
                content="Claude runtime returned a final diagnostic report.",
            )
            self.result_service.save_result(job, result.final_answer)
            self.status_service.succeed(job.id, result.final_answer)
            self.delivery_service.deliver_job_result(job.id)
            self.audit_service.record(
                "result.delivery.requested",
                status="SUCCEEDED",
                summary="Final report delivery requested",
                job_id=job.id,
                actor_id=worker_id,
            )
            return result.final_answer
        except Exception as exc:
            safe_message = getattr(exc, "safe_message", str(exc))
            self._persist_tool_events(job.id, getattr(exc, "tool_events", []))
            self.repository.add_step(
                job_id=job.id,
                step_type="error",
                title="Agent execution failed",
                content=safe_message,
            )
            if fail_on_error:
                self.status_service.fail(job.id, safe_message)
            raise

    def _persist_tool_events(self, job_id: str, tool_events: list[dict[str, object]]) -> None:
        existing = {
            _event_key(
                {
                    "tool_name": row["tool_name"],
                    "request_payload": row["request_payload"],
                    "response_summary": row["response_summary"],
                    "status": row["status"],
                }
            )
            for row in self.repository.list_tool_calls(job_id)
        }
        for event in tool_events:
            key = _event_key(event)
            if key in existing:
                continue
            existing.add(key)
            tool_name = str(event.get("tool_name", "unknown"))
            duration = _int_value(event.get("duration_ms"))
            audit_id_value = event.get("audit_id")
            audit_id = audit_id_value if isinstance(audit_id_value, str) else None
            self.repository.add_tool_call(
                job_id=job_id,
                tool_name=tool_name,
                request_payload=_dict_value(event.get("request_payload")),
                response_summary=_dict_value(event.get("response_summary")),
                status=str(event.get("status", "SUCCEEDED")),
                duration_ms=duration,
                risk_level=str(event.get("risk_level", "medium")),
                audit_id=audit_id,
            )


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {"payload": str(value)}


def _int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _event_key(event: dict[str, object]) -> str:
    return json.dumps(
        {
            "tool_name": event.get("tool_name"),
            "request_payload": event.get("request_payload"),
            "response_summary": event.get("response_summary"),
            "status": event.get("status"),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
