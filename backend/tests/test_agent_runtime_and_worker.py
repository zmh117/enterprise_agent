from __future__ import annotations

import unittest

from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.exceptions import RetryableExecutionError
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import container


class FailingClaudeClient:
    def run(self, request: object) -> object:
        raise RetryableExecutionError("timeout", safe_message="Claude timeout")


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
        self.assertEqual(1, len(c.agent_executor.callback_client.sent_messages))

        worker.handle(AgentJobMessage(job_id=job.id, correlation_id="duplicate"))
        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)
        self.assertEqual(1, len(c.agent_executor.callback_client.sent_messages))


if __name__ == "__main__":
    unittest.main()
