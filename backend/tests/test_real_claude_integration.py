from __future__ import annotations

import os
from dataclasses import replace

import pytest

from app.modules.agent.domain.runtime import AgentExecutionContext, AgentRunRequest
from app.modules.agent.infrastructure.claude_code_agent_client import (
    RealClaudeCodeAgentClient,
    is_claude_cli_available,
)
from backend.tests.helpers import container


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_INTEGRATION") != "true"
    or not os.getenv("ANTHROPIC_API_KEY")
    or not is_claude_cli_available(),
    reason="Real Claude integration requires opt-in flag, ANTHROPIC_API_KEY, and Claude CLI",
)
def test_real_claude_sdk_smoke_completes_single_debug_job() -> None:
    from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="real-claude-integration",
            dingding_conversation_id="integration-conversation",
            dingding_user_id="local-user",
            user_message="请用一句话确认真实 Claude Agent SDK 运行时可用，不要调用工具。",
            project_code="default",
        )
    )
    client = RealClaudeCodeAgentClient(
        model=c.settings.claude_model,
        tool_registry=c.agent_executor.tool_registry,
        limits=replace(c.settings.execution, timeout_seconds=60, max_turns=2),
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
    )
    result = client.run(
        AgentRunRequest(
            job_id=job.id,
            user_id=job.user_id,
            project_code=job.project_code,
            context=AgentExecutionContext(
                system_role="Enterprise internal read-only diagnostic Agent",
                safety_rules=["Do not mutate anything.", "Answer briefly."],
                user_question=job.user_message,
                project_code=job.project_code,
                allowed_tools=[],
                tool_restrictions=["Do not call tools in this smoke test."],
                skills={},
                retrieved_context={},
                conversation_summary="Real SDK smoke test.",
            ),
        )
    )

    assert result.final_answer
    assert "read-only diagnostic analysis completed" not in result.final_answer
