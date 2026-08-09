from __future__ import annotations

from typing import Any

import jwt
import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
    McpUnavailableNotice,
)
from app.modules.agent.infrastructure.claude_code_agent_client import (
    ClaudeSdk,
    RealClaudeCodeAgentClient,
)
from app.shared.config import ExecutionSettings
from app.shared.exceptions import NonRetryableExecutionError
from services.mcp_common import McpTokenIssuer


KEY = b"worker-mcp-signing-key-at-least-32-bytes"


class FakeOptions:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def _sdk(query: Any) -> ClaudeSdk:
    return ClaudeSdk(
        query=query,
        options=FakeOptions,
        permission_allow=PermissionResultAllow,
        permission_deny=PermissionResultDeny,
    )


def _context(*bindings: McpRuntimeBinding) -> AgentExecutionContext:
    return AgentExecutionContext(
        system_role="readonly project agent",
        safety_rules=["readonly"],
        user_question="find failed work items",
        project_code="project-1",
        allowed_tools=[],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="none",
        timeout_seconds=120,
        application_publication_id="application-publication-1",
        mcp_bindings=tuple(bindings),
        mcp_unavailable_notices=(
            McpUnavailableNotice(
                tool_name="data_schema_directory",
                reason_code="mcp_resource_unavailable",
                message="数据诊断工具暂不可用，请联系管理员检查资源发布状态。",
            ),
        ),
    )


def _request(context: AgentExecutionContext) -> AgentRunRequest:
    return AgentRunRequest(
        job_id="job-1",
        user_id="app-user-1",
        project_code="project-1",
        context=context,
    )


def _client(query: Any, *, allowed: tuple[str, ...] = ("ones-mcp", "data-mcp")):
    return RealClaudeCodeAgentClient(
        model="claude-test",
        limits=ExecutionSettings(timeout_seconds=5),
        api_key="sk-test-valid-shaped-value",
        sdk_loader=lambda: _sdk(query),
        mcp_token_issuer=McpTokenIssuer(KEY),
        ones_mcp_url="https://ones-mcp.internal/mcp",
        data_mcp_url="https://data-mcp.internal/mcp",
        allowed_mcp_server_codes=allowed,
    )


def test_worker_connects_only_job_bound_remote_mcp_tools() -> None:
    captured: dict[str, Any] = {}

    async def query(*, prompt: str, options: FakeOptions):
        captured["prompt"] = prompt
        captured["options"] = options
        yield {"result": "done"}

    binding = McpRuntimeBinding(
        server_code="ones-mcp",
        tool_name="ones_work_item_search",
        required_scope="ones.work_items.search",
        tool_schema_hash="a" * 64,
    )
    result = _client(query).run(_request(_context(binding)))
    options = captured["options"]

    assert result.final_answer == "done"
    assert options.allowed_tools == ["mcp__ones__ones_work_item_search"]
    assert set(options.mcp_servers) == {"ones"}
    assert options.mcp_servers["ones"]["type"] == "http"
    assert options.mcp_servers["ones"]["url"] == "https://ones-mcp.internal/mcp"
    authorization = options.mcp_servers["ones"]["headers"]["Authorization"]
    payload = jwt.decode(
        authorization.removeprefix("Bearer "),
        KEY,
        algorithms=["HS256"],
        audience="ones-mcp",
    )
    assert payload["sub"] == "app-user-1"
    assert payload["job_id"] == "job-1"
    assert payload["scopes"] == ["ones.work_items.search"]
    assert "data_schema_directory" not in options.allowed_tools
    assert "Bearer " not in options.system_prompt
    assert "mcp_resource_unavailable" in options.system_prompt
    assert {"Bash", "Write", "Edit", "WebFetch", "WebSearch", "Shell"} <= set(
        options.disallowed_tools
    )


def test_runtime_permission_guard_denies_model_forged_tool() -> None:
    captured: dict[str, Any] = {}

    async def query(*, prompt: str, options: FakeOptions):
        del prompt
        captured["denied"] = await options.can_use_tool(
            "mcp__data__data_schema_directory",
            {"user_id": "forged"},
            object(),
        )
        captured["allowed"] = await options.can_use_tool(
            "mcp__ones__ones_work_item_search",
            {},
            object(),
        )
        yield {"result": "done"}

    binding = McpRuntimeBinding(
        server_code="ones-mcp",
        tool_name="ones_work_item_search",
        required_scope="ones.work_items.search",
        tool_schema_hash="b" * 64,
    )
    _client(query).run(_request(_context(binding)))
    assert captured["denied"].behavior == "deny"
    assert captured["allowed"].behavior == "allow"


def test_worker_fails_closed_for_server_outside_deployment_allowlist() -> None:
    async def query(*, prompt: str, options: FakeOptions):
        del prompt, options
        yield {"result": "must not run"}

    binding = McpRuntimeBinding(
        server_code="data-mcp",
        tool_name="data_schema_directory",
        required_scope="data.schema.read",
        tool_schema_hash="c" * 64,
    )
    with pytest.raises(NonRetryableExecutionError) as raised:
        _client(query, allowed=("ones-mcp",)).run(_request(_context(binding)))
    assert raised.value.error_code == "mcp_server_not_allowed"
