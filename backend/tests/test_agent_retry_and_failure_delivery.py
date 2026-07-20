from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.retry_recovery_service import RetryRecoveryService
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import container


class _CaptureAdapter(DeliveryAdapter):
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, *, connector: object, route: object, title: str, text: str) -> None:
        del connector, route, title
        self.sent.append(text)


class _FailingPublisher:
    def publish_retry(self, job_id: str, correlation_id: str, delay_seconds: int) -> None:
        del job_id, correlation_id, delay_seconds
        raise RuntimeError("broker unavailable secret=do-not-store")

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"Unexpected publisher call: {name}")


class _FailOnceClient:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: object) -> object:
        from app.modules.agent.domain.runtime import AgentRunResult

        del request
        self.calls += 1
        if self.calls == 1:
            raise RetryableExecutionError(
                "synthetic transient",
                safe_message="模型服务暂时不可用",
                error_code="synthetic_transient",
            )
        return AgentRunResult(final_answer="recovered result")


class _AlwaysFailClient:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: object) -> object:
        del request
        self.calls += 1
        raise RetryableExecutionError(
            "synthetic persistent transient",
            safe_message="模型服务持续不可用",
            error_code="synthetic_transient",
        )


class AgentRetryAndFailureDeliveryTests(unittest.TestCase):
    def _create_job(self, c: object, key: str, **kwargs: object) -> object:
        return c.create_agent_job_service.execute(  # type: ignore[attr-defined]
            CreateAgentJobCommand(
                idempotency_key=key,
                requester_id="local-user",
                external_conversation_id=f"conversation-{key}",
                user_message="synthetic retry test",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                project_code="default",
                **kwargs,
            )
        )

    def test_retry_wait_metadata_due_claim_and_duplicate_claim(self) -> None:
        c = container()
        job = self._create_job(c, "retry-wait")
        claimed = c.agent_repository.claim_job(job.id, "worker-1")
        self.assertIsNotNone(claimed)

        action = c.retry_service.handle_failure(
            claimed,
            RetryableExecutionError(
                "transport failed",
                safe_message="模型服务暂时不可用",
                error_code="claude_transient_error",
            ),
            "corr-1",
        )
        waiting = c.agent_repository.get_job(job.id)
        self.assertEqual("retry", action)
        self.assertEqual(JobStatus.RETRY_WAIT, waiting.status)
        self.assertEqual(1, waiting.retry_count)
        self.assertEqual("claude_transient_error", waiting.last_error_code)
        self.assertIsNotNone(waiting.last_error_at)
        self.assertIsNotNone(waiting.next_retry_at)
        self.assertIsNone(c.agent_repository.claim_job(job.id, "worker-early"))

        c.database.execute(
            "update agent_job set next_retry_at = ? where id = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), job.id),
        )
        retry_claim = c.agent_repository.claim_job(job.id, "worker-2")
        duplicate = c.agent_repository.claim_job(job.id, "worker-3")
        self.assertIsNotNone(retry_claim)
        self.assertIsNone(duplicate)
        self.assertEqual(job.internal_user_id, retry_claim.internal_user_id)
        self.assertEqual(job.agent_publication_id, retry_claim.agent_publication_id)
        self.assertEqual(job.reply_route, retry_claim.reply_route)

    def test_retry_publish_failure_leaves_recoverable_retry_wait(self) -> None:
        c = container()
        job = self._create_job(c, "publish-failure")
        claimed = c.agent_repository.claim_job(job.id, "worker")
        c.retry_service.publisher = _FailingPublisher()  # type: ignore[assignment]

        action = c.retry_service.handle_failure(
            claimed,
            RetryableExecutionError(
                "transport failed",
                safe_message="模型服务暂时不可用",
                error_code="claude_transient_error",
            ),
            "corr-publish-failure",
        )
        persisted = c.agent_repository.get_job(job.id)
        self.assertEqual("retry_dispatch_failed", action)
        self.assertEqual(JobStatus.RETRY_WAIT, persisted.status)
        events = c.database.execute(
            "select event_type from audit_event where job_id = ?", (job.id,)
        )
        self.assertIn("job.retry.publish_failed", [row["event_type"] for row in events])

    def test_early_retry_message_is_rescheduled_without_model_call(self) -> None:
        c = container()
        job = self._create_job(c, "early-retry")
        claimed = c.agent_repository.claim_job(job.id, "worker")
        c.retry_service.handle_failure(
            claimed,
            RetryableExecutionError("temporary", error_code="temporary"),
            "corr-early",
        )
        before = len(c.message_bus.retries)
        worker = AgentJobWorker(c.settings, container=c)
        worker.handle(AgentJobMessage(job.id, "corr-early-duplicate"))
        self.assertEqual(before + 1, len(c.message_bus.retries))
        self.assertEqual(JobStatus.RETRY_WAIT, c.agent_repository.get_job(job.id).status)

    def test_terminal_failure_is_safe_and_delivered_once(self) -> None:
        c = container()
        adapter = _CaptureAdapter()
        c.result_delivery_service.adapters["test_capture"] = adapter
        job = self._create_job(
            c,
            "terminal-failure",
            reply_route={"type": "test_capture", "target": {}},
        )
        claimed = c.agent_repository.claim_job(job.id, "worker")
        error = NonRetryableExecutionError(
            "provider http://user:password@example.invalid?token=secret failed",
            safe_message="provider http://example.invalid?token=secret failed",
            error_code="provider_failure",
        )
        action = c.retry_service.handle_failure(claimed, error, "corr-terminal")
        self.assertEqual("dead", action)
        c.result_delivery_service.deliver_job_failure(
            job.id, error.safe_message, error_code=error.error_code
        )
        c.result_delivery_service.deliver_job_failure(
            job.id, error.safe_message, error_code=error.error_code
        )
        self.assertEqual(1, len(adapter.sent))
        payload = json.loads(adapter.sent[0])
        self.assertEqual("provider_failure", payload["error_code"])
        self.assertEqual(job.id, payload["job_id"])
        self.assertNotIn("secret", payload["message"])
        self.assertNotIn("http", payload["message"].lower())

    def test_recovery_dry_run_has_no_writes_and_apply_is_idempotent(self) -> None:
        c = container()
        job = self._create_job(c, "legacy-recovery")
        c.database.execute(
            """
            update agent_job set retry_count = 1, error_message = ?, status = ?,
                locked_at = null, locked_by = null where id = ?
            """,
            ("legacy safe error", JobStatus.PENDING.value, job.id),
        )
        service = RetryRecoveryService(
            repository=c.agent_repository,
            publisher=c.publisher,
            audit_service=c.audit_service,
            queue_settings=c.settings.queue,
        )
        dry_run = service.reconcile(job_ids=[job.id])
        self.assertEqual("dry-run", dry_run["mode"])
        self.assertEqual(JobStatus.PENDING, c.agent_repository.get_job(job.id).status)
        self.assertNotIn("http", json.dumps(dry_run).lower())

        applied = service.reconcile(apply=True, job_ids=[job.id], actor_id="test-admin")
        repeated = service.reconcile(apply=True, job_ids=[job.id], actor_id="test-admin")
        self.assertEqual("published", applied["jobs"][0]["apply_status"])
        self.assertEqual(JobStatus.RETRY_WAIT, c.agent_repository.get_job(job.id).status)
        self.assertEqual(0, repeated["candidate_count"])

    def test_recovery_publish_failure_is_audited_and_remains_retry_wait(self) -> None:
        c = container()
        job = self._create_job(
            c,
            "legacy-recovery-publish-failure",
            reply_route={
                "type": "dingtalk_stream_session_webhook",
                "target": {"session_webhook": "https://secret.invalid?token=do-not-print"},
            },
        )
        c.database.execute(
            """
            update agent_job set retry_count = 1, error_message = ?, status = ?,
                locked_at = null, locked_by = null where id = ?
            """,
            ("legacy safe error", JobStatus.PENDING.value, job.id),
        )
        service = RetryRecoveryService(
            repository=c.agent_repository,
            publisher=_FailingPublisher(),  # type: ignore[arg-type]
            audit_service=c.audit_service,
            queue_settings=c.settings.queue,
        )
        dry_run = service.reconcile(job_ids=[job.id])
        self.assertNotIn("secret.invalid", json.dumps(dry_run))
        applied = service.reconcile(apply=True, job_ids=[job.id])
        self.assertEqual("publish_failed", applied["jobs"][0]["apply_status"])
        self.assertEqual(JobStatus.RETRY_WAIT, c.agent_repository.get_job(job.id).status)

    def test_recovery_reports_stale_lock_but_not_recent_lock(self) -> None:
        c = container()
        stale = self._create_job(c, "stale-lock")
        recent = self._create_job(c, "recent-lock")
        c.database.execute(
            """
            update agent_job set retry_count = 1, error_message = 'legacy', status = ?,
                locked_at = ?, locked_by = 'old-worker' where id = ?
            """,
            (
                JobStatus.PENDING.value,
                (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                stale.id,
            ),
        )
        c.database.execute(
            """
            update agent_job set retry_count = 1, error_message = 'legacy', status = ?,
                locked_at = ?, locked_by = 'active-worker' where id = ?
            """,
            (JobStatus.PENDING.value, datetime.now(UTC).isoformat(), recent.id),
        )
        service = RetryRecoveryService(
            repository=c.agent_repository,
            publisher=c.publisher,
            audit_service=c.audit_service,
            queue_settings=c.settings.queue,
        )
        report = service.reconcile(job_ids=[stale.id, recent.id])
        self.assertEqual([stale.id], [row["job_id"] for row in report["jobs"]])

    def test_first_failure_then_success_reuses_same_job(self) -> None:
        c = container()
        client = _FailOnceClient()
        c.agent_executor.claude_client = client  # type: ignore[assignment]
        job = self._create_job(c, "fail-once")
        message = c.message_bus.jobs.popleft()
        worker = AgentJobWorker(c.settings, container=c)
        worker.handle(message)
        self.assertEqual(JobStatus.RETRY_WAIT, c.agent_repository.get_job(job.id).status)

        c.database.execute(
            "update agent_job set next_retry_at = ? where id = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), job.id),
        )
        retry_message, _ = c.message_bus.retries.popleft()
        worker.handle(retry_message)
        completed = c.agent_repository.get_job(job.id)
        self.assertEqual(JobStatus.SUCCEEDED, completed.status)
        self.assertEqual(1, completed.retry_count)
        self.assertEqual(2, client.calls)

    def test_persistent_failure_exhausts_retries_and_delivers_once(self) -> None:
        c = container()
        adapter = _CaptureAdapter()
        c.result_delivery_service.adapters["test_capture"] = adapter
        client = _AlwaysFailClient()
        c.agent_executor.claude_client = client  # type: ignore[assignment]
        job = self._create_job(
            c,
            "always-fails",
            reply_route={"type": "test_capture", "target": {}},
        )
        worker = AgentJobWorker(c.settings, container=c)
        message = c.message_bus.jobs.popleft()

        for expected_retry in range(1, job.max_retry_count + 1):
            worker.handle(message)
            waiting = c.agent_repository.get_job(job.id)
            self.assertEqual(JobStatus.RETRY_WAIT, waiting.status)
            self.assertEqual(expected_retry, waiting.retry_count)
            self.assertEqual([], adapter.sent)
            c.database.execute(
                "update agent_job set next_retry_at = ? where id = ?",
                ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), job.id),
            )
            message, _ = c.message_bus.retries.popleft()

        worker.handle(message)
        failed = c.agent_repository.get_job(job.id)
        self.assertEqual(JobStatus.FAILED, failed.status)
        self.assertEqual(job.max_retry_count + 1, client.calls)
        self.assertEqual(1, len(adapter.sent))
        self.assertEqual(1, len(c.message_bus.dead_letters))
        event_types = [
            row["event_type"]
            for row in c.database.execute(
                "select event_type from audit_event where job_id = ?", (job.id,)
            )
        ]
        self.assertEqual(job.max_retry_count, event_types.count("job.retry.scheduled"))
        self.assertIn("job.dead_letter.published", event_types)


if __name__ == "__main__":
    unittest.main()
