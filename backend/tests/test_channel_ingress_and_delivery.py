from __future__ import annotations

import unittest
from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import (
    container,
    dispatch_pending_deliveries,
    enqueue_job_result_for_delivery,
    test_settings as make_settings,
)


PUBLIC_ID = "wh_local_grafana_default_00000000000000000001"
BEARER = "test-grafana-token-0123456789abcdefABCDEF"


class FailingAdapter:
    def send(
        self,
        *,
        connector: Connector | None,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        raise NonRetryableExecutionError("boom", safe_message="投递安全失败")


class ChannelIngressAndDeliveryTests(unittest.TestCase):
    def test_unbound_generic_channel_route_is_removed(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Any):
            c = container()
            built.append(c)
            return c

        with TestClient(create_app(settings, container_factory=factory)) as client:
            c = built[0]
            response = client.post(
                "/webhooks/channel/agent",
                json={
                    "from": {
                        "type": "debug_api",
                        "connector_id": "connector-debug-api",
                        "event_id": "generic-1",
                        "actor_id": "local-user",
                    },
                    "delivery": {"type": "none"},
                    "routing": {"project_code": "default"},
                    "message": "check order",
                },
            )

            self.assertEqual(404, response.status_code)
            self.assertEqual(0, c.agent_repository.count_rows("agent_job"))

    def test_grafana_firing_creates_job_and_resolved_is_ignored(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Any):
            c = container()
            built.append(c)
            return c

        payload = {
            "status": "firing",
            "groupKey": "order-service-alert",
            "commonLabels": {
                "ea_project_code": "default",
                "ea_environment": "prod",
                "ea_base": "guanlan",
                "ea_workshop": "GL001",
                "ea_service": "order-service",
                "ea_delivery_type": "dingtalk_webhook_robot",
                "ea_delivery_connector_id": "connector-dingtalk-webhook-default",
            },
            "commonAnnotations": {"summary": "order service error rate high"},
        }

        with TestClient(create_app(settings, container_factory=factory)) as client:
            c = built[0]
            firing = client.post(
                f"/webhooks/v1/{PUBLIC_ID}",
                json=payload,
                headers={"authorization": f"Bearer {BEARER}"},
            )
            resolved = client.post(
                f"/webhooks/v1/{PUBLIC_ID}",
                json={**payload, "status": "resolved"},
                headers={"authorization": f"Bearer {BEARER}"},
            )

            self.assertEqual(202, firing.status_code)
            self.assertEqual(200, resolved.status_code)
            self.assertTrue(resolved.json()["ignored"])
            self.assertIsNotNone(c.message_bus)
            c.message_bus.consume_webhook_events(c.webhook_dispatcher.handle)
            self.assertEqual(1, c.agent_repository.count_rows("agent_job"))
            event = c.webhook_event_repository.get(firing.json()["event_id"])
            job = c.agent_repository.get_job(str(event["job_id"]))
            self.assertEqual("grafana_alert", job.source_channel)
            self.assertEqual("prod", (job.routing_context or {})["environment"])

    def test_grafana_missing_required_label_is_rejected_without_queue_message(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Any):
            c = container()
            built.append(c)
            return c

        with TestClient(create_app(settings, container_factory=factory)) as client:
            c = built[0]
            response = client.post(
                f"/webhooks/v1/{PUBLIC_ID}",
                json={
                    "status": "firing",
                    "groupKey": "bad-alert",
                    "commonLabels": {"ea_project_code": "default"},
                },
                headers={"authorization": f"Bearer {BEARER}"},
            )

            self.assertEqual(400, response.status_code)
            self.assertEqual(0, c.agent_repository.count_rows("agent_job"))
            self.assertIsNotNone(c.message_bus)
            self.assertEqual(0, len(c.message_bus.jobs))

    def test_old_grafana_header_translation_route_is_removed(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Any):
            c = container()
            built.append(c)
            return c

        with TestClient(create_app(settings, container_factory=factory)) as client:
            c = built[0]
            response = client.post(
                "/webhooks/grafana/alert",
                json={
                    "status": "firing",
                    "groupKey": "legacy-header",
                    "commonLabels": {"ea_project_code": "default"},
                },
                headers={"x-grafana-token": BEARER},
            )

            self.assertEqual(404, response.status_code)
            self.assertEqual(0, c.agent_repository.count_rows("agent_job"))
            self.assertIsNotNone(c.message_bus)
            self.assertEqual(0, len(c.message_bus.jobs))

    def test_delivery_chunks_long_report_and_none_delivery_is_skipped(self) -> None:
        c = container()
        c.result_delivery_service.chunker.max_chars = 10
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="chunked-delivery",
                requester_id="local-user",
                external_conversation_id="conversation-1",
                user_message="diagnose",
                project_code="default",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                reply_route={
                    "type": "dingtalk_conversation",
                    "connector_id": "connector-dingtalk-enterprise-default",
                    "target": {"conversation_id": "conversation-1"},
                },
            )
        )
        status_service = JobStatusService(c.agent_repository)
        self.assertIsNotNone(status_service.claim(job.id, "worker-1"))
        status_service.succeed(job.id, "abcdefghijklmnopqrstuvwxyz")

        enqueue_job_result_for_delivery(c, job.id)
        dispatch_pending_deliveries(c)
        chunks = c.agent_repository.list_delivery_chunks(job.id)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk["status"] == "SUCCEEDED" for chunk in chunks))

        none_job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="none-delivery",
                requester_id="local-user",
                external_conversation_id="debug",
                user_message="diagnose",
                project_code="default",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                reply_route={"type": "none"},
            )
        )
        self.assertIsNotNone(status_service.claim(none_job.id, "worker-1"))
        status_service.succeed(none_job.id, "done")
        enqueue_job_result_for_delivery(c, none_job.id)
        dispatch_pending_deliveries(c)
        attempts = c.agent_repository.list_delivery_attempts(none_job.id)
        self.assertEqual("SKIPPED", attempts[0]["status"])

    def test_delivery_failure_does_not_fail_succeeded_agent_job(self) -> None:
        c = container()
        c.result_delivery_service.adapters["dingtalk_conversation"] = FailingAdapter()
        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="failed-delivery",
                requester_id="local-user",
                external_conversation_id="conversation-1",
                user_message="diagnose",
                project_code="default",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                reply_route={
                    "type": "dingtalk_conversation",
                    "connector_id": "connector-dingtalk-enterprise-default",
                    "target": {"conversation_id": "conversation-1"},
                },
            )
        )
        status_service = JobStatusService(c.agent_repository)
        self.assertIsNotNone(status_service.claim(job.id, "worker-1"))
        status_service.succeed(job.id, "done")

        enqueue_job_result_for_delivery(c, job.id)
        c.delivery_dispatcher.dispatch_pending(limit=1)

        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)
        attempts = c.agent_repository.list_delivery_attempts(job.id)
        self.assertEqual("FAILED", attempts[0]["status"])
        self.assertEqual("投递安全失败", attempts[0]["error_message"])

    def test_delivery_connector_direction_is_enforced_before_job_creation(self) -> None:
        c = container()
        with self.assertRaises(NonRetryableExecutionError):
            c.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key="bad-delivery-connector",
                    requester_id="local-user",
                    external_conversation_id="debug",
                    user_message="diagnose",
                    project_code="default",
                    source_channel="debug_api",
                    source_connector_id="connector-debug-api",
                    reply_route={
                        "type": "grafana_alert",
                        "connector_id": "connector-grafana-default",
                    },
                )
            )


if __name__ == "__main__":
    unittest.main()
