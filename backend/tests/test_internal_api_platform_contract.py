from __future__ import annotations

import json
import unittest
from typing import Any

from app.modules.internal_tools.infrastructure.internal_api_client import (
    HttpInternalApiClient,
    ToolRequestContext,
)
from backend.tests.helpers import container


class FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class StructuredAddressingContractTests(unittest.TestCase):
    def test_http_client_sends_addressing_when_provided(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"summary": {"row_count": 0}})

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)
        client.query_database(
            "default",
            "select * from GL001_EBR_order",
            10,
            ToolRequestContext(job_id="j", user_id="u", project_code="p"),
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
        )

        self.assertEqual("sanjiu", captured["payload"]["environment"])
        self.assertEqual("guanlan", captured["payload"]["base"])
        self.assertEqual("GL001", captured["payload"]["workshop"])

    def test_http_client_omits_addressing_when_absent(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"summary": {}})

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)
        client.query_redis_get(
            "default", "order:1", ToolRequestContext(job_id="j", user_id="u", project_code="p")
        )

        self.assertNotIn("environment", captured["payload"])
        self.assertNotIn("base", captured["payload"])

    def test_tool_service_threads_addressing_to_client(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="addressing-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="check order",
                project_code="default",
            )
        )
        c.tool_service.call_tool(
            job_id=job.id,
            user_id="local-user",
            project_code="default",
            tool_name="query_database",
            arguments={
                "environment": "sanjiu",
                "base": "guanlan",
                "workshop": "GL001",
                "sql": "select * from GL001_EBR_order",
                "limit": 10,
            },
        )
        name, payload = c.internal_api_client.calls[-1]
        self.assertEqual("query_database", name)
        self.assertEqual("sanjiu", payload["environment"])
        self.assertEqual("guanlan", payload["base"])
        self.assertEqual("GL001", payload["workshop"])

    def test_agent_context_prefetches_schema_for_single_target(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="schema-context-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="观澜001，帮我查一下订单 MO20260627001 为什么一直待领料",
                project_code="default",
            )
        )

        context = c.agent_executor.context_builder.build(job)
        name, payload = c.internal_api_client.calls[-1]

        self.assertEqual("get_schema_directory", name)
        self.assertEqual("sanjiu", payload["environment"])
        self.assertEqual("guanlan", payload["base"])
        self.assertEqual("GL001", payload["workshop"])
        self.assertIn("schema_directory", context.retrieved_context)

    def test_agent_context_does_not_guess_when_target_is_ambiguous(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="schema-context-ambiguous-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="帮我查一下订单 MO20260627001 为什么一直待领料",
                project_code="default",
            )
        )

        context = c.agent_executor.context_builder.build(job)
        calls = [name for name, _ in c.internal_api_client.calls]

        self.assertNotIn("get_schema_directory", calls)
        self.assertEqual(
            "target_not_resolved",
            context.retrieved_context["schema_directory"]["status"],
        )

    def test_http_client_sends_schema_directory_request(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"summary": {"tables": []}})

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)
        client.get_schema_directory(
            ToolRequestContext(job_id="j", user_id="u", project_code="p"),
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            query="order",
            limit=20,
        )

        self.assertEqual("http://internal.test/tools/schema/directory", captured["url"])
        self.assertEqual("sanjiu", captured["payload"]["environment"])
        self.assertEqual("guanlan", captured["payload"]["base"])
        self.assertEqual("GL001", captured["payload"]["workshop"])
        self.assertEqual("order", captured["payload"]["query"])


if __name__ == "__main__":
    unittest.main()
