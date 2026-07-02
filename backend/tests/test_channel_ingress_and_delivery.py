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
from backend.tests.helpers import container, test_settings as make_settings


class FailingAdapter:
    def send(
        self,
        *,
        connector: Connector | None,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        raise NonRetryableExecutionError("boom", safe_message="delivery failed safely")


class ChannelIngressAndDeliveryTests(unittest.TestCase):
    def test_generic_channel_creates_job_with_none_delivery_and_minimal_queue_payload(self) -> None:
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

            self.assertEqual(200, response.status_code)
            job_id = response.json()["job_id"]
            detail = c.agent_repository.get_job_detail(job_id)
            self.assertEqual("debug_api", detail["source_channel"])
            self.assertEqual(
                {"type": "none", "connector_id": "", "target": {}, "options": {}},
                detail["reply_route"],
            )
            self.assertIsNotNone(c.message_bus)
            queue_message = c.message_bus.jobs[0]
            self.assertEqual(job_id, queue_message.job_id)
            self.assertTrue(queue_message.correlation_id)

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
                "/webhooks/grafana/alert",
                json=payload,
                headers={"x-grafana-token": "test-grafana-token"},
            )
            resolved = client.post(
                "/webhooks/grafana/alert",
                json={**payload, "status": "resolved"},
                headers={"x-grafana-token": "test-grafana-token"},
            )

            self.assertEqual(200, firing.status_code)
            self.assertEqual(200, resolved.status_code)
            self.assertTrue(resolved.json()["ignored"])
            self.assertEqual(1, c.agent_repository.count_rows("agent_job"))
            job = c.agent_repository.get_job(firing.json()["job_id"])
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
                "/webhooks/grafana/alert",
                json={
                    "status": "firing",
                    "groupKey": "bad-alert",
                    "commonLabels": {"ea_project_code": "default"},
                },
                headers={"x-grafana-token": "test-grafana-token"},
            )

            self.assertEqual(400, response.status_code)
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

        c.result_delivery_service.deliver_job_result(job.id)
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
        c.result_delivery_service.deliver_job_result(none_job.id)
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

        c.result_delivery_service.deliver_job_result(job.id)

        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)
        attempts = c.agent_repository.list_delivery_attempts(job.id)
        self.assertEqual("FAILED", attempts[0]["status"])
        self.assertEqual("delivery failed safely", attempts[0]["error_message"])

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
