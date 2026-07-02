from __future__ import annotations

import unittest
from typing import Any

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import DingTalkSettings, Settings
from backend.tests.helpers import container, dingtalk_payload, dingtalk_sign


class DingTalkIngressTests(unittest.TestCase):
    def test_http_webhook_route_is_disabled_by_default(self) -> None:
        settings = Settings(database_dsn="sqlite:///:memory:", dingtalk=DingTalkSettings())
        built = []

        def factory(factory_settings: Any):
            c = build_test_container(factory_settings, migrate=True, seed=True)
            built.append(c)
            return c

        with TestClient(create_app(settings, container_factory=factory)) as client:
            response = client.post(
                "/webhooks/dingding/agent",
                json=dingtalk_payload(),
                headers={
                    "x-dingtalk-timestamp": "1710000000000",
                    "x-dingtalk-sign": "bad",
                },
            )
            self.assertEqual(404, response.status_code)
            self.assertEqual(0, built[0].agent_repository.count_rows("agent_job"))

    def test_http_webhook_route_can_be_enabled_for_compatibility(self) -> None:
        timestamp = "1710000000000"
        settings = Settings(
            database_dsn="sqlite:///:memory:",
            dingtalk=DingTalkSettings(secret="test-secret", http_webhook_enabled=True),
        )
        built = []

        def factory(factory_settings: Any):
            c = build_test_container(factory_settings, migrate=True, seed=True)
            built.append(c)
            return c

        with TestClient(create_app(settings, container_factory=factory)) as client:
            response = client.post(
                "/webhooks/dingding/agent",
                json=dingtalk_payload(),
                headers={
                    "x-dingtalk-timestamp": timestamp,
                    "x-dingtalk-sign": dingtalk_sign("test-secret", timestamp),
                },
            )
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.json()["accepted"])
            self.assertEqual(1, built[0].agent_repository.count_rows("agent_job"))

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
        job = c.agent_repository.get_job(str(result["job_id"]))
        self.assertEqual("dingtalk_enterprise_robot", job.reply_route["type"])
        self.assertEqual("connector-dingtalk-enterprise-default", job.reply_route["connector_id"])

    def test_default_delivery_and_routing_can_be_configured(self) -> None:
        c = container()
        c.dingtalk_message_service.default_environment = "sanjiu"
        c.dingtalk_message_service.default_base = "guanlan"
        c.dingtalk_message_service.default_workshop = "GL001"
        c.dingtalk_message_service.default_service = "order-service"
        c.dingtalk_message_service.default_open_conversation_id = "open-cid"
        c.dingtalk_message_service.default_robot_code = "robot-code"
        timestamp = "1710000000000"
        result = c.dingtalk_message_service.handle_webhook(
            payload=dingtalk_payload(),
            timestamp=timestamp,
            sign=dingtalk_sign("test-secret", timestamp),
            correlation_id="corr-1",
        )

        job = c.agent_repository.get_job(str(result["job_id"]))
        self.assertEqual("sanjiu", job.routing_context["environment"])
        self.assertEqual("guanlan", job.routing_context["base"])
        self.assertEqual("GL001", job.routing_context["workshop"])
        self.assertEqual("order-service", job.routing_context["service"])
        self.assertEqual("open-cid", job.reply_route["target"]["open_conversation_id"])
        self.assertEqual("robot-code", job.reply_route["target"]["robot_code"])

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
