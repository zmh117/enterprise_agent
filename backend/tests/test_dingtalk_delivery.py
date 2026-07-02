from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from typing import Any

from app.modules.delivery.infrastructure.adapters import (
    DingTalkEnterpriseAppDeliveryAdapter,
    DingTalkWebhookRobotDeliveryAdapter,
)
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import (
    DingTalkAccessTokenClient,
    DingTalkWebhookRobotClient,
)
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.domain.job_status import JobStatus
from backend.tests.helpers import container


class FakeDingTalkTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_seconds: int
    ) -> dict[str, Any]:
        self.calls.append(
            {"url": url, "payload": payload, "headers": headers, "timeout": timeout_seconds}
        )
        if url.endswith("/oauth2/accessToken"):
            return {"accessToken": "fake-access-token", "expireIn": 7200}
        return {"code": "0"}


class DingTalkDeliveryTests(unittest.TestCase):
    def test_access_token_client_caches_token_and_masks_credentials_from_calls(self) -> None:
        transport = FakeDingTalkTransport()
        current = {"now": 1000.0}
        client = DingTalkAccessTokenClient(
            client_id="client-id",
            client_secret="client-secret",
            transport=transport,
            clock=lambda: current["now"],
        )

        first = client.access_token()
        second = client.access_token()

        self.assertEqual("fake-access-token", first)
        self.assertEqual(first, second)
        self.assertEqual(1, len(transport.calls))
        self.assertEqual(
            {"appKey": "client-id", "appSecret": "client-secret"},
            transport.calls[0]["payload"],
        )

    def test_enterprise_app_delivery_uses_env_credentials_and_default_target(self) -> None:
        transport = FakeDingTalkTransport()
        with patched_env(
            DINGTALK_CLIENT_ID="client-id",
            DINGTALK_CLIENT_SECRET="client-secret",
        ):
            c = container()
            c.result_delivery_service.adapters["dingtalk_enterprise_robot"] = (
                DingTalkEnterpriseAppDeliveryAdapter(
                    connector_registry=c.connector_registry,
                    transport=transport,
                )
            )
            job = c.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key="enterprise-delivery",
                    requester_id="local-user",
                    external_conversation_id="conversation-1",
                    user_message="diagnose",
                    project_code="default",
                    source_channel="debug_api",
                    source_connector_id="connector-debug-api",
                    reply_route={
                        "type": "dingtalk_enterprise_robot",
                        "connector_id": "connector-dingtalk-enterprise-default",
                    },
                )
            )
            status_service = JobStatusService(c.agent_repository)
            self.assertIsNotNone(status_service.claim(job.id, "worker-1"))
            status_service.succeed(job.id, "done")

            c.result_delivery_service.deliver_job_result(job.id)

        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)
        attempts = c.agent_repository.list_delivery_attempts(job.id)
        self.assertEqual("SUCCEEDED", attempts[0]["status"])
        self.assertEqual(2, len(transport.calls))
        self.assertEqual(
            "fake-access-token",
            transport.calls[1]["headers"]["x-acs-dingtalk-access-token"],
        )
        self.assertNotIn("client-secret", str(attempts[0]["target_summary"]))

    def test_webhook_robot_delivery_signs_url_and_masks_sensitive_target(self) -> None:
        transport = FakeDingTalkTransport()
        with patched_env(
            DINGTALK_WEBHOOK_ROBOT_URL=(
                "https://oapi.dingtalk.com/robot/send?access_token=robot-token"
            ),
            DINGTALK_WEBHOOK_ROBOT_SECRET="robot-secret",
        ):
            c = container()
            c.result_delivery_service.adapters["dingtalk_webhook_robot"] = (
                DingTalkWebhookRobotDeliveryAdapter(
                    connector_registry=c.connector_registry,
                    transport=transport,
                )
            )
            job = c.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key="webhook-delivery",
                    requester_id="local-user",
                    external_conversation_id="conversation-1",
                    user_message="diagnose",
                    project_code="default",
                    source_channel="debug_api",
                    source_connector_id="connector-debug-api",
                    reply_route={
                        "type": "dingtalk_webhook_robot",
                        "connector_id": "connector-dingtalk-webhook-default",
                        "target": {
                            "webhook_url": "https://oapi.dingtalk.com/robot/send?x=secret",
                            "at_mobiles": ["13800138000"],
                            "is_at_all": False,
                        },
                    },
                )
            )
            status_service = JobStatusService(c.agent_repository)
            self.assertIsNotNone(status_service.claim(job.id, "worker-1"))
            status_service.succeed(job.id, "done")

            c.result_delivery_service.deliver_job_result(job.id)

        self.assertEqual(1, len(transport.calls))
        self.assertIn("timestamp=", transport.calls[0]["url"])
        self.assertIn("sign=", transport.calls[0]["url"])
        self.assertEqual("markdown", transport.calls[0]["payload"]["msgtype"])
        attempts = c.agent_repository.list_delivery_attempts(job.id)
        self.assertEqual("SUCCEEDED", attempts[0]["status"])
        summary = str(attempts[0]["target_summary"])
        self.assertNotIn("robot-token", summary)
        self.assertNotIn("13800138000", summary)
        self.assertIn("at_mobiles_count", summary)

    def test_webhook_robot_host_denied_does_not_call_transport(self) -> None:
        transport = FakeDingTalkTransport()
        with patched_env(DINGTALK_WEBHOOK_ROBOT_URL="https://evil.example/robot/send"):
            c = container()
            c.result_delivery_service.adapters["dingtalk_webhook_robot"] = (
                DingTalkWebhookRobotDeliveryAdapter(
                    connector_registry=c.connector_registry,
                    transport=transport,
                )
            )
            job = c.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key="webhook-host-denied",
                    requester_id="local-user",
                    external_conversation_id="conversation-1",
                    user_message="diagnose",
                    project_code="default",
                    source_channel="debug_api",
                    source_connector_id="connector-debug-api",
                    reply_route={
                        "type": "dingtalk_webhook_robot",
                        "connector_id": "connector-dingtalk-webhook-default",
                    },
                )
            )
            status_service = JobStatusService(c.agent_repository)
            self.assertIsNotNone(status_service.claim(job.id, "worker-1"))
            status_service.succeed(job.id, "done")

            c.result_delivery_service.deliver_job_result(job.id)

        self.assertEqual([], transport.calls)
        attempts = c.agent_repository.list_delivery_attempts(job.id)
        self.assertEqual("FAILED", attempts[0]["status"])
        self.assertEqual("Delivery host is not allowed", attempts[0]["error_message"])

    def test_webhook_robot_client_generates_dingtalk_signature(self) -> None:
        client = DingTalkWebhookRobotClient(
            webhook_url="https://oapi.dingtalk.com/robot/send?access_token=token",
            secret="robot-secret",
            transport=FakeDingTalkTransport(),
            clock=lambda: 1.0,
        )

        signed_url = client.signed_webhook_url()

        self.assertIn("timestamp=1000", signed_url)
        self.assertIn("sign=", signed_url)
        self.assertIn("access_token=token", signed_url)


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
