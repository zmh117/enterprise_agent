from __future__ import annotations

import unittest

from app.shared.exceptions import ToolPolicyError
from backend.tests.helpers import container


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
