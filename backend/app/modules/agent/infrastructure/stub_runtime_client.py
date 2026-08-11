from __future__ import annotations

from app.modules.agent.domain.runtime import AgentRunRequest, AgentRunResult


class StubAgentRuntimeClient:
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

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]:
        return {
            "status": "cancelled",
            "job_id": request.job_id,
            "reason": reason,
        }
