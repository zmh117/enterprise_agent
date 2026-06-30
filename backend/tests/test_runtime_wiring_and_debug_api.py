from __future__ import annotations

import unittest
from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import (
    build_api_container,
    build_test_container,
    build_worker_container,
)
from app.main import create_app
from app.modules.agent.infrastructure.claude_code_agent_client import (
    RealClaudeCodeAgentClient,
    StubClaudeCodeAgentClient,
)
from app.modules.internal_tools.infrastructure.internal_api_client import (
    FakeInternalApiClient,
    HttpInternalApiClient,
    ToolRequestContext,
    ToolResult,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.infrastructure.rabbitmq_consumer import RabbitMQConsumer
from app.modules.message_bus.infrastructure.rabbitmq_publisher import RabbitMQPublisher
from app.shared.config import Settings
from backend.tests.helpers import dingtalk_payload, dingtalk_sign, test_settings as make_settings


class ContextMetadataInternalApiClient(FakeInternalApiClient):
    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        summary = {"tables": ["ws_a_order"], "source": "mock-er"}
        return ToolResult(
            summary=summary,
            raw=summary,
            metadata={"request_id": context.correlation_id, "source": "mock-er"},
        )

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        summary = {"nodes": ["material_pick"], "source": "mock-flow"}
        return ToolResult(
            summary=summary,
            raw=summary,
            metadata={"request_id": context.correlation_id, "source": "mock-flow"},
        )


class RuntimeWiringAndDebugApiTests(unittest.TestCase):
    def test_compose_runtime_uses_rabbitmq_not_in_memory_bus(self) -> None:
        settings = make_settings()
        api_container = build_api_container(settings, migrate=True, seed=True)
        worker_container = build_worker_container(settings, migrate=True, seed=True)
        test_container = build_test_container(settings, migrate=True, seed=True)
        try:
            self.assertIsInstance(api_container.publisher, RabbitMQPublisher)
            self.assertIsNone(api_container.consumer)
            self.assertIsNone(api_container.message_bus)

            self.assertIsInstance(worker_container.publisher, RabbitMQPublisher)
            self.assertIsInstance(worker_container.consumer, RabbitMQConsumer)
            self.assertIsNone(worker_container.message_bus)

            self.assertIsNotNone(test_container.message_bus)
        finally:
            api_container.database.close()
            worker_container.database.close()
            test_container.database.close()

    def test_feature_flag_selects_real_claude_only_for_production_runtime(self) -> None:
        real_settings = replace(
            make_settings(),
            feature_real_claude=True,
            anthropic_api_key="test-key",
        )
        api_container = build_api_container(real_settings, migrate=True, seed=True)
        test_container = build_test_container(real_settings, migrate=True, seed=True)
        try:
            self.assertIsInstance(
                api_container.agent_executor.claude_client,
                RealClaudeCodeAgentClient,
            )
            self.assertIsInstance(
                test_container.agent_executor.claude_client,
                StubClaudeCodeAgentClient,
            )
        finally:
            api_container.database.close()
            test_container.database.close()

    def test_feature_flag_selects_real_internal_tools_only_for_production_runtime(self) -> None:
        real_settings = replace(
            make_settings(),
            feature_real_internal_tools=True,
            internal_api_base_url="http://internal.test",
            internal_api_auth_token="tool-token",
        )
        api_container = build_api_container(real_settings, migrate=True, seed=True)
        worker_container = build_worker_container(real_settings, migrate=True, seed=True)
        test_container = build_test_container(real_settings, migrate=True, seed=True)
        try:
            self.assertIsInstance(api_container.internal_api_client, HttpInternalApiClient)
            self.assertIsInstance(worker_container.internal_api_client, HttpInternalApiClient)
            self.assertIsInstance(test_container.internal_api_client, FakeInternalApiClient)
        finally:
            api_container.database.close()
            worker_container.database.close()
            test_container.database.close()

    def test_lifespan_builds_container_once_for_multiple_webhooks(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            timestamp = "1710000000000"
            for index in range(2):
                response = client.post(
                    "/webhooks/dingding/agent",
                    json=dingtalk_payload(msg_id=f"msg-{index}"),
                    headers={
                        "x-dingtalk-timestamp": timestamp,
                        "x-dingtalk-sign": dingtalk_sign("test-secret", timestamp),
                    },
                )
                self.assertEqual(200, response.status_code)

            container = built[0]
            self.assertEqual(1, len(built))
            self.assertEqual(2, container.agent_repository.count_rows("agent_job"))
            self.assertIsNotNone(container.message_bus)
            self.assertEqual(2, len(container.message_bus.jobs))

    def test_debug_api_creates_idempotent_job_and_exposes_execution_trace(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            container = built[0]
            payload = {
                "message": "帮我查一下订单 MO20260627001 为什么一直待领料",
                "user_id": "local-user",
                "conversation_id": "debug-conversation",
                "project_code": "default",
                "idempotency_key": "same-debug-job",
            }
            first = client.post("/api/agent/jobs", json=payload)
            second = client.post("/api/agent/jobs", json=payload)

            self.assertEqual(200, first.status_code)
            self.assertEqual(200, second.status_code)
            self.assertEqual(first.json()["job_id"], second.json()["job_id"])
            self.assertIsNotNone(container.message_bus)
            self.assertEqual(1, len(container.message_bus.jobs))

            job_id = str(first.json()["job_id"])
            pending = client.get(f"/api/agent/jobs/{job_id}")
            self.assertEqual(JobStatus.PENDING.value, pending.json()["status"])

            container.message_bus.consume_agent_jobs(
                lambda message: container.agent_executor.execute(
                    message.job_id,
                    fail_on_error=True,
                )
            )

            completed = client.get(f"/api/agent/jobs/{job_id}")
            self.assertEqual(JobStatus.SUCCEEDED.value, completed.json()["status"])
            self.assertIn("read-only diagnostic", completed.json()["result"])

            steps = client.get(f"/api/agent/jobs/{job_id}/steps")
            tool_calls = client.get(f"/api/agent/jobs/{job_id}/tool-calls")
            self.assertEqual(200, steps.status_code)
            self.assertEqual(200, tool_calls.status_code)
            self.assertGreaterEqual(len(steps.json()["steps"]), 3)
            self.assertEqual(2, len(tool_calls.json()["tool_calls"]))

    def test_debug_api_worker_persists_mock_internal_platform_tool_metadata(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            container.tool_service.internal_api_client = ContextMetadataInternalApiClient()
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            container = built[0]
            created = client.post(
                "/api/agent/jobs",
                json={
                    "message": "帮我查一下订单 MO20260627001 为什么一直待领料",
                    "user_id": "local-user",
                    "conversation_id": "debug-conversation",
                    "project_code": "default",
                    "idempotency_key": "mock-platform-debug-job",
                },
            )
            job_id = str(created.json()["job_id"])

            container.message_bus.consume_agent_jobs(
                lambda message: container.agent_executor.execute(
                    message.job_id,
                    fail_on_error=True,
                )
            )

            completed = client.get(f"/api/agent/jobs/{job_id}")
            tool_calls = client.get(f"/api/agent/jobs/{job_id}/tool-calls")

            self.assertEqual(JobStatus.SUCCEEDED.value, completed.json()["status"])
            payloads = [
                call["response_summary"]["payload"] for call in tool_calls.json()["tool_calls"]
            ]
            self.assertTrue(any("mock-er" in payload for payload in payloads))

    def test_debug_api_rejects_unauthorized_user_and_missing_job(self) -> None:
        settings = make_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            forbidden = client.post(
                "/api/agent/jobs",
                json={
                    "message": "check order",
                    "user_id": "blocked-user",
                    "conversation_id": "debug-conversation",
                    "project_code": "default",
                },
            )
            missing = client.get("/api/agent/jobs/job_missing")

            self.assertEqual(403, forbidden.status_code)
            self.assertEqual(404, missing.status_code)


if __name__ == "__main__":
    unittest.main()
