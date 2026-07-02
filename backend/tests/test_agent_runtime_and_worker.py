from __future__ import annotations

import unittest

from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.modules.agent.domain.runtime import AgentRunResult
from app.shared.exceptions import DiagnosticLoopExhausted, RetryableExecutionError
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import container


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
                    "tool_name": "query_database",
                    "request_payload": {"payload": '{"sql":"select 1"}', "truncated": False},
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
                    "tool_name": "query_database",
                    "request_payload": {"payload": '{"sql":"select 1"}', "truncated": False},
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
                    "tool_name": "query_loki",
                    "request_payload": {
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


class AgentRuntimeAndWorkerTests(unittest.TestCase):
    def test_agent_executor_completes_with_evidence_report(self) -> None:
        c = container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="runtime-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="Why is order waiting material?",
                project_code="default",
            )
        )

        report = c.agent_executor.execute(job.id)
        stored = c.agent_repository.get_job(job.id)

        self.assertIn("Evidence:", report)
        self.assertEqual(JobStatus.SUCCEEDED, stored.status)
        self.assertEqual(2, c.agent_repository.count_rows("agent_tool_call"))
        self.assertEqual(1, c.agent_repository.count_rows("agent_artifact"))
        steps = c.database.execute(
            "select step_type, content from agent_step where job_id = ?", (job.id,)
        )
        self.assertNotIn("private chain", " ".join(row["content"] for row in steps).lower())

    def test_worker_routes_retryable_failure_to_retry_queue(self) -> None:
        c = container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="retry-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="retry please",
                project_code="default",
            )
        )
        c.agent_executor.claude_client = FailingClaudeClient()  # type: ignore[assignment]

        message = AgentJobMessage(job_id=job.id, correlation_id="corr-1")
        try:
            c.agent_executor.execute(message.job_id, fail_on_error=False)
        except RetryableExecutionError as exc:
            action = c.retry_service.handle_failure(
                c.agent_repository.get_job(job.id), exc, message.correlation_id
            )
        else:
            action = "none"

        self.assertEqual("retry", action)
        self.assertEqual(1, len(c.message_bus.retries))
        self.assertEqual(JobStatus.PENDING, c.agent_repository.get_job(job.id).status)

    def test_retry_pending_job_keeps_failure_tool_events(self) -> None:
        c = container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="retry-tool-events-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="retry with events",
                project_code="default",
            )
        )
        c.agent_executor.claude_client = FailingClaudeClientWithEvents()  # type: ignore[assignment]
        message = AgentJobMessage(job_id=job.id, correlation_id="corr-1")

        try:
            c.agent_executor.execute(message.job_id, fail_on_error=False)
        except RetryableExecutionError as exc:
            action = c.retry_service.handle_failure(
                c.agent_repository.get_job(job.id), exc, message.correlation_id
            )
        else:
            action = "none"

        self.assertEqual("retry", action)
        self.assertEqual(JobStatus.PENDING, c.agent_repository.get_job(job.id).status)
        tool_calls = c.agent_repository.list_tool_calls(job.id)
        self.assertIn("query_database", [call["tool_name"] for call in tool_calls])

    def test_max_turns_failure_is_not_retried_and_keeps_tool_events(self) -> None:
        c = container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="max-turns-tool-events-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="max turns",
                project_code="default",
            )
        )
        c.agent_executor.claude_client = MaxTurnsClaudeClient()  # type: ignore[assignment]
        message = AgentJobMessage(job_id=job.id, correlation_id="corr-1")

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
        c = container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="tool-event-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
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
        c = container()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="worker-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="diagnose order",
                project_code="default",
            )
        )
        worker = AgentJobWorker(c.settings, container=c)

        worker.run_once()
        stored = c.agent_repository.get_job(job.id)
        self.assertEqual(JobStatus.SUCCEEDED, stored.status)
        self.assertEqual(1, len(c.result_delivery_service.sent_messages))

        worker.handle(AgentJobMessage(job_id=job.id, correlation_id="duplicate"))
        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)
        self.assertEqual(1, len(c.result_delivery_service.sent_messages))


if __name__ == "__main__":
    unittest.main()
