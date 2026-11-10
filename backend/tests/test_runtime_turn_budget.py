import asyncio
from types import SimpleNamespace

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

from app.modules.agent.domain.runtime import ToolCallBudget
from app.python_runtime.mcp_config import _file_turn_budget_hooks
from app.python_runtime.sdk_event_normalizer import SdkEventNormalizer
from app.python_runtime.turn_budget import TurnBudget
from app.shared.exceptions import DiagnosticLoopExhausted, NonRetryableExecutionError


def message(identifier, *tools):
    return AssistantMessage(
        model="synthetic",
        message_id=identifier,
        content=[ToolUseBlock(id=call, name=name, input={}) for call, name in tools]
        or [TextBlock(text="synthetic")],
    )


def test_file_turns_are_free_but_model_audit_keeps_all_responses():
    budget = TurnBudget(1, 10, ("Read", "Glob", "Grep"))
    audit = SdkEventNormalizer()
    for item in [
        message("m1", ("t1", "Glob"), ("t2", "Glob")),
        message("m2", ("t3", "Grep")),
        message("m3", ("t4", "Read")),
        message("m4"),
        {"type": "result", "is_error": False},
    ]:
        audit.consume(item)
        budget.observe(item)
    assert budget.snapshot() == dict(
        policy="file-reads-exempt-v1",
        maximum=1,
        sdk_maximum=11,
        observed=4,
        charged=1,
        exempt=3,
        pending=0,
    )
    assert len([e for e in audit.events if e["event_type"] == "model_call"]) == 4


def test_split_and_replayed_blocks_do_not_double_charge_mixed_turn():
    budget = TurnBudget(2, 10, ("Read", "Glob", "Grep"))
    for item in [
        message("m1"),
        message("m1", ("t1", "Read")),
        message("m1", ("t2", "mcp__knowledge__search")),
        message("m1", ("t2", "mcp__knowledge__search")),
        message("m2"),
        {"type": "result", "is_error": False},
    ]:
        budget.observe(item)
    assert budget.snapshot()["observed"] == 2
    assert budget.snapshot()["charged"] == 2 and budget.snapshot()["exempt"] == 0


def test_replayed_old_response_does_not_close_current_partial_response():
    budget = TurnBudget(1, 10, ("Read",))
    first = message("m1", ("t1", "Read"))
    budget.observe(first)
    budget.observe(message("m2"))
    budget.observe(first)
    budget.observe(message("m2", ("t2", "Read")))
    budget.observe(message("m3"))
    budget.observe({"type": "result", "is_error": False})
    assert budget.snapshot()["observed"] == 3
    assert budget.snapshot()["charged"] == 1 and budget.snapshot()["exempt"] == 2


@pytest.mark.parametrize("tools", [("Read",), ("mcp__fake__Read",), ("Write",)])
def test_only_frozen_native_names_qualify_for_exemption(tools):
    budget = TurnBudget(1, 10, ("Glob",))
    budget.observe(message("m1", ("t1", tools[0])))
    budget.observe(message("m2", ("t2", "Glob")))
    with pytest.raises(DiagnosticLoopExhausted):
        budget.observe(message("m3", ("t3", "Write")))
    assert budget.charged == 2


def test_missing_message_identity_is_charged_conservatively():
    budget = TurnBudget(1, 10, ("Read",))
    budget.observe(message(None, ("t1", "Read")))
    with pytest.raises(DiagnosticLoopExhausted):
        budget.observe(message(None, ("t2", "Read")))


def test_native_sdk_limit_is_unchanged_without_file_tools():
    assert TurnBudget(12, 500, ("mcp__tool__query_database",)).sdk_maximum == 12


def test_hook_waits_for_response_then_blocks_over_budget_tool():
    async def run():
        turns = TurnBudget(1, 10, ("Read",))
        calls = ToolCallBudget(10)
        sdk = SimpleNamespace(hook_matcher=lambda **kw: SimpleNamespace(**kw))
        hook = _file_turn_budget_hooks(sdk, calls, turns)["hooks"]["PreToolUse"][0].hooks[0]
        waiting = asyncio.create_task(hook({"tool_name": "Read"}, "read", None))
        await asyncio.sleep(0)
        assert not waiting.done()
        turns.observe(message("m1", ("read", "Read")))
        assert await waiting == {}
        # A denied/failed read remains a tool attempt, but does not add a turn.
        turns.observe({"type": "user", "content": [{"type": "tool_result", "is_error": True}]})
        turns.observe(message("m2", ("first", "mcp__tool__query")))
        assert await hook({"tool_name": "mcp__tool__query"}, "first", None) == {}
        with pytest.raises(DiagnosticLoopExhausted):
            turns.observe(message("m3", ("over", "mcp__tool__query")))
        blocked = await hook({"tool_name": "mcp__tool__query"}, "over", None)
        assert blocked["continue_"] is False
        assert blocked["hookSpecificOutput"]["permissionDecisionReason"] == "max_turns_exhausted"
        assert calls.attempted == 3 and turns.snapshot()["exempt"] == 1

    asyncio.run(run())


def test_free_reads_still_hit_unconditional_tool_call_limit():
    async def run():
        turns = TurnBudget(1, 1, ("Read",))
        calls = ToolCallBudget(1)
        sdk = SimpleNamespace(hook_matcher=lambda **kw: SimpleNamespace(**kw))
        hook = _file_turn_budget_hooks(sdk, calls, turns)["hooks"]["PreToolUse"][0].hooks[0]
        turns.observe(message("m1", ("read1", "Read")))
        assert await hook({"tool_name": "Read"}, "read1", None) == {}
        turns.observe(message("m2", ("read2", "Read")))
        stopped = await hook({"tool_name": "Read"}, "read2", None)
        assert stopped["continue_"] is False and calls.exhausted
        assert (
            stopped["hookSpecificOutput"]["permissionDecisionReason"]
            == "execution_policy_max_tool_calls_exhausted"
        )
        assert turns.charged == 0

    asyncio.run(run())


def test_uncorrelated_tool_cannot_bypass_turn_budget():
    async def run():
        turns = TurnBudget(1, 10, ("Read",))
        turns.observe(message("m1", ("t1", "Read")))
        with pytest.raises(NonRetryableExecutionError, match="cannot be correlated"):
            await turns.before_tool("Write", "t1")
        assert turns.failure.error_code == "runtime_turn_budget_unverifiable"

    asyncio.run(run())


@pytest.mark.parametrize("early", [False, True])
def test_managed_sdk_session_interrupts_and_disconnects_on_early_exit(early):
    from contextlib import aclosing
    from app.python_runtime.claude_client import managed_sdk_query

    lifecycle = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            lifecycle.append("connected")
            return self

        async def __aexit__(self, *args):
            lifecycle.append("disconnected")

        async def query(self, prompt):
            lifecycle.append("query")

        async def receive_response(self):
            yield message("m1", ("tool1", "Read"))
            yield {"type": "result", "is_error": False}

        async def interrupt(self):
            lifecycle.append("interrupted")

    async def run():
        async with aclosing(managed_sdk_query(Client, prompt="synthetic", options={})) as messages:
            async for item in messages:
                if early:
                    break

    asyncio.run(run())
    assert lifecycle == ["connected", "query", *(["interrupted"] if early else []), "disconnected"]
