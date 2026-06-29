from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True)
class AgentRunRequest:
    job_id: str
    user_id: str
    project_code: str
    context: AgentExecutionContext


@dataclass(frozen=True)
class AgentRunResult:
    final_answer: str
    tool_events: list[dict[str, Any]] = field(default_factory=list)
