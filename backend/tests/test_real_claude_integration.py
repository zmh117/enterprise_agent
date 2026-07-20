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
    _run_real_smoke(
        model=os.getenv("CLAUDE_MODEL", ""),
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
        idempotency_key="real-claude-integration",
    )


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_BASELINE_INTEGRATION") != "true"
    or not os.getenv("BASELINE_ANTHROPIC_API_KEY")
    or not os.getenv("BASELINE_CLAUDE_MODEL")
    or not is_claude_cli_available(),
    reason="Baseline comparison requires explicit opt-in, model, key, and Claude CLI",
)
def test_real_claude_sdk_baseline_compatibility_smoke() -> None:
    _run_real_smoke(
        model=os.environ["BASELINE_CLAUDE_MODEL"],
        api_key=os.environ["BASELINE_ANTHROPIC_API_KEY"],
        base_url=os.getenv("BASELINE_ANTHROPIC_BASE_URL", ""),
        idempotency_key="real-claude-baseline-integration",
    )


def _run_real_smoke(
    *, model: str, api_key: str, base_url: str, idempotency_key: str
) -> None:
    from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=idempotency_key,
            dingding_conversation_id="integration-conversation",
            dingding_user_id="local-user",
            user_message="请用一句话确认真实 Claude Agent SDK 运行时可用，不要调用工具。",
            project_code="default",
        )
    )
    client = RealClaudeCodeAgentClient(
        model=model or c.settings.claude_model,
        tool_registry=c.agent_executor.tool_registry,
        limits=replace(c.settings.execution, timeout_seconds=60, max_turns=2),
        api_key=api_key,
        base_url=base_url,
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
