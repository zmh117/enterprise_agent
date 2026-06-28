from __future__ import annotations

import unittest

from backend.tests.helpers import container, dingtalk_payload, dingtalk_sign


class DingTalkIngressTests(unittest.TestCase):
    def test_valid_webhook_creates_job_and_acknowledges(self) -> None:
        c = container()
        timestamp = "1710000000000"
        result = c.dingtalk_message_service.handle_webhook(
            payload=dingtalk_payload(),
            timestamp=timestamp,
            sign=dingtalk_sign("test-secret", timestamp),
            correlation_id="corr-1",
        )

        self.assertTrue(result["accepted"])
        self.assertEqual("received", result["status"])
        self.assertEqual(1, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(1, len(c.message_bus.jobs))

    def test_invalid_signature_does_not_persist(self) -> None:
        c = container()
        result = c.dingtalk_message_service.handle_webhook(
            payload=dingtalk_payload(),
            timestamp="1710000000000",
            sign="bad",
            correlation_id="corr-1",
        )

        self.assertFalse(result["accepted"])
        self.assertEqual("invalid_signature", result["status"])
        self.assertEqual(0, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(0, len(c.message_bus.jobs))

    def test_unauthorized_user_is_rejected(self) -> None:
        c = container()
        timestamp = "1710000000000"
        result = c.dingtalk_message_service.handle_webhook(
            payload=dingtalk_payload(user_id="blocked-user"),
            timestamp=timestamp,
            sign=dingtalk_sign("test-secret", timestamp),
            correlation_id="corr-1",
        )

        self.assertFalse(result["accepted"])
        self.assertEqual("permission_denied", result["status"])
        self.assertEqual(0, c.agent_repository.count_rows("agent_job"))


if __name__ == "__main__":
    unittest.main()
