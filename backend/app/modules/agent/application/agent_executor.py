from __future__ import annotations

from typing import Any

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.domain.runtime import AgentRunRequest
from app.modules.agent.infrastructure.claude_code_agent_client import ClaudeCodeAgentClient
from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center.application import BusinessAuthorizationService
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import PermissionDenied
from app.shared.exceptions import NonRetryableExecutionError


class AgentExecutor:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
        status_service: JobStatusService,
        context_builder: AgentContextBuilder,
        claude_client: ClaudeCodeAgentClient,
        result_service: AgentResultService,
        delivery_service: ResultDeliveryService,
        business_authorization_service: BusinessAuthorizationService | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.status_service = status_service
        self.context_builder = context_builder
        self.claude_client = claude_client
        self.result_service = result_service
        self.delivery_service = delivery_service
        self.business_authorization_service = business_authorization_service

    def cancel(
        self,
        job_id: str,
        *,
        actor_id: str,
        reason: str = "JOB_CANCELLED",
    ) -> AgentJob:
        if reason not in {"JOB_CANCELLED", "WORKER_TIMEOUT", "CLIENT_DISCONNECTED"}:
            raise NonRetryableExecutionError(
                "Agent Runtime cancel reason is invalid",
                safe_message="取消原因无效",
                error_code="runtime_cancel_reason_invalid",
            )
        job = self.repository.get_job(job_id)
        if job.status in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.TIMEOUT,
            JobStatus.CANCELLED,
        }:
            return job
        runtime_ack = "not_started"
        if job.status == JobStatus.RUNNING:
            context = self.context_builder.build(job)
            request = AgentRunRequest(
                job_id=job.id,
                user_id=job.internal_user_id or job.user_id,
                project_code=job.project_code,
                context=context,
                invocation_id=f"{job.id}.attempt-{job.retry_count}",
            )
            cancel = getattr(self.claude_client, "cancel", None)
            if not callable(cancel):
                raise NonRetryableExecutionError(
                    "Selected Agent Runtime client cannot cancel a running Job",
                    safe_message="当前 Agent Runtime 不支持运行中取消",
                    error_code="runtime_cancel_unavailable",
                )
            result = cancel(request, reason)
            runtime_ack = str((result or {}).get("status") or "")
            if runtime_ack not in {"cancelled", "already_terminal"}:
                raise NonRetryableExecutionError(
                    "Agent Runtime did not acknowledge cancellation",
                    safe_message="Agent Runtime 未确认取消请求",
                    error_code="runtime_cancel_not_acknowledged",
                )
        cancelled = self.status_service.cancel(job.id)
        self.repository.add_step(
            job_id=job.id,
            step_type="cancelled",
            title="Agent execution cancelled",
            content="Execution stopped by an authorized cancellation request.",
        )
        self.audit_service.record(
            "job.cancelled",
            status="SUCCEEDED",
            summary="Agent job cancellation persisted after Runtime acknowledgement",
            job_id=job.id,
            actor_id=actor_id,
            payload={
                "reason": reason,
                "runtime_ack": runtime_ack,
                "runtime_kind": job.agent_runtime_kind,
            },
        )
        return cancelled

    def execute(
        self,
        job_id: str,
        *,
        worker_id: str = "agent-worker",
        correlation_id: str = "",
        fail_on_error: bool = True,
        recover_typescript_running: bool = False,
    ) -> str:
        claimed = self.status_service.claim(
            job_id,
            worker_id,
            recover_typescript_running=recover_typescript_running,
        )
        if claimed is None:
            persisted = self.repository.get_job(job_id)
            if persisted.status == JobStatus.SUCCEEDED and persisted.result:
                return persisted.result
            return ""
        job = claimed
        if job.business_application_id:
            if self.business_authorization_service is None:
                self.status_service.fail(job_id, "业务应用授权服务暂时不可用")
                raise PermissionDenied(
                    "Business authorization service is unavailable",
                    safe_message="业务应用授权服务暂时不可用",
                    error_code="business_authorization_unavailable",
                )
            try:
                decision = self.business_authorization_service.require(
                    user_id=job.internal_user_id or job.user_id,
                    application_id=job.business_application_id,
                    stage="worker_start",
                )
            except PermissionDenied as exc:
                self.repository.add_step(
                    job_id=job_id,
                    step_type="authorization_denied",
                    title="业务应用授权已失效",
                    content=exc.safe_message,
                )
                self.status_service.fail(job_id, exc.safe_message)
                raise
            self.audit_service.record(
                "authorization.business.worker_start",
                status="SUCCEEDED",
                summary="Business authorization allowed worker start",
                job_id=job_id,
                actor_id=job.internal_user_id or job.user_id,
                payload=decision,
            )
        self.audit_service.record(
            "worker.claimed",
            status="SUCCEEDED",
            summary="Worker claimed Agent job",
            job_id=job.id,
            actor_id=worker_id,
            payload={
                "correlation_id": correlation_id,
                "retry_count": job.retry_count,
                **_business_application_context(job),
            },
        )
        if job.retry_count > 0:
            self.audit_service.record(
                "job.retry.released",
                status="SUCCEEDED",
                summary="Due Agent job retry returned to a worker",
                job_id=job.id,
                actor_id=worker_id,
                payload={
                    "correlation_id": correlation_id,
                    "retry_count": job.retry_count,
                    **_business_application_context(job),
                },
            )
        self.repository.add_step(
            job_id=job.id,
            step_type="started",
            title="Agent execution started",
            content="Read-only diagnostic runtime started.",
        )
        self.repository.record_execution_policy_usage(
            job.id,
            tool_call_count=0,
            exhausted=False,
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
                    user_id=job.internal_user_id or job.user_id,
                    project_code=job.project_code,
                    context=context,
                    invocation_id=f"{job.id}.attempt-{job.retry_count}",
                )
            )
            if result.runtime_provenance:
                self.repository.record_runtime_provenance(
                    job.id,
                    result.runtime_provenance,
                )
            self.repository.record_execution_policy_usage(
                job.id,
                tool_call_count=_tool_call_count(result.tool_events),
                exhausted=False,
            )
            self.repository.add_step(
                job_id=job.id,
                step_type="model_completed",
                title="Model execution completed",
                content="Claude runtime returned a final diagnostic report.",
            )
            self._persist_success(
                job=job,
                final_answer=result.final_answer,
                worker_id=worker_id,
                correlation_id=correlation_id,
            )
            return result.final_answer
        except Exception as exc:
            persisted = self.repository.get_job(job.id)
            if persisted.status == JobStatus.SUCCEEDED and persisted.result:
                return persisted.result
            if persisted.status in {
                JobStatus.FAILED,
                JobStatus.TIMEOUT,
                JobStatus.CANCELLED,
            }:
                return ""
            safe_message = getattr(exc, "safe_message", str(exc))
            tool_events = getattr(exc, "tool_events", [])
            self.repository.record_execution_policy_usage(
                job.id,
                tool_call_count=_tool_call_count(tool_events),
                exhausted=(
                    getattr(exc, "error_code", "") == "execution_policy_max_tool_calls_exhausted"
                ),
            )
            self.repository.add_step(
                job_id=job.id,
                step_type="error",
                title="Agent execution failed",
                content=safe_message,
            )
            diagnostics = getattr(exc, "diagnostics", {})
            runtime_provenance = (
                diagnostics.get("runtime_provenance") if isinstance(diagnostics, dict) else None
            )
            if isinstance(runtime_provenance, dict):
                self.repository.record_runtime_provenance(job.id, runtime_provenance)
            if fail_on_error:
                self.status_service.fail(job.id, safe_message)
            raise

    @operation_unit_of_work(lambda executor: executor.repository.database)
    def _persist_success(
        self,
        *,
        job: AgentJob,
        final_answer: str,
        worker_id: str,
        correlation_id: str,
    ) -> None:
        artifact_id = self.result_service.save_result(job, final_answer)
        self.status_service.succeed(job.id, final_answer)
        delivery_id = self.delivery_service.enqueue_job_result(
            job_id=job.id,
            artifact_id=artifact_id,
            correlation_id=correlation_id,
        )
        self.audit_service.record(
            "result.delivery.requested",
            status="PENDING",
            summary="Final report delivery persisted for independent dispatch",
            job_id=job.id,
            actor_id=worker_id,
            payload={
                "delivery_id": delivery_id,
                "correlation_id": correlation_id,
                **_business_application_context(job),
            },
        )


def _business_application_context(job: object) -> dict[str, str]:
    return {
        "business_application_code": str(getattr(job, "business_application_code", "") or ""),
        "business_application_publication_id": str(
            getattr(job, "business_application_publication_id", "") or ""
        ),
        "business_application_deployment_id": str(
            getattr(job, "business_application_deployment_id", "") or ""
        ),
        "business_application_route_id": str(
            getattr(job, "business_application_route_id", "") or ""
        ),
    }


def _tool_call_count(events: list[dict[str, Any]]) -> int:
    relevant = [
        (index, event)
        for index, event in enumerate(events)
        if str(event.get("status") or "").upper()
        in {"STARTED", "SUCCEEDED", "FAILED", "REJECTED", "DENIED"}
    ]
    started = {
        str(event.get("tool_call_id") or index)
        for index, event in relevant
        if str(event.get("status") or "").upper() in {"STARTED", "DENIED"}
    }
    if started:
        return len(started)
    return len({str(event.get("tool_call_id") or index) for index, event in relevant})
