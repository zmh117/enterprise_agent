from __future__ import annotations

from typing import Protocol

from app.modules.agent.domain.runtime import AgentRunRequest, AgentRunResult
from app.shared.exceptions import RetryableExecutionError


class ClaudeCodeAgentClient(Protocol):
    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


class StubClaudeCodeAgentClient:
    def run(self, request: AgentRunRequest) -> AgentRunResult:
        context = request.context.retrieved_context
        evidence = []
        if "er" in context:
            evidence.append(f"ER context: {context['er']}")
        if "business_flow" in context:
            evidence.append(f"Business flow context: {context['business_flow']}")
        final_answer = "\n".join(
            [
                "Conclusion: read-only diagnostic analysis completed.",
                f"Question: {request.context.user_question}",
                "Evidence:",
                *(f"- {item}" for item in evidence),
                "Uncertainty: runtime used configured read-only tool summaries only.",
                "Suggested next actions: review the cited evidence and perform any mutation manually through approved procedures.",
            ]
        )
        return AgentRunResult(final_answer=final_answer)


class RealClaudeCodeAgentClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        try:
            import anthropic  # noqa: F401
        except ModuleNotFoundError as exc:
            raise RetryableExecutionError(
                "Claude Code Agent SDK dependency is not installed",
                safe_message="Claude runtime dependency is not available",
            ) from exc
        raise RetryableExecutionError(
            "Real Claude Code Agent SDK integration is not configured",
            safe_message="Claude runtime is not configured",
        )
