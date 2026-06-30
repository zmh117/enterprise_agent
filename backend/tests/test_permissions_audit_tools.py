from __future__ import annotations

import unittest

from app.modules.internal_tools.infrastructure.internal_api_client import (
    ToolRequestContext,
    ToolResult,
)
from app.shared.exceptions import RetryableExecutionError
from app.shared.exceptions import ToolPolicyError
from backend.tests.helpers import container


class MetadataInternalApiClient:
    def query_database(
        self, datasource: str, sql: str, limit: int, context: ToolRequestContext
    ) -> ToolResult:
        return ToolResult(
            summary={"row_count": 1},
            raw={"rows": [{"secret": "hidden"}]},
            metadata={"request_id": context.correlation_id, "source": "mock-db"},
            truncated=True,
        )

    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def query_loki(
        self, service: str, query: str, minutes: int, limit: int, context: ToolRequestContext
    ) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def query_redis_get(self, datasource: str, key: str, context: ToolRequestContext) -> ToolResult:
        return ToolResult(summary={}, raw={})

    def query_redis_scan(
        self, datasource: str, pattern: str, limit: int, context: ToolRequestContext
    ) -> ToolResult:
        return ToolResult(summary={}, raw={})


class FailingInternalApiClient(MetadataInternalApiClient):
    def query_database(
        self, datasource: str, sql: str, limit: int, context: ToolRequestContext
    ) -> ToolResult:
        raise RetryableExecutionError(
            "timeout",
            safe_message="Internal API Platform request failed",
        )


class PermissionAuditToolTests(unittest.TestCase):
    def test_allowed_tool_records_audit_and_uses_internal_api_client(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="tool-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="check order",
                project_code="default",
            )
        )

        result = c.tool_service.call_tool(
            job_id=job.id,
            user_id="local-user",
            project_code="default",
            tool_name="query_database",
            arguments={"datasource": "default", "sql": "select * from ws_a_order", "limit": 10},
        )

        self.assertEqual(1, result.summary["row_count"])
        self.assertEqual("query_database", c.internal_api_client.calls[-1][0])
        self.assertEqual(1, c.agent_repository.count_rows("agent_tool_call"))

    def test_database_mutation_is_rejected_and_recorded(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="bad-tool-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="check order",
                project_code="default",
            )
        )

        with self.assertRaises(ToolPolicyError):
            c.tool_service.call_tool(
                job_id=job.id,
                user_id="local-user",
                project_code="default",
                tool_name="query_database",
                arguments={"datasource": "default", "sql": "delete from ws_a_order", "limit": 10},
            )
        self.assertEqual(1, c.agent_repository.count_rows("agent_tool_call"))
        self.assertEqual(0, len(c.internal_api_client.calls))

    def test_tool_call_persists_platform_metadata_summary(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="metadata-tool-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="check order",
                project_code="default",
            )
        )
        c.tool_service.internal_api_client = MetadataInternalApiClient()

        c.tool_service.call_tool(
            job_id=job.id,
            user_id="local-user",
            project_code="default",
            tool_name="query_database",
            arguments={"datasource": "default", "sql": "select * from ws_a_order", "limit": 10},
        )
        tool_call = c.agent_repository.list_tool_calls(job.id)[0]
        payload = tool_call["response_summary"]["payload"]

        self.assertIn("mock-db", payload)
        self.assertIn('"truncated": true', payload)
        self.assertNotIn("hidden", payload)

    def test_failed_internal_platform_call_is_recorded(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="failed-platform-tool-job",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="check order",
                project_code="default",
            )
        )
        c.tool_service.internal_api_client = FailingInternalApiClient()

        with self.assertRaises(RetryableExecutionError):
            c.tool_service.call_tool(
                job_id=job.id,
                user_id="local-user",
                project_code="default",
                tool_name="query_database",
                arguments={
                    "datasource": "default",
                    "sql": "select * from ws_a_order",
                    "limit": 10,
                },
            )

        tool_call = c.agent_repository.list_tool_calls(job.id)[0]
        self.assertEqual("FAILED", tool_call["status"])
        self.assertIsNotNone(tool_call["audit_id"])

    def test_redis_mutation_and_loki_bounds_are_rejected(self) -> None:
        from app.modules.internal_tools.application.policies import (
            assert_loki_bounds,
            assert_redis_readonly,
        )
        from app.shared.config import ExecutionSettings

        settings = ExecutionSettings(max_loki_minutes=60, max_loki_lines=100, redis_scan_limit=50)
        with self.assertRaises(ToolPolicyError):
            assert_redis_readonly("delete", limit=None, settings=settings)
        with self.assertRaises(ToolPolicyError):
            assert_loki_bounds(service="order-service", minutes=120, limit=10, settings=settings)


if __name__ == "__main__":
    unittest.main()
