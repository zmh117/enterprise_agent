from __future__ import annotations

from app.modules.agent.domain.runtime import AgentExecutionContext
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.job.domain.agent_job import AgentJob


class AgentContextBuilder:
    def __init__(self, *, tool_registry: ToolRegistry, skill_loader: SkillLoader) -> None:
        self.tool_registry = tool_registry
        self.skill_loader = skill_loader

    def build(self, job: AgentJob) -> AgentExecutionContext:
        er_context = self.tool_registry.call(
            job_id=job.id,
            user_id=job.user_id,
            project_code=job.project_code,
            tool_name="get_er_context",
            arguments={"query": job.user_message},
        )
        business_flow_context = self.tool_registry.call(
            job_id=job.id,
            user_id=job.user_id,
            project_code=job.project_code,
            tool_name="get_business_flow_context",
            arguments={"query": job.user_message},
        )
        return AgentExecutionContext(
            system_role="Enterprise internal read-only diagnostic Agent",
            safety_rules=[
                "Use only registered internal read-only tools.",
                "Do not modify code, databases, Redis, services, deployments, or files.",
                "Every conclusion must cite evidence or state uncertainty.",
            ],
            user_question=job.user_message,
            project_code=job.project_code,
            allowed_tools=self.tool_registry.available_tools(),
            tool_restrictions=[
                "SQL must be read-only and bounded.",
                "Redis operations must be get or bounded scan.",
                "Loki queries must be bounded by service, time range, and result size.",
            ],
            skills=self.skill_loader.load(),
            retrieved_context={
                "er": er_context.summary,
                "business_flow": business_flow_context.summary,
            },
            conversation_summary="Current MVP uses the active DingTalk question only.",
        )
