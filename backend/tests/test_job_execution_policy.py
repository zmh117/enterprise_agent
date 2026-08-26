from __future__ import annotations

import json

import pytest

from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.agent.domain.runtime import AgentRunResult, ToolCallBudget
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.execution_policy import (
    EffectiveExecutionPolicyResolver,
    JobExecutionPolicySnapshot,
)
from app.modules.job.domain.job_status import JobStatus
from app.shared.config import ExecutionSettings
from app.shared.exceptions import (
    ExecutionPolicyExceeded,
    ExecutionTimeout,
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import container, persisted_agent_job_message


class _CaptureFailureDeliveryAdapter(DeliveryAdapter):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, *, connector: object, route: object, title: str, text: str) -> None:
        del connector, route, title
        self.messages.append(text)


def test_business_application_policy_only_tightens_agent_limits() -> None:
    resolver = EffectiveExecutionPolicyResolver(
        ExecutionSettings(max_turns=20, timeout_seconds=600, max_tool_calls=30)
    )
    snapshot = resolver.resolve(
        application_policy={
            "max_turns": 40,
            "timeout_seconds": 120,
            "max_tool_calls": 0,
        },
        agent_snapshot={"execution": {"max_turns": 12, "timeout_seconds": 300}},
        sources={
            "business_application_publication_id": "app-publication",
            "agent_publication_id": "agent-publication",
        },
    )

    assert snapshot.requested.to_dict() == {
        "max_turns": 40,
        "timeout_seconds": 120,
        "max_tool_calls": 0,
    }
    assert snapshot.effective.to_dict() == {
        "max_turns": 12,
        "timeout_seconds": 120,
        "max_tool_calls": 0,
    }
    assert snapshot.sources["source_kind"] == "business_application"


def test_non_business_job_uses_versioned_runtime_default_snapshot() -> None:
    c = container()
    c.create_agent_job_service.published_agent_runtime_enabled = False
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="policy-default",
            external_conversation_id="conversation-policy",
            requester_id="local-user",
            user_message="check",
        )
    )

    parsed = JobExecutionPolicySnapshot.from_dict(job.execution_policy)
    assert parsed.schema_version == 1
    assert parsed.sources["source_kind"] == "runtime_default"
    assert parsed.effective.max_tool_calls == c.settings.execution.max_tool_calls


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"schema_version": 2},
        {
            "schema_version": 1,
            "requested": {},
            "effective": {},
            "sources": {"source_kind": "runtime_default"},
        },
        {
            "schema_version": "1",
            "requested": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "effective": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "sources": {"source_kind": "runtime_default"},
        },
        {
            "schema_version": 1,
            "requested": {
                "max_turns": True,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "effective": {
                "max_turns": 1,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "sources": {"source_kind": "runtime_default"},
        },
    ],
)
def test_invalid_policy_snapshots_fail_closed(value: object) -> None:
    with pytest.raises(NonRetryableExecutionError) as raised:
        JobExecutionPolicySnapshot.from_dict(value)  # type: ignore[arg-type]
    assert raised.value.error_code == "execution_policy_integrity_error"


def test_repository_rejects_job_without_execution_policy() -> None:
    c = container()
    session = c.agent_repository.create_session(
        project_code="default",
        source_channel="debug_api",
        source_connector_id="connector-debug-api",
        external_conversation_id="conversation",
        requester_id="local-user",
    )
    with pytest.raises(NonRetryableExecutionError):
        c.agent_repository.create_job(
            session_id=session.id,
            idempotency_key="missing-policy",
            project_code="default",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            requester_id="local-user",
            input_message="check",
            max_retry_count=0,
        )


def test_worker_rejects_missing_policy_before_context_tools_or_model() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="invalid-worker-policy",
            external_conversation_id="conversation-invalid-policy",
            requester_id="local-user",
            user_message="check",
        )
    )
    c.database.execute(
        "update agent_job set execution_policy_json = null where id = ?",
        (job.id,),
    )

    class RecordingClient:
        calls = 0

        def run(self, request: object) -> object:
            del request
            self.calls += 1
            raise AssertionError("model must not be called")

    client = RecordingClient()
    c.agent_executor.runtime_client = client
    with pytest.raises(NonRetryableExecutionError) as raised:
        c.agent_executor.execute(job.id)

    assert raised.value.error_code == "execution_policy_integrity_error"
    assert client.calls == 0
    assert c.agent_repository.list_tool_calls(job.id) == []


def test_tool_budget_counts_rejected_attempt() -> None:
    budget = ToolCallBudget(maximum=1)
    budget.consume()
    assert budget.exhausted is False
    with pytest.raises(ExecutionPolicyExceeded):
        budget.consume()
    assert budget.attempted == 2
    assert budget.exhausted is True


def test_executor_counts_server_persisted_mcp_call_without_runtime_tool_event() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="persisted-mcp-policy-usage",
            external_conversation_id="conversation-persisted-mcp-policy-usage",
            requester_id="local-user",
            user_message="check",
        )
    )

    class PersistingMcpClient:
        def run(self, request: object) -> AgentRunResult:
            invocation_id = str(getattr(request, "invocation_id"))
            c.agent_repository.add_tool_call(
                job_id=job.id,
                tool_name="ones_work_item_search",
                request_payload={},
                response_summary={"total": 1, "truncated": False},
                status="SUCCEEDED",
                duration_ms=4,
                risk_level="low",
                invocation_id=invocation_id,
                tool_origin="mcp",
                server_code="ones-mcp",
                mcp_call_id="mcp-call-policy-usage",
                persisted_by="mcp_server",
            )
            return AgentRunResult(final_answer="safe final answer", tool_events=[])

    c.agent_executor.runtime_client = PersistingMcpClient()

    c.agent_executor.execute(job.id)

    persisted = c.agent_repository.get_job(job.id)
    assert persisted.execution_policy_tool_call_count == 1
    assert len(c.agent_repository.list_tool_calls(job.id)) == 1


def test_executor_counts_runtime_tool_lifecycle_as_one_attempt() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="runtime-tool-lifecycle-policy-usage",
            external_conversation_id="conversation-runtime-tool-lifecycle-policy-usage",
            requester_id="local-user",
            user_message="check",
        )
    )
    tool_events = [
        {
            "tool_call_id": "runtime-tool-call-1",
            "tool_name": "governed_safe_tool",
            "tool_origin": "sdk_custom",
            "status": "STARTED",
        },
        {
            "tool_call_id": "runtime-tool-call-1",
            "tool_name": "governed_safe_tool",
            "tool_origin": "sdk_custom",
            "status": "SUCCEEDED",
            "response_summary": {"available": True},
        },
    ]

    class LifecycleClient:
        def run(self, request: object) -> AgentRunResult:
            del request
            return AgentRunResult(
                final_answer="safe final answer",
                tool_events=tool_events,
            )

    c.agent_executor.runtime_client = LifecycleClient()

    c.agent_executor.execute(job.id)

    persisted = c.agent_repository.get_job(job.id)
    assert persisted.execution_policy_tool_call_count == 1
    assert len(c.agent_repository.list_tool_calls(job.id)) == 1


def test_executor_persists_attempt_usage_and_exhaustion_separately_from_context_tools() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="persist-policy-usage",
            external_conversation_id="conversation-policy-usage",
            requester_id="local-user",
            user_message="check",
        )
    )
    tool_events = [
        {
            "tool_name": "query_database",
            "request_payload": {"sql": "select 1"},
            "response_summary": {"row_count": 1},
            "status": "SUCCEEDED",
            "duration_ms": 1,
            "risk_level": "medium",
        },
        {
            "tool_name": "query_database",
            "request_payload": {"sql": "select 1"},
            "response_summary": {"error": "budget exhausted"},
            "status": "REJECTED",
            "duration_ms": 0,
            "risk_level": "medium",
        },
    ]

    class ExhaustingClient:
        def run(self, request: object) -> object:
            del request
            raise ExecutionPolicyExceeded(
                "budget exhausted",
                safe_message="budget exhausted",
                error_code="execution_policy_max_tool_calls_exhausted",
                tool_events=tool_events,
            )

    c.agent_executor.runtime_client = ExhaustingClient()
    with pytest.raises(ExecutionPolicyExceeded):
        c.agent_executor.execute(job.id)

    persisted = c.agent_repository.get_job(job.id)
    assert persisted.execution_policy_tool_call_count == 2
    assert persisted.execution_policy_exhausted is True


def test_worker_delivers_safe_non_retryable_tool_budget_failure_once() -> None:
    c = container()
    adapter = _CaptureFailureDeliveryAdapter()
    c.result_delivery_service.adapters["policy_failure_capture"] = adapter
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="worker-policy-exhaustion",
            external_conversation_id="conversation-policy-exhaustion",
            requester_id="local-user",
            user_message="check",
            reply_route={"type": "policy_failure_capture", "target": {}},
        )
    )
    tool_events = [
        {
            "tool_name": "query_database",
            "request_payload": {"sql": "select 1"},
            "response_summary": {"row_count": 1},
            "status": "SUCCEEDED",
            "duration_ms": 1,
            "risk_level": "medium",
        },
        {
            "tool_name": "query_database",
            "request_payload": {},
            "response_summary": {"error": "tool call budget exhausted"},
            "status": "REJECTED",
            "duration_ms": 0,
            "risk_level": "medium",
        },
    ]

    class ExhaustingClient:
        def run(self, request: object) -> object:
            del request
            raise ExecutionPolicyExceeded(
                "internal detail must not be delivered",
                safe_message="Agent 工具调用次数已达到本次执行上限",
                error_code="execution_policy_max_tool_calls_exhausted",
                tool_events=tool_events,
            )

    c.agent_executor.runtime_client = ExhaustingClient()
    worker = AgentJobWorker(c.settings, container=c)
    message = persisted_agent_job_message(c, job.id)

    worker.handle(message)
    worker.handle(message)
    delivery = c.delivery_dispatcher.dispatch_pending(limit=1)

    persisted = c.agent_repository.get_job(job.id)
    assert persisted.status == JobStatus.FAILED
    assert persisted.retry_count == 0
    assert persisted.last_error_code == "execution_policy_max_tool_calls_exhausted"
    assert persisted.execution_policy_tool_call_count == 2
    assert persisted.execution_policy_exhausted is True
    assert c.agent_repository.get_dispatch_event_for_job(job.id) is not None
    assert "job.dead.persisted" in {
        row["event_type"] for row in c.audit_repository.list_for_job(job.id)
    }
    assert delivery.succeeded == 1
    assert len(adapter.messages) == 1
    delivered = json.loads(adapter.messages[0])
    assert delivered["error_code"] == "execution_policy_max_tool_calls_exhausted"
    assert "internal detail" not in delivered["message"]


@pytest.mark.parametrize("failure_type", [ExecutionTimeout, RetryableExecutionError])
def test_worker_marks_runtime_timeout_terminal_without_retry_and_delivers_once(
    failure_type: type[ExecutionTimeout | RetryableExecutionError],
) -> None:
    c = container()
    adapter = _CaptureFailureDeliveryAdapter()
    c.result_delivery_service.adapters["timeout_failure_capture"] = adapter
    failure_name = failure_type.__name__.lower()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=f"worker-runtime-timeout-{failure_name}",
            external_conversation_id=f"conversation-runtime-timeout-{failure_name}",
            requester_id="local-user",
            user_message="check",
            reply_route={"type": "timeout_failure_capture", "target": {}},
        )
    )
    tool_events = [
        {
            "tool_call_id": "runtime-timeout-tool-1",
            "tool_name": "query_database",
            "request_payload": {"sql": "select 1"},
            "status": "STARTED",
            "duration_ms": 1,
            "risk_level": "medium",
        }
    ]

    class TimeoutClient:
        def run(self, request: object) -> object:
            del request
            raise failure_type(
                "internal timeout detail must not be delivered",
                safe_message="Claude 运行超时",
                error_code="runtime_timeout",
                tool_events=tool_events,
            )

    c.agent_executor.runtime_client = TimeoutClient()
    worker = AgentJobWorker(c.settings, container=c)
    message = persisted_agent_job_message(c, job.id)

    worker.handle(message)
    worker.handle(message)
    delivery = c.delivery_dispatcher.dispatch_pending(limit=1)

    persisted = c.agent_repository.get_job(job.id)
    assert persisted.status == JobStatus.TIMEOUT
    assert persisted.retry_count == 0
    assert persisted.last_error_code == "runtime_timeout"
    assert persisted.execution_policy_tool_call_count == 1
    assert persisted.execution_policy_exhausted is False
    audit_types = {row["event_type"] for row in c.audit_repository.list_for_job(job.id)}
    assert "job.retry.scheduled" not in audit_types
    assert "job.dead.persisted" in audit_types
    assert delivery.succeeded == 1
    assert len(adapter.messages) == 1
    delivered = json.loads(adapter.messages[0])
    assert delivered["error_code"] == "runtime_timeout"
    assert "internal timeout detail" not in delivered["message"]
