from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from typing import Any

from app.bootstrap import build_test_container
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector
from app.modules.dingding.application.dingtalk_stream_service import (
    DingTalkStreamHandleResult,
)
from app.modules.job.application.job_status_service import JobStatusService
from app.shared.config import DingTalkSettings, Settings
from app.shared.exceptions import NonRetryableExecutionError
from app.workers.dingtalk_stream_ingress_worker import DingTalkStreamIngressWorker
from backend.tests.helpers import container


class FakeStreamClient:
    def __init__(
        self,
        *,
        callback: Any,
        events: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.callback = callback
        self.events = events or []
        self.error = error
        self.started = 0
        self.results: list[DingTalkStreamHandleResult] = []

    def start_forever(self) -> None:
        self.started += 1
        if self.error is not None:
            raise self.error
        for event in self.events:
            self.results.append(self.callback(event))


class CaptureDeliveryAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send(
        self,
        *,
        connector: Connector | None,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        self.calls.append(
            {
                "connector_id": connector.id if connector else "",
                "route_type": route.type,
                "title": title,
                "text": text,
            }
        )


class DingTalkStreamIngressTests(unittest.TestCase):
    def test_stream_message_creates_job_and_acknowledges(self) -> None:
        c = container()

        result = c.dingtalk_stream_message_service.handle_callback(
            payload=stream_payload(),
            correlation_id="corr-stream-1",
        )

        self.assertTrue(result.accepted)
        self.assertEqual("received", result.status)
        self.assertEqual("OK", result.ack_status)
        self.assertEqual(1, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(1, len(c.message_bus.jobs))
        job = c.agent_repository.get_job(result.job_id)
        self.assertEqual("dingding_stream", job.source_channel)
        self.assertEqual("connector-dingtalk-stream-default", job.source_connector_id)
        self.assertEqual("stream-event-1", job.external_event_id)
        self.assertEqual("dingtalk_stream_session_webhook", job.reply_route["type"])
        self.assertEqual("", job.reply_route["connector_id"])
        self.assertEqual("https://oapi.dingtalk.com/robot/sendBySession", job.reply_route["target"]["session_webhook"])

    def test_duplicate_stream_event_returns_existing_job_without_second_queue_message(self) -> None:
        c = container()

        first = c.dingtalk_stream_message_service.handle_callback(
            payload=stream_payload(), correlation_id="corr-stream-1"
        )
        second = c.dingtalk_stream_message_service.handle_callback(
            payload=stream_payload(), correlation_id="corr-stream-2"
        )

        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(1, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(1, len(c.message_bus.jobs))

    def test_unsupported_stream_event_is_ignored_without_job(self) -> None:
        c = container()

        result = c.dingtalk_stream_message_service.handle_callback(
            payload={"eventType": "cardCallback", "eventId": "card-1"},
            correlation_id="corr-stream-1",
        )

        self.assertFalse(result.accepted)
        self.assertEqual("ignored", result.status)
        self.assertEqual("OK", result.ack_status)
        self.assertEqual(0, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(0, len(c.message_bus.jobs))

    def test_missing_stream_identity_is_rejected_without_job(self) -> None:
        c = container()

        result = c.dingtalk_stream_message_service.handle_callback(
            payload={"text": {"content": "diagnose"}, "msgId": "msg-1"},
            correlation_id="corr-stream-1",
        )

        self.assertFalse(result.accepted)
        self.assertEqual("rejected", result.status)
        self.assertEqual(0, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(0, len(c.message_bus.jobs))

    def test_unauthorized_stream_user_is_rejected_without_job(self) -> None:
        c = container()

        result = c.dingtalk_stream_message_service.handle_callback(
            payload=stream_payload(user_id="blocked-user"),
            correlation_id="corr-stream-1",
        )

        self.assertFalse(result.accepted)
        self.assertEqual("permission_denied", result.status)
        self.assertEqual(0, c.agent_repository.count_rows("agent_job"))

    def test_stream_job_result_uses_session_webhook_by_default(self) -> None:
        c = container()
        adapter = CaptureDeliveryAdapter()
        c.result_delivery_service.adapters["dingtalk_stream_session_webhook"] = adapter

        result = c.dingtalk_stream_message_service.handle_callback(
            payload=stream_payload(),
            correlation_id="corr-stream-1",
        )
        status_service = JobStatusService(c.agent_repository)
        self.assertIsNotNone(status_service.claim(result.job_id, "worker-1"))
        status_service.succeed(result.job_id, "diagnostic done")

        c.result_delivery_service.deliver_job_result(result.job_id)

        self.assertEqual(1, len(adapter.calls))
        self.assertEqual("dingtalk_stream_session_webhook", adapter.calls[0]["route_type"])
        self.assertEqual("", adapter.calls[0]["connector_id"])
        attempts = c.agent_repository.list_delivery_attempts(result.job_id)
        self.assertEqual("SUCCEEDED", attempts[0]["status"])

    def test_stream_message_can_override_delivery_to_enterprise_robot(self) -> None:
        c = container()

        result = c.dingtalk_stream_message_service.handle_callback(
            payload={
                **stream_payload(),
                "delivery": {
                    "type": "dingtalk_enterprise_robot",
                    "connector_id": "connector-dingtalk-enterprise-default",
                    "target": {"open_conversation_id": "open-cid-override"},
                },
            },
            correlation_id="corr-stream-1",
        )

        job = c.agent_repository.get_job(result.job_id)
        self.assertEqual("dingtalk_enterprise_robot", job.reply_route["type"])
        self.assertEqual("connector-dingtalk-enterprise-default", job.reply_route["connector_id"])
        self.assertEqual("open-cid-override", job.reply_route["target"]["open_conversation_id"])

    def test_stream_worker_starts_fake_client_and_creates_job(self) -> None:
        fake_holder: dict[str, FakeStreamClient] = {}
        with patched_env(DINGTALK_CLIENT_ID="client-id", DINGTALK_CLIENT_SECRET="client-secret"):
            settings = stream_settings()
            c = build_test_container(settings, migrate=True, seed=True)

            def factory(client_id: str, client_secret: str, callback: Any) -> FakeStreamClient:
                self.assertEqual("client-id", client_id)
                self.assertEqual("client-secret", client_secret)
                fake = FakeStreamClient(callback=callback, events=[stream_payload()])
                fake_holder["client"] = fake
                return fake

            worker = DingTalkStreamIngressWorker(
                settings,
                container=c,
                stream_client_factory=factory,
            )
            worker.run_once()

        self.assertEqual(1, fake_holder["client"].started)
        self.assertEqual(1, c.agent_repository.count_rows("agent_job"))

    def test_stream_worker_missing_credentials_fails_without_job(self) -> None:
        with patched_env(DINGTALK_CLIENT_ID="", DINGTALK_CLIENT_SECRET=""):
            settings = stream_settings()
            c = build_test_container(settings, migrate=True, seed=True)
            worker = DingTalkStreamIngressWorker(settings, container=c)

            with self.assertRaises(NonRetryableExecutionError):
                worker.run_once()

        self.assertEqual(0, c.agent_repository.count_rows("agent_job"))
        audit_rows = c.database.execute(
            "select event_type from audit_event where event_type = ?",
            ("dingtalk.stream.config_failed",),
        )
        self.assertEqual(1, len(audit_rows))

    def test_stream_worker_reconnects_after_transient_failure(self) -> None:
        calls = {"count": 0}
        with patched_env(DINGTALK_CLIENT_ID="client-id", DINGTALK_CLIENT_SECRET="client-secret"):
            settings = stream_settings()
            c = build_test_container(settings, migrate=True, seed=True)

            def factory(client_id: str, client_secret: str, callback: Any) -> FakeStreamClient:
                calls["count"] += 1
                if calls["count"] == 1:
                    return FakeStreamClient(callback=callback, error=RuntimeError("stream closed"))
                return FakeStreamClient(callback=callback, events=[stream_payload(msg_id="msg-2")])

            worker = DingTalkStreamIngressWorker(
                settings,
                container=c,
                stream_client_factory=factory,
                sleep=lambda _: None,
            )
            worker.run_forever(max_attempts=2)

        self.assertEqual(2, calls["count"])
        self.assertEqual(1, c.agent_repository.count_rows("agent_job"))


def stream_settings() -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        dingtalk=DingTalkSettings(
            stream_enabled=True,
            stream_reconnect_initial_seconds=1,
            stream_reconnect_max_seconds=1,
        ),
    )


def stream_payload(
    *,
    msg_id: str = "msg-1",
    event_id: str = "stream-event-1",
    user_id: str = "local-user",
    content: str = "帮我查一下订单 MO20260627001 为什么一直待领料",
) -> dict[str, Any]:
    return {
        "conversationId": "conversation-1",
        "openConversationId": "open-cid-1",
        "senderStaffId": user_id,
        "senderNick": "Local User",
        "msgId": msg_id,
        "eventId": event_id,
        "robotCode": "robot-code-1",
        "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession",
        "sessionWebhookExpiredTime": "1783003242125",
        "text": {"content": content},
    }


@contextmanager
def patched_env(**values: str):
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
