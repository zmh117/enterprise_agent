from __future__ import annotations

import unittest

from app.modules.job.domain.job_status import JobStatus
from backend.tests.helpers import container, dingtalk_payload, dingtalk_sign


class EndToEndTests(unittest.TestCase):
    def test_dingtalk_to_callback_path_with_fakes(self) -> None:
        c = container()
        timestamp = "1710000000000"
        result = c.dingtalk_message_service.handle_webhook(
            payload=dingtalk_payload(),
            timestamp=timestamp,
            sign=dingtalk_sign("test-secret", timestamp),
            correlation_id="corr-1",
        )

        self.assertTrue(result["accepted"])
        c.message_bus.consume_agent_jobs(
            lambda message: c.agent_executor.execute(message.job_id, fail_on_error=True)
        )
        job = c.agent_repository.get_job(str(result["job_id"]))

        self.assertEqual(JobStatus.SUCCEEDED, job.status)
        self.assertIn("read-only diagnostic", job.result or "")
        self.assertGreaterEqual(c.agent_repository.count_rows("audit_event"), 4)

    def test_duplicate_dingtalk_delivery_does_not_publish_twice(self) -> None:
        c = container()
        timestamp = "1710000000000"
        payload = dingtalk_payload(msg_id="dup-msg")
        first = c.dingtalk_message_service.handle_webhook(
            payload=payload,
            timestamp=timestamp,
            sign=dingtalk_sign("test-secret", timestamp),
            correlation_id="corr-1",
        )
        second = c.dingtalk_message_service.handle_webhook(
            payload=payload,
            timestamp=timestamp,
            sign=dingtalk_sign("test-secret", timestamp),
            correlation_id="corr-2",
        )

        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(1, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(1, len(c.message_bus.jobs))


if __name__ == "__main__":
    unittest.main()
