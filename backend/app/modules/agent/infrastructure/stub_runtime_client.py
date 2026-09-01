from __future__ import annotations

from datetime import UTC, datetime

from app.modules.agent.domain.runtime import AgentRunRequest, AgentRunResult
from app.shared.tool_contract import canonical_json_sha256


class StubAgentRuntimeClient:
    def run(self, request: AgentRunRequest) -> AgentRunResult:
        timestamp = datetime.now(UTC).isoformat()
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
        audit = {
            "started_at": timestamp,
            "finished_at": timestamp,
            "status": "SUCCEEDED",
            "context_manifest": {
                "sources": [
                    {
                        "source_type": "user_prompt",
                        "name": "user_question",
                        "content": request.context.user_question,
                    },
                    {
                        "source_type": "retrieved_context",
                        "name": "retrieved_context",
                        "content": request.context.retrieved_context,
                    },
                ],
                "runtime_protocol_version": request.context.runtime_protocol_version,
            },
            "system_prompt": request.context.system_role,
            "user_prompt": request.context.user_question,
            "tool_definitions": [{"name": item} for item in request.context.effective_tool_names],
            "permission_snapshot": {"effective_tools": list(request.context.effective_tool_names)},
            "init_snapshot": {},
            "sdk_messages": [],
            "api_requests": [],
            "api_responses": [],
            "tool_executions": [],
            "model_requests": [],
            "usage": {},
            "summary": {
                "model_request_count": 0,
                "max_request_context_tokens": 0,
                "registered_tool_count": len(request.context.effective_tool_names),
                "max_loaded_tool_count": 0,
                "auto_approved_tool_count": 0,
                "tool_call_count": 0,
                "distinct_tool_count": 0,
            },
            "raw_api_capture_status": "not_applicable",
            "provider_thinking_disclosure": "Stub Runtime 未产生真实模型响应。",
            "error": {},
        }
        audit["runtime_identity"] = {
            "protocol_version": request.context.runtime_protocol_version,
            "invocation_id": request.invocation_id or f"{request.job_id}.attempt-0",
            "request_digest": canonical_json_sha256(audit),
        }
        return AgentRunResult(final_answer=final_answer, run_audit=audit)

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]:
        return {
            "status": "cancelled",
            "job_id": request.job_id,
            "reason": reason,
        }
