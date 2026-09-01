from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.application.runtime_client import AgentRuntimeClient
from app.modules.agent.domain.runtime import AgentRunRequest
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center.application import BusinessAuthorizationService
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.job.infrastructure.execution_audit_repository import (
    ExecutionAuditRepository,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import PermissionDenied
from app.shared.tool_contract import canonical_json_sha256


class AgentExecutor:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        audit_service: AuditService,
        status_service: JobStatusService,
        context_builder: AgentContextBuilder,
        runtime_client: AgentRuntimeClient,
        tool_registry: ToolRegistry,
        result_service: AgentResultService,
        delivery_service: ResultDeliveryService,
        business_authorization_service: BusinessAuthorizationService | None = None,
        mcp_tool_snapshot_service: JobMcpToolSnapshotService | None = None,
        after_runtime_result_hook: Callable[[], None] | None = None,
        execution_audit_repository: ExecutionAuditRepository | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.status_service = status_service
        self.context_builder = context_builder
        self.runtime_client = runtime_client
        self.tool_registry = tool_registry
        self.result_service = result_service
        self.delivery_service = delivery_service
        self.business_authorization_service = business_authorization_service
        self.mcp_tool_snapshot_service = mcp_tool_snapshot_service
        self.after_runtime_result_hook = after_runtime_result_hook
        self.execution_audit_repository = execution_audit_repository or ExecutionAuditRepository(
            repository.database
        )
        self._active_lock = threading.Lock()
        self._active_requests: dict[str, AgentRunRequest] = {}

    def cancel_active(self, job_id: str, reason: str) -> bool:
        with self._active_lock:
            request = self._active_requests.get(job_id)
        if request is None:
            return False
        self.runtime_client.cancel(request, reason)
        return True

    def execute(
        self,
        job_id: str,
        *,
        worker_id: str = "agent-worker",
        correlation_id: str = "",
        fail_on_error: bool = True,
        recover_runtime_running: bool = False,
    ) -> str:
        claimed = self.status_service.claim(
            job_id,
            worker_id,
            recover_runtime_running=recover_runtime_running,
        )
        if claimed is None:
            persisted = self.repository.get_job(job_id)
            if persisted.status == JobStatus.SUCCEEDED and persisted.result:
                return persisted.result
            return ""
        job = claimed
        mcp_tool_snapshot: dict[str, object] | None = None
        if self.mcp_tool_snapshot_service is not None:
            try:
                mcp_tool_snapshot = self.mcp_tool_snapshot_service.verify(job.id)
            except Exception as exc:
                if fail_on_error:
                    self.status_service.fail(
                        job.id,
                        getattr(exc, "safe_message", str(exc)),
                    )
                raise
        if job.business_application_id:
            if self.business_authorization_service is None:
                if fail_on_error:
                    self.status_service.fail(job_id, "业务应用授权服务暂时不可用")
                raise PermissionDenied(
                    "Business authorization service is unavailable",
                    safe_message="业务应用授权服务暂时不可用",
                    error_code="business_authorization_unavailable",
                )
            try:
                decision = self.business_authorization_service.require(
                    user_id=job.internal_user_id or job.requester_id,
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
                if fail_on_error:
                    self.status_service.fail(job_id, exc.safe_message)
                raise
            self.audit_service.record(
                "authorization.business.worker_start",
                status="SUCCEEDED",
                summary="Business authorization allowed worker start",
                job_id=job_id,
                actor_id=job.internal_user_id or job.requester_id,
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
        attempt_invocation_id = f"{job.id}.attempt-{job.retry_count}"
        self.repository.record_execution_policy_usage(
            job.id,
            tool_call_count=0,
            exhausted=False,
        )
        try:
            context = self.context_builder.build(job)
            if mcp_tool_snapshot is None:
                raise PermissionDenied(
                    "Job MCP Tool Snapshot is unavailable",
                    safe_message="此 Job 缺少 MCP 工具快照",
                    error_code="mcp_tool_snapshot_missing",
                )
            context = replace(
                context,
                job_tool_snapshot_hash=str(mcp_tool_snapshot["snapshot_hash"]),
            )
            self.repository.add_step(
                job_id=job.id,
                step_type="tool_call",
                title="Context search completed",
                content="Relevant ER and business-flow context retrieved.",
            )
            run_request = AgentRunRequest(
                job_id=job.id,
                user_id=job.internal_user_id or job.requester_id,
                project_code=job.project_code,
                context=context,
                invocation_id=attempt_invocation_id,
            )
            with self._active_lock:
                self._active_requests[job.id] = run_request
            try:
                result = self.runtime_client.run(run_request)
            finally:
                with self._active_lock:
                    if self._active_requests.get(job.id) is run_request:
                        self._active_requests.pop(job.id, None)
            if self.after_runtime_result_hook is not None:
                self.after_runtime_result_hook()
            if result.runtime_provenance:
                self.repository.record_runtime_provenance(
                    job.id,
                    result.runtime_provenance,
                )
            self._persist_run_audit(
                job=job,
                invocation_id=attempt_invocation_id,
                status="SUCCEEDED",
                audit=result.run_audit,
            )
            self._persist_tool_events(job.id, result.tool_events)
            self._record_execution_policy_usage(
                job.id,
                invocation_id=attempt_invocation_id,
                tool_events=result.tool_events,
                exhausted=False,
            )
            final_answer, rejected_confirmation_claim = _guard_confirmation_claim(
                final_answer=result.final_answer,
                allowed_tools=context.allowed_tools,
                tool_events=result.tool_events,
            )
            if rejected_confirmation_claim:
                self.audit_service.record(
                    "agent.external_action_confirmation_claim.rejected",
                    status="DENIED",
                    summary="Unverified external action confirmation claim was replaced",
                    job_id=job.id,
                    actor_id=job.internal_user_id or job.requester_id,
                    payload={"invocation_id": attempt_invocation_id},
                )
            self.repository.add_step(
                job_id=job.id,
                step_type="model_completed",
                title="Model execution completed",
                content="Claude runtime returned a final diagnostic report.",
            )
            self._persist_success(
                job=job,
                final_answer=final_answer,
                worker_id=worker_id,
                correlation_id=correlation_id,
            )
            self.execution_audit_repository.rebuild_summary(job.id)
            return final_answer
        except Exception as exc:
            safe_message = getattr(exc, "safe_message", str(exc))
            tool_events = getattr(exc, "tool_events", [])
            self._persist_run_audit(
                job=job,
                invocation_id=attempt_invocation_id,
                status=(
                    "CANCELLED"
                    if getattr(exc, "error_code", "") == "runtime_cancelled"
                    else "FAILED"
                ),
                audit=getattr(exc, "run_audit", {}),
            )
            self._persist_tool_events(job.id, tool_events)
            self._record_execution_policy_usage(
                job.id,
                invocation_id=attempt_invocation_id,
                tool_events=tool_events,
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
            if fail_on_error:
                self.status_service.fail(job.id, safe_message)
            self.execution_audit_repository.rebuild_summary(job.id)
            diagnostics = getattr(exc, "diagnostics", {})
            runtime_provenance = (
                diagnostics.get("runtime_provenance") if isinstance(diagnostics, dict) else None
            )
            if isinstance(runtime_provenance, dict):
                self.repository.record_runtime_provenance(job.id, runtime_provenance)
            raise

    def _persist_run_audit(
        self,
        *,
        job: AgentJob,
        invocation_id: str,
        status: str,
        audit: object,
    ) -> None:
        if not isinstance(audit, dict) or not audit:
            return
        identity = audit.get("runtime_identity")
        identity = identity if isinstance(identity, dict) else {}
        persisted_invocation_id = str(identity.get("invocation_id") or invocation_id)
        request_digest = str(identity.get("request_digest") or "")
        if len(request_digest) != 64:
            request_digest = canonical_json_sha256(audit)
        self.repository.record_run_audit(
            job_id=job.id,
            invocation_id=persisted_invocation_id,
            request_digest=request_digest,
            attempt_no=job.retry_count + 1,
            status=status,
            audit=audit,
        )

    def _record_execution_policy_usage(
        self,
        job_id: str,
        *,
        invocation_id: str,
        tool_events: list[dict[str, object]],
        exhausted: bool,
    ) -> None:
        persisted_count = self.repository.count_tool_calls_for_invocation(
            job_id,
            invocation_id,
        )
        self.repository.record_execution_policy_usage(
            job_id,
            tool_call_count=max(
                persisted_count,
                _runtime_tool_attempt_count(tool_events),
            ),
            exhausted=exhausted,
        )

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

    def _persist_tool_events(self, job_id: str, tool_events: list[dict[str, object]]) -> None:
        job = self.repository.get_job(job_id)
        expected_invocation_id = f"{job.id}.attempt-{job.retry_count}"
        published: set[tuple[str, str]] = set()
        if self.mcp_tool_snapshot_service is not None:
            verified = self.mcp_tool_snapshot_service.verify(job_id)
            published = {
                (str(item.get("server_code") or ""), str(item.get("tool_identifier") or ""))
                for item in verified["snapshot"].get("tools") or []
                if isinstance(item, dict)
            }
        for event in tool_events:
            invocation_id = str(event.get("invocation_id") or expected_invocation_id)
            runtime_tool_call_id = str(event.get("tool_call_id") or "")
            if not invocation_id or not runtime_tool_call_id:
                continue
            tool_name = str(event.get("tool_name", "unknown"))
            declared_origin = str(event.get("tool_origin") or "")
            declared_server = str(event.get("server_code") or "")
            if declared_origin in {"mcp", "sdk_builtin", "sdk_custom", "unknown"}:
                tool_origin = declared_origin
            elif (declared_server, tool_name) in published:
                tool_origin = "mcp"
            else:
                tool_origin = "unknown"
            server_code = declared_server if tool_origin == "mcp" else None
            if tool_origin == "mcp" and (server_code, tool_name) not in published:
                tool_origin = "unknown"
                server_code = None
            duration = _int_value(event.get("duration_ms"))
            response = _dict_value(event.get("response_summary"))
            failure = event.get("failure")
            if isinstance(failure, dict):
                response = {**response, "failure": failure}
            self.repository.upsert_runtime_tool_call(
                job_id=job_id,
                invocation_id=invocation_id,
                runtime_tool_call_id=runtime_tool_call_id,
                tool_origin=tool_origin,
                server_code=server_code,
                tool_name=tool_name,
                request_payload=_dict_value(event.get("request_summary")),
                response_summary=response,
                status=str(event.get("status", "SUCCEEDED")),
                duration_ms=duration,
                risk_level=str(event.get("risk_level", "medium")),
                mcp_call_id=(str(event.get("mcp_call_id")) if event.get("mcp_call_id") else None),
                persisted_tool_call_id=(
                    str(event.get("persisted_tool_call_id"))
                    if event.get("persisted_tool_call_id")
                    else None
                ),
            )


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {"payload": str(value)}


def _runtime_tool_attempt_count(tool_events: list[dict[str, object]]) -> int:
    stable_ids: set[str] = set()
    identityless_attempts = 0
    for event in tool_events:
        tool_call_id = str(event.get("tool_call_id") or "").strip()
        if tool_call_id:
            stable_ids.add(tool_call_id)
        else:
            identityless_attempts += 1
    return len(stable_ids) + identityless_attempts


_CONFIRMATION_CLAIM_PHRASES = (
    "确认卡已创建",
    "确认卡片已创建",
    "确认卡已生成",
    "确认卡片已生成",
    "确认卡已提交",
    "确认卡片已提交",
    "处于等待确认状态",
    "处于待确认状态",
)
_UNVERIFIED_CONFIRMATION_MESSAGE = (
    "外部操作确认卡未创建：本次 Agent 没有实际完成确认型 Tool Call。"
    "请不要等待或点击卡片；可在修正后重新发起请求。"
)


def _guard_confirmation_claim(
    *,
    final_answer: str,
    allowed_tools: list[str],
    tool_events: list[dict[str, object]],
) -> tuple[str, bool]:
    confirmation_tools = {
        tool_name
        for tool_name in allowed_tools
        if (definition := MCP_TOOL_MANIFEST.get(tool_name)) is not None
        and definition.effect == "mutation"
        and definition.confirmation_policy != "none"
    }
    claims_current_confirmation = "confirmation_required" in final_answer and any(
        phrase in final_answer for phrase in _CONFIRMATION_CLAIM_PHRASES
    )
    if not confirmation_tools or not claims_current_confirmation:
        return final_answer, False
    has_successful_confirmation_tool = any(
        str(event.get("tool_name") or "") in confirmation_tools
        and str(event.get("status") or "").upper() == "SUCCEEDED"
        for event in tool_events
    )
    if has_successful_confirmation_tool:
        return final_answer, False
    return _UNVERIFIED_CONFIRMATION_MESSAGE, True


def _int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


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
