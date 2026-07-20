from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from typing import Any

from app.modules.agent.domain.runtime import AgentExecutionContext, AgentRunRequest
from app.modules.agent.infrastructure.claude_code_agent_client import (
    ClaudeSdk,
    RealClaudeCodeAgentClient,
)
from app.modules.internal_tools.infrastructure.internal_api_client import (
    ToolRequestContext,
    ToolResult,
)
from app.shared.config import ExecutionSettings
from app.shared.exceptions import (
    DiagnosticLoopExhausted,
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from backend.tests.helpers import container


class FakeOptions:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


def fake_tool(name: str, description: str, schema: dict[str, Any], **kwargs: Any) -> Any:
    def decorator(handler: Any) -> Any:
        handler.tool_name = name
        handler.description = description
        handler.schema = schema
        handler.annotations = kwargs.get("annotations")
        return handler

    return decorator


def fake_server(name: str, tools: list[Any]) -> dict[str, Any]:
    return {"name": name, "tools": {tool.tool_name: tool for tool in tools}}


class ProcessError(Exception):
    pass


class MockPlatformInternalApiClient:
    def query_database(
        self, datasource: str, sql: str, limit: int, context: ToolRequestContext
    ) -> ToolResult:
        return ToolResult(
            summary={"row_count": 1, "mock_platform": True, "job_id": context.job_id},
            raw={"rows": [{"order_no": "MO20260627001"}]},
        )

    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def get_schema_directory(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str,
        workshop: str | None = None,
        query: str = "",
        limit: int = 50,
    ) -> ToolResult:
        return ToolResult(summary={"tables": []}, raw={})

    def query_loki(
        self,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        context: ToolRequestContext,
    ) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def diagnose_loki_labels(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str,
        workshop: str | None = None,
        minutes: int = 15,
        limit: int = 100,
    ) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def diagnose_loki_label_values(
        self,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str,
        label: str,
        workshop: str | None = None,
        minutes: int = 15,
        limit: int = 100,
    ) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def diagnose_loki_probe(
        self,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
        context: ToolRequestContext,
        *,
        environment: str,
        base: str,
        workshop: str | None = None,
    ) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def query_redis_get(self, datasource: str, key: str, context: ToolRequestContext) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def query_redis_scan(
        self, datasource: str, pattern: str, limit: int, context: ToolRequestContext
    ) -> ToolResult:
        return ToolResult(summary={}, raw={})


class RealClaudeCodeAgentClientTests(unittest.TestCase):
    def test_single_turn_answer_and_runtime_permissions(self) -> None:
        captured: dict[str, Any] = {}

        async def query(prompt: str, options: FakeOptions) -> Any:
            captured["prompt"] = prompt
            captured["options"] = options
            yield {"content": [{"type": "text", "text": "intermediate"}]}
            yield {"result": "final diagnostic report"}

        client, request = self._client_and_request(query)
        result = client.run(request)
        options = captured["options"]

        self.assertEqual("final diagnostic report", result.final_answer)
        self.assertEqual(request.context.user_question, captured["prompt"])
        self.assertEqual(["mcp__internal__*"], options.allowed_tools)
        self.assertFalse(getattr(options, "disallowed_tools", []))
        self.assertEqual("dontAsk", options.permission_mode)
        self.assertIn("不具备诊断证据", options.system_prompt)
        self.assertIn("get_schema_directory", options.system_prompt)

    def test_tool_loop_routes_through_tool_registry_and_returns_tool_events(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            tool = options.mcp_servers["internal"]["tools"]["query_database"]
            await tool({"datasource": "default", "sql": "select * from ws_a_order", "limit": 5})
            yield {"result": "database evidence found"}

        client, request = self._client_and_request(query)
        result = client.run(request)

        self.assertEqual("database evidence found", result.final_answer)
        self.assertEqual(1, len(result.tool_events))
        self.assertEqual("query_database", result.tool_events[0]["tool_name"])
        self.assertEqual("SUCCEEDED", result.tool_events[0]["status"])

    def test_tool_loop_can_use_mock_internal_platform_client(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            tool = options.mcp_servers["internal"]["tools"]["query_database"]
            await tool({"datasource": "default", "sql": "select * from ws_a_order", "limit": 5})
            yield {"result": "database evidence found"}

        client, request = self._client_and_request(
            query,
            internal_api_client=MockPlatformInternalApiClient(),
        )
        result = client.run(request)

        self.assertEqual("database evidence found", result.final_answer)
        self.assertIn("mock_platform", result.tool_events[0]["response_summary"]["payload"])

    def test_policy_rejection_is_returned_to_model_as_tool_event(self) -> None:
        tool_response: dict[str, Any] = {}

        async def query(prompt: str, options: FakeOptions) -> Any:
            tool = options.mcp_servers["internal"]["tools"]["query_database"]
            tool_response.update(await tool({"sql": "delete from ws_a_order", "limit": 5}))
            yield {"result": "policy handled"}

        client, request = self._client_and_request(query)
        result = client.run(request)

        self.assertEqual("policy handled", result.final_answer)
        self.assertEqual("FAILED", result.tool_events[0]["status"])
        self.assertIn("tool_rejected", tool_response["content"][0]["text"])

    def test_missing_api_key_is_non_retryable(self) -> None:
        client, request = self._client_and_request(self._empty_query, api_key="")

        with self.assertRaises(NonRetryableExecutionError):
            client.run(request)

    def test_placeholder_api_key_is_non_retryable(self) -> None:
        client, request = self._client_and_request(
            self._empty_query,
            api_key="your-deepseek-api-key",
        )

        with self.assertRaises(NonRetryableExecutionError) as raised:
            client.run(request)

        self.assertIn("placeholder", raised.exception.safe_message)

    def test_timeout_is_retryable(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            await asyncio.sleep(0.01)
            yield {"result": "too late"}

        client, request = self._client_and_request(
            query, limits=ExecutionSettings(timeout_seconds=0)
        )

        with self.assertRaises(RetryableExecutionError):
            client.run(request)

    def test_process_error_is_retryable(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            raise ProcessError("transport disconnected")
            yield {"result": "unreachable"}

        client, request = self._client_and_request(query)

        with self.assertRaises(RetryableExecutionError):
            client.run(request)

    def test_inconsistent_error_result_has_stable_safe_classification(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            del prompt, options
            yield {"type": "result", "is_error": True, "result": "success", "errors": []}

        client, request = self._client_and_request(query)
        with self.assertRaises(RetryableExecutionError) as raised:
            client.run(request)

        self.assertEqual("claude_inconsistent_result", raised.exception.error_code)
        self.assertIn("不一致", raised.exception.safe_message)
        self.assertNotIn("error result: success", raised.exception.safe_message.lower())

    def test_process_error_success_is_inconsistent_and_diagnostics_are_redacted(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            del prompt
            options.stderr(
                "request https://user:pass@example.invalid/path?api_key=secret api_key=secret"
            )
            raise ProcessError("Claude Code returned an error result: success")
            yield {"result": "unreachable"}

        client, request = self._client_and_request(query)
        with self.assertRaises(RetryableExecutionError) as raised:
            client.run(request)

        self.assertEqual("claude_inconsistent_result", raised.exception.error_code)
        diagnostics = json.dumps(raised.exception.diagnostics)
        self.assertNotIn("secret", diagnostics)
        self.assertNotIn("user:pass", diagnostics)
        self.assertEqual("default", raised.exception.diagnostics["provider_host"])

    def test_explicit_invalid_model_is_non_retryable(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            del prompt, options
            raise ProcessError("model not found")
            yield {"result": "unreachable"}

        client, request = self._client_and_request(query)
        with self.assertRaises(NonRetryableExecutionError) as raised:
            client.run(request)
        self.assertEqual("claude_invalid_model", raised.exception.error_code)

    def test_process_error_after_tool_call_carries_tool_events(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            tool = options.mcp_servers["internal"]["tools"]["query_database"]
            await tool({"datasource": "default", "sql": "select * from ws_a_order", "limit": 5})
            raise ProcessError("transport disconnected")
            yield {"result": "unreachable"}

        client, request = self._client_and_request(query)

        with self.assertRaises(RetryableExecutionError) as raised:
            client.run(request)

        self.assertEqual("claude_transient_error", raised.exception.error_code)
        self.assertEqual(1, len(raised.exception.tool_events))
        self.assertEqual("query_database", raised.exception.tool_events[0]["tool_name"])

    def test_max_turns_exhausted_is_non_retryable_and_carries_tool_events(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            tool = options.mcp_servers["internal"]["tools"]["query_database"]
            await tool({"datasource": "default", "sql": "select * from ws_a_order", "limit": 5})
            raise ProcessError("Reached maximum number of turns (12)")
            yield {"result": "unreachable"}

        client, request = self._client_and_request(query)

        with self.assertRaises(DiagnosticLoopExhausted) as raised:
            client.run(request)

        self.assertEqual("max_turns_exhausted", raised.exception.error_code)
        self.assertEqual(1, len(raised.exception.tool_events))

    def test_cli_stderr_is_included_in_safe_runtime_error(self) -> None:
        async def query(prompt: str, options: FakeOptions) -> Any:
            options.stderr("HTTP 401 invalid api_key=secret-value")
            raise ProcessError("process exited")
            yield {"result": "unreachable"}

        client, request = self._client_and_request(query)

        with self.assertRaises(RetryableExecutionError) as raised:
            client.run(request)

        self.assertIn("HTTP 401", raised.exception.safe_message)
        self.assertIn("api_key=<redacted>", raised.exception.safe_message)
        self.assertNotIn("secret-value", raised.exception.safe_message)

    async def _empty_query(self, prompt: str, options: FakeOptions) -> Any:
        yield {"result": "unused"}

    def _client_and_request(
        self,
        query: Any,
        *,
        api_key: str = "sk-test-valid-shaped-value",
        limits: ExecutionSettings | None = None,
        internal_api_client: Any | None = None,
    ) -> tuple[RealClaudeCodeAgentClient, AgentRunRequest]:
        c = container()
        if internal_api_client is not None:
            c.tool_service.internal_api_client = internal_api_client
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="real-client-test",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="check order",
                project_code="default",
            )
        )
        runtime_limits = limits or replace(c.settings.execution, timeout_seconds=5)
        client = RealClaudeCodeAgentClient(
            model="claude-test",
            tool_registry=c.agent_executor.tool_registry,
            limits=runtime_limits,
            api_key=api_key,
            sdk_loader=lambda: ClaudeSdk(
                query=query,
                options=FakeOptions,
                tool=fake_tool,
                create_sdk_mcp_server=fake_server,
                tool_annotations=None,
            ),
        )
        request = AgentRunRequest(
            job_id=job.id,
            user_id=job.user_id,
            project_code=job.project_code,
            context=AgentExecutionContext(
                system_role="test agent",
                safety_rules=["readonly"],
                user_question=job.user_message,
                project_code=job.project_code,
                allowed_tools=["query_database"],
                tool_restrictions=[
                    "select only",
                    "Call get_schema_directory before query_database.",
                    "Stop and report 不具备诊断证据 when schema is insufficient.",
                ],
                skills={"test": "diagnose"},
                retrieved_context={"er": {"tables": ["ws_a_order"]}},
                conversation_summary="none",
            ),
        )
        return client, request


if __name__ == "__main__":
    unittest.main()
