from __future__ import annotations

import unittest

from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.modules.agent.domain.runtime import AgentExecutionContext, AgentRunResult
from app.modules.agent.infrastructure.routed_runtime_client import RuntimeClientRegistry
from app.shared.exceptions import DiagnosticLoopExhausted, RetryableExecutionError
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import (
    container,
    dispatch_pending_deliveries,
    persisted_agent_job_message,
    publish_pending_agent_jobs,
)


def _runtime_container():
    runtime = container(allow_direct_jobs=True)
    runtime.create_agent_job_service.published_agent_runtime_enabled = True
    runtime.create_agent_job_service.runtime_readiness_guard = None
    return runtime


class FailingClaudeClient:
    def run(self, request: object) -> object:
        raise RetryableExecutionError("timeout", safe_message="Claude timeout")


class FailingClaudeClientWithEvents:
    def run(self, request: object) -> object:
        raise RetryableExecutionError(
            "timeout",
            safe_message="Claude timeout",
            tool_events=[
                {
                    "tool_call_id": "sdk-tool-retry-1",
                    "tool_origin": "unknown",
                    "tool_name": "query_database",
                    "request_summary": {"payload": '{"sql":"select 1"}', "truncated": False},
                    "response_summary": {"error": "timeout"},
                    "status": "FAILED",
                    "duration_ms": 7,
                    "risk_level": "medium",
                }
            ],
        )


class MaxTurnsClaudeClient:
    def run(self, request: object) -> object:
        raise DiagnosticLoopExhausted(
            "Reached maximum number of turns (12)",
            safe_message="Claude runtime failed: Reached maximum number of turns (12)",
            error_code="max_turns_exhausted",
            tool_events=[
                {
                    "tool_call_id": "sdk-tool-max-turns-1",
                    "tool_origin": "unknown",
                    "tool_name": "query_database",
                    "request_summary": {"payload": '{"sql":"select 1"}', "truncated": False},
                    "response_summary": {"error": "schema missing"},
                    "status": "FAILED",
                    "duration_ms": 9,
                    "risk_level": "medium",
                }
            ],
        )


class ToolEventClaudeClient:
    def run(self, request: object) -> AgentRunResult:
        return AgentRunResult(
            final_answer="real runtime answer",
            tool_events=[
                {
                    "tool_call_id": "sdk-tool-success-1",
                    "tool_origin": "unknown",
                    "tool_name": "query_loki",
                    "request_summary": {
                        "payload": '{"service":"order-service"}',
                        "truncated": False,
                    },
                    "response_summary": {"payload": '{"line_count":1}', "truncated": False},
                    "status": "SUCCEEDED",
                    "duration_ms": 12,
                    "risk_level": "low",
                }
            ],
        )


class RecordingPythonRuntimeClient:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: object) -> AgentRunResult:
        self.calls += 1
        return AgentRunResult(final_answer="must not run")


class RetiredRuntimeContextBuilder:
    def build(self, job: object) -> AgentExecutionContext:
        return AgentExecutionContext(
            system_role="Historical retired Runtime Job",
            safety_rules=[],
            user_question="synthetic retired Runtime message",
            project_code="default",
            allowed_tools=[],
            tool_restrictions=[],
            skills={},
            retrieved_context={},
            conversation_summary="",
            runtime_kind="typescript-v1",
            runtime_protocol_version="1.2",
        )


class AgentRuntimeAndWorkerTests(unittest.TestCase):
    def test_agent_executor_completes_with_evidence_report(self) -> None:
        c = _runtime_container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="runtime-job",
                external_conversation_id="conversation-1",
                requester_id="local-user",
                user_message="Why is order waiting material?",
                project_code="default",
            )
        )

        report = c.agent_executor.execute(job.id)
        stored = c.agent_repository.get_job(job.id)

        self.assertIn("Evidence:", report)
        self.assertEqual(JobStatus.SUCCEEDED, stored.status)
        self.assertEqual(0, c.agent_repository.count_rows("agent_tool_call"))
        self.assertEqual(1, c.agent_repository.count_rows("agent_artifact"))
        steps = c.database.execute(
            "select step_type, content from agent_step where job_id = ?", (job.id,)
        )
        self.assertNotIn("private chain", " ".join(row["content"] for row in steps).lower())

    def test_worker_routes_retryable_failure_to_retry_queue(self) -> None:
        c = _runtime_container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="retry-job",
                external_conversation_id="conversation-1",
                requester_id="local-user",
                user_message="retry please",
                project_code="default",
            )
        )
        c.agent_executor.claude_client = FailingClaudeClient()  # type: ignore[assignment]

        message = persisted_agent_job_message(c, job.id)
        try:
            c.agent_executor.execute(message.job_id, fail_on_error=False)
        except RetryableExecutionError as exc:
            action = c.retry_service.handle_failure(
                c.agent_repository.get_job(job.id), exc, message.correlation_id
            )
        else:
            action = "none"

        self.assertEqual("retry", action)
        dispatch = c.agent_repository.get_dispatch_event_for_job(job.id)
        self.assertIsNotNone(dispatch)
        self.assertEqual("RETRY_WAIT", dispatch.status.value)
        self.assertEqual(JobStatus.RETRY_WAIT, c.agent_repository.get_job(job.id).status)

    def test_retry_pending_job_keeps_failure_tool_events(self) -> None:
        c = _runtime_container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="retry-tool-events-job",
                external_conversation_id="conversation-1",
                requester_id="local-user",
                user_message="retry with events",
                project_code="default",
            )
        )
        c.agent_executor.claude_client = FailingClaudeClientWithEvents()  # type: ignore[assignment]
        message = persisted_agent_job_message(c, job.id)

        try:
            c.agent_executor.execute(message.job_id, fail_on_error=False)
        except RetryableExecutionError as exc:
            action = c.retry_service.handle_failure(
                c.agent_repository.get_job(job.id), exc, message.correlation_id
            )
        else:
            action = "none"

        self.assertEqual("retry", action)
        self.assertEqual(JobStatus.RETRY_WAIT, c.agent_repository.get_job(job.id).status)
        tool_calls = c.agent_repository.list_tool_calls(job.id)
        self.assertIn("query_database", [call["tool_name"] for call in tool_calls])

    def test_max_turns_failure_is_not_retried_and_keeps_tool_events(self) -> None:
        c = _runtime_container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="max-turns-tool-events-job",
                external_conversation_id="conversation-1",
                requester_id="local-user",
                user_message="max turns",
                project_code="default",
            )
        )
        c.agent_executor.claude_client = MaxTurnsClaudeClient()  # type: ignore[assignment]
        message = persisted_agent_job_message(c, job.id)

        try:
            c.agent_executor.execute(message.job_id, fail_on_error=False)
        except DiagnosticLoopExhausted as exc:
            action = c.retry_service.handle_failure(
                c.agent_repository.get_job(job.id), exc, message.correlation_id
            )
        else:
            action = "none"

        self.assertEqual("dead", action)
        self.assertEqual(JobStatus.FAILED, c.agent_repository.get_job(job.id).status)
        self.assertIn(
            "query_database",
            [call["tool_name"] for call in c.agent_repository.list_tool_calls(job.id)],
        )

    def test_agent_executor_persists_real_runtime_tool_events(self) -> None:
        c = _runtime_container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="tool-event-job",
                external_conversation_id="conversation-1",
                requester_id="local-user",
                user_message="diagnose with real runtime",
                project_code="default",
            )
        )
        c.agent_executor.claude_client = ToolEventClaudeClient()  # type: ignore[assignment]

        c.agent_executor.execute(job.id)
        tool_calls = c.agent_repository.list_tool_calls(job.id)
        tool_names = [call["tool_name"] for call in tool_calls]

        self.assertIn("query_loki", tool_names)
        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)

    def test_worker_consumes_message_and_ignores_duplicate_delivery(self) -> None:
        c = _runtime_container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="worker-job",
                external_conversation_id="conversation-1",
                requester_id="local-user",
                user_message="diagnose order",
                project_code="default",
            )
        )
        worker = AgentJobWorker(c.settings, container=c)

        publish_pending_agent_jobs(c)
        worker.run_once()
        dispatch_pending_deliveries(c)
        stored = c.agent_repository.get_job(job.id)
        self.assertEqual(JobStatus.SUCCEEDED, stored.status)
        self.assertEqual(1, len(c.result_delivery_service.sent_messages))

        worker.handle(persisted_agent_job_message(c, job.id))
        dispatch_pending_deliveries(c)
        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)
        self.assertEqual(1, len(c.result_delivery_service.sent_messages))

    def test_worker_terminalizes_retired_runtime_message_without_python_fallback(self) -> None:
        c = _runtime_container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="retired-runtime-worker-message",
                external_conversation_id="retired-runtime-worker",
                requester_id="local-user",
                user_message="synthetic retired Runtime message",
                project_code="default",
            )
        )
        c.database.execute(
            "update agent_job set agent_runtime_kind = 'typescript-v1', "
            "agent_runtime_protocol_version = '1.2' where id = ?",
            (job.id,),
        )
        python = RecordingPythonRuntimeClient()
        c.agent_executor.claude_client = RuntimeClientRegistry({"python-v1": python})
        c.agent_executor.context_builder = RetiredRuntimeContextBuilder()  # type: ignore[assignment]
        message = persisted_agent_job_message(c, job.id)
        worker = AgentJobWorker(c.settings, container=c)

        worker.handle(message)
        terminal = c.agent_repository.get_job(job.id)
        delivery_count = c.database.execute_one(
            "select count(*) as count from delivery_outbox where job_id = ?",
            (job.id,),
        )
        worker.handle(message)

        self.assertEqual(JobStatus.FAILED, terminal.status)
        self.assertEqual("typescript_agent_runtime_retired", terminal.last_error_code)
        self.assertEqual(0, python.calls)
        self.assertIsNotNone(delivery_count)
        self.assertEqual(1, int(delivery_count["count"]))
        self.assertEqual(
            1,
            int(
                c.database.execute_one(
                    "select count(*) as count from delivery_outbox where job_id = ?",
                    (job.id,),
                )["count"]
            ),
        )


if __name__ == "__main__":
    unittest.main()
