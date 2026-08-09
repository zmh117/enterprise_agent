from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
)
from app.modules.agent.infrastructure.claude_code_agent_client import (
    ClaudeSdk,
    RealClaudeCodeAgentClient,
)
from app.shared.config import ExecutionSettings
from app.shared.exceptions import (
    DiagnosticLoopExhausted,
    RetryableExecutionError,
)
from services.mcp_common import McpTokenIssuer


SIGNING_KEY = b"runtime-characterization-signing-key"


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


def _context() -> AgentExecutionContext:
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
        timeout_seconds=5,
        application_publication_id="application-publication-1",
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="ones-mcp",
                tool_name="ones_work_item_search",
                required_scope="ones.work_items.search",
                tool_schema_hash="a" * 64,
            ),
        ),
    )


def _request(context: AgentExecutionContext | None = None) -> AgentRunRequest:
    return AgentRunRequest(
        job_id="job-1",
        user_id="app-user-1",
        project_code="project-1",
        context=context or _context(),
    )


def _client(query: Any) -> RealClaudeCodeAgentClient:
    return RealClaudeCodeAgentClient(
        model="claude-test",
        limits=ExecutionSettings(timeout_seconds=5),
        api_key="sk-test-valid-shaped-value",
        sdk_loader=lambda: _sdk(query),
        mcp_token_issuer=McpTokenIssuer(SIGNING_KEY),
        ones_mcp_url="https://ones-mcp.internal/mcp",
        data_mcp_url="https://data-mcp.internal/mcp",
    )


def test_golden_success_prefers_terminal_result_and_preserves_tool_events() -> None:
    async def query(*, prompt: str, options: FakeOptions):
        del prompt, options
        yield {
            "content": [
                {
                    "type": "tool_use",
                    "name": "ones_work_item_search",
                    "input": {"project": "project-1"},
                }
            ]
        }
        yield {
            "content": [
                {
                    "type": "tool_result",
                    "tool_name": "ones_work_item_search",
                    "content": {"count": 1},
                }
            ]
        }
        yield {"content": [{"type": "text", "text": "draft"}], "result": "final"}

    result = _client(query).run(_request())

    assert result.final_answer == "final"
    assert [(item["status"], item["tool_name"]) for item in result.tool_events] == [
        ("STARTED", "ones_work_item_search"),
        ("SUCCEEDED", "ones_work_item_search"),
    ]


def test_golden_timeout_is_retryable() -> None:
    async def query(*, prompt: str, options: FakeOptions):
        del prompt, options
        await asyncio.sleep(0.01)
        yield {"result": "must not complete"}

    with pytest.raises(RetryableExecutionError) as raised:
        _client(query).run(_request(replace(_context(), timeout_seconds=0)))

    assert raised.value.error_code == "runtime_timeout"


@pytest.mark.parametrize(
    ("message", "exception_type", "error_code"),
    [
        (
            "maximum number of turns reached",
            DiagnosticLoopExhausted,
            "max_turns_exhausted",
        ),
        ("503 temporarily overloaded", RetryableExecutionError, "claude_transient_error"),
    ],
)
def test_golden_sdk_errors_keep_stable_classification(
    message: str,
    exception_type: type[Exception],
    error_code: str,
) -> None:
    async def query(*, prompt: str, options: FakeOptions):
        del prompt, options
        raise RuntimeError(message)
        yield  # pragma: no cover

    with pytest.raises(exception_type) as raised:
        _client(query).run(_request())

    assert getattr(raised.value, "error_code") == error_code


def test_golden_inconsistent_success_result_is_retryable() -> None:
    async def query(*, prompt: str, options: FakeOptions):
        del prompt, options
        yield {"is_error": True, "subtype": "success", "errors": [], "result": "success"}

    with pytest.raises(RetryableExecutionError) as raised:
        _client(query).run(_request())

    assert raised.value.error_code == "claude_inconsistent_result"


def test_golden_permission_guard_denies_every_unfrozen_tool() -> None:
    captured: dict[str, Any] = {}

    async def query(*, prompt: str, options: FakeOptions):
        del prompt
        captured["denied"] = await options.can_use_tool(
            "mcp__ones__ones_work_item_update",
            {"status": "DONE"},
            object(),
        )
        captured["allowed"] = await options.can_use_tool(
            "mcp__ones__ones_work_item_search",
            {},
            object(),
        )
        yield {"result": "final"}

    _client(query).run(_request())

    assert captured["denied"].behavior == "deny"
    assert captured["allowed"].behavior == "allow"
