from __future__ import annotations

from typing import Any
from app.modules.agent.domain.runtime import (
    AgentRunRequest,
    AgentExecutionContext,
    McpRuntimeBinding,
)


def agent_request_from_runtime_request(
    request: dict[str, Any],
    binding: Any,
) -> AgentRunRequest:
    tools = tuple(
        McpRuntimeBinding(
            server_code=str(server["server_code"]),
            tool_name=str(tool["tool_name"]),
            required_scope=str(tool["required_scope"]),
            tool_schema_hash=str(tool["tool_schema_hash"]),
            resource_code=str(tool.get("resource_code") or ""),
            resource_deployment_id=str(tool.get("resource_deployment_id") or ""),
            resource_revision_id=str(tool.get("resource_revision_id") or ""),
        )
        for server in request["mcp_servers"]
        for tool in server["tools"]
    )
    prompt = request["prompt"]
    limits = request["limits"]
    context = AgentExecutionContext(
        system_role=str(prompt["system_role"]),
        safety_rules=list(prompt["safety_rules"]),
        business_instructions=str(prompt["business_instructions"]),
        user_question=str(prompt["user_question"]),
        project_code=str(request["project_code"]),
        allowed_tools=[item.tool_name for item in tools],
        tool_restrictions=list(prompt["tool_restrictions"]),
        skills=dict(prompt.get("skills") or {}),
        retrieved_context=dict(prompt["retrieved_context"]),
        conversation_summary=str(prompt["conversation_summary"]),
        max_turns=int(limits["max_turns"]),
        timeout_seconds=int(limits["timeout_seconds"]),
        max_tool_calls=int(limits["max_tool_calls"]),
        publication_id=str(request["agent_publication_id"]),
        application_publication_id=str(request["application_publication_id"]),
        model_runtime_binding=binding,
        mcp_bindings=tools,
        runtime_kind="python-v1",
        runtime_protocol_version=str(request["protocol_version"]),
        job_tool_snapshot_hash=str(request["job_tool_snapshot_hash"]),
        control_plane_build_identity=dict(request["control_plane_build_identity"]),
        worker_build_identity=dict(request["worker_build_identity"]),
        prompt_template_version=str(prompt["template_version"]),
    )
    return AgentRunRequest(
        job_id=str(request["job_id"]),
        user_id=str(request["app_user_id"]),
        project_code=str(request["project_code"]),
        context=context,
        invocation_id=str(request["invocation_id"]),
    )
