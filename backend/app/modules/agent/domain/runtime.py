from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.shared.exceptions import ExecutionPolicyExceeded
from app.modules.model_connection.domain import ModelRuntimeBinding


@dataclass(frozen=True, slots=True)
class McpRuntimeBinding:
    server_code: str
    tool_name: str
    required_scope: str
    tool_schema_hash: str
    resource_code: str = ""
    resource_deployment_id: str = ""
    resource_revision_id: str = ""


@dataclass(frozen=True, slots=True)
class McpUnavailableNotice:
    tool_name: str
    reason_code: str
    message: str
    status: str = field(default="unavailable", init=False)

    def to_prompt_payload(self) -> dict[str, str]:
        return {
            "tool": self.tool_name,
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class AgentExecutionContext:
    system_role: str
    safety_rules: list[str]
    user_question: str
    project_code: str
    allowed_tools: list[str]
    tool_restrictions: list[str]
    skills: dict[str, str]
    retrieved_context: dict[str, Any]
    conversation_summary: str
    business_instructions: str = ""
    model: str = ""
    max_turns: int = 12
    timeout_seconds: int = 300
    max_tool_calls: int = 30
    publication_id: str = ""
    config_hash: str = ""
    model_runtime_binding: ModelRuntimeBinding | None = None
    application_publication_id: str = ""
    mcp_bindings: tuple[McpRuntimeBinding, ...] = ()
    mcp_unavailable_notices: tuple[McpUnavailableNotice, ...] = ()
    runtime_kind: str = "python-v1"
    runtime_protocol_version: str = "1.0"


@dataclass(frozen=True)
class AgentRunRequest:
    job_id: str
    user_id: str
    project_code: str
    context: AgentExecutionContext
    invocation_id: str = ""


@dataclass(frozen=True)
class AgentRunResult:
    final_answer: str
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    runtime_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallBudget:
    maximum: int
    attempted: int = 0

    def consume(self) -> None:
        self.attempted += 1
        if self.attempted > self.maximum:
            raise ExecutionPolicyExceeded(
                f"Agent tool call budget exhausted after {self.maximum} calls",
                safe_message=(
                    f"Agent 已达到本次执行允许的最大工具调用次数（{self.maximum}），"
                    "执行已安全停止。"
                ),
                error_code="execution_policy_max_tool_calls_exhausted",
            )
