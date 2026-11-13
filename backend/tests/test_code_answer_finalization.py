"""Question binding, bounded Stop hooks and durable save failures with synthetic evidence."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import threading

import pytest

from app.modules.agent.domain.runtime import ToolCallBudget, AgentExecutionContext, AgentRunRequest
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.code_save_outcome import record_save_outcomes
from app.python_runtime.code_answer_finalization import CodeAnswerFinalization
from app.python_runtime.code_source_mount import CodeSourceMount
from app.python_runtime.claude_client import (
    _code_save_fallback,
    load_claude_agent_sdk,
    ClaudeSdkClient,
    ClaudeSdk,
    _LocalExecutionTimeout,
)
from app.python_runtime.job_sandbox import JobSandboxManager
from app.python_runtime.mcp_config import _code_source_hook_options
from app.python_runtime.turn_budget import TurnBudget
from backend.tests.test_code_answer_store import prepared, workspace as workspace_fixture
from backend.tests.test_knowledge_runtime_dispatch import Remote, bridge
from backend.tests.test_knowledge_save_diagnostics import save_args
from backend.tests.support.runtime import test_settings as build_settings
from app.shared.exceptions import NonRetryableExecutionError, DiagnosticLoopExhausted
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditContext

workspace = workspace_fixture


def bind(state, analysis="analysis", *, question="Synthetic code question", base="kb-synthetic"):
    search = dict(
        source_kind="code",
        search_id="search",
        environment="test",
        knowledge_base_id=base,
        source_id="source",
        checkout_id="checkout",
        requested_revision=100,
    )
    state.observe("knowledge_search", {"query": question}, search)
    update = {
        k: search[k] for k in ("environment", "knowledge_base_id", "source_id", "checkout_id")
    }
    update.update(search_id="search", revision=100)
    state.prepare("knowledge_svn_update", update)
    state.observe(
        "knowledge_svn_update",
        update,
        {
            "analysis_id": analysis,
            "svn_revision": 100,
            "state": "queued",
        },
    )
    return update


def test_rephrased_save_uses_bound_question_and_keeps_server_evidence_gate(workspace):
    _, store, _, _ = workspace
    ctx, analysis, result = prepared(workspace)
    state = CodeAnswerFinalization()
    bind(state, analysis["id"], base="code-kb")
    arguments = dict(
        analysis_id=analysis["id"],
        environment="test",
        knowledge_base_id="code-kb",
        question="A paraphrased title",
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_QUESTION_MISMATCH"):
        store.save(
            ctx,
            analysis["id"],
            question=arguments["question"],
            result=result,
            visibility_scope={"paths": ["set_server"]},
            request_key="save",
        )
    state.prepare("knowledge_save_code_answer", arguments)
    invalid = deepcopy(result)
    invalid["claims"][0]["evidence_ids"] = ["unobserved"]
    with pytest.raises(CodeKnowledgeError, match="CODE_EVIDENCE_UNVERIFIED"):
        store.save(
            ctx,
            analysis["id"],
            question=arguments["question"],
            result=invalid,
            visibility_scope={"paths": ["set_server"]},
            request_key="save",
        )
    first = store.save(
        ctx,
        analysis["id"],
        question=arguments["question"],
        result=result,
        visibility_scope={"paths": ["set_server"]},
        request_key="save",
    )
    arguments["question"] = "Another paraphrase during replay"
    state.prepare("knowledge_save_code_answer", arguments)
    replay = store.save(
        ctx,
        analysis["id"],
        question=arguments["question"],
        result=result,
        visibility_scope={"paths": ["set_server"]},
        request_key="save",
    )
    assert replay == first and first["index_state"] == "pending"
    assert len(store.db.execute(f"SELECT id FROM {store.t('code_index_task')}")) == 1


def test_unbound_other_analysis_or_changed_scope_never_substitutes_a_question():
    state = CodeAnswerFinalization()
    args = save_args()
    with pytest.raises(CodeKnowledgeError, match="CODE_SUCCESSFUL_SEARCH_REQUIRED"):
        state.prepare("knowledge_save_code_answer", args)
    update = bind(state)
    for field, value in (("environment", "other"), ("revision", 101), ("search_id", "missing")):
        with pytest.raises(CodeKnowledgeError):
            state.prepare("knowledge_svn_update", {**update, field: value})
    with pytest.raises(CodeKnowledgeError):
        state.prepare("knowledge_save_code_answer", {**args, "analysis_id": "other"})
    with pytest.raises(CodeKnowledgeError, match="CODE_ANALYSIS_MISMATCH"):
        state.prepare("knowledge_save_code_answer", {**args, "knowledge_base_id": "other"})


def test_bridge_canonicalizes_actual_wire_request_without_mutating_model_input(tmp_path):
    async def run():
        mount = CodeSourceMount(
            root=tmp_path, capability={}, check=lambda _: {"state": "validating"}
        )
        bind(mount.answers)
        mount.grant = {"analysis_id": "analysis"}
        client = bridge(Remote(), source_guard=mount)
        sent = []

        async def rpc(method, params, **kwargs):
            sent.append(deepcopy(params["arguments"]))
            return {
                "content": [],
                "structuredContent": {
                    "analysis_id": "analysis",
                    "saved": True,
                    "support_status": "partial",
                },
                "isError": False,
            }

        client._rpc = rpc
        original = save_args()
        original["question"] = "模型重新组织的问题"
        try:
            assert not (await client.call_tool("knowledge_save_code_answer", original)).is_error
            assert sent[0]["question"] == "Synthetic code question"
            assert original["question"] == "模型重新组织的问题"
            assert mount.grant is None and mount.saved_analysis_id == "analysis"
            assert not (await client.call_tool("knowledge_save_code_answer", original)).is_error
            assert sent[0] == sent[1]
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("blocked", [None, "tools", "turns", "auth", "already_saved", "recursive"])
def test_real_sdk_stop_hook_is_once_and_respects_budget_and_save_state(tmp_path, blocked):
    sandbox = JobSandboxManager(tmp_path / "sandboxes").create("stop-test")
    mount = CodeSourceMount(root=tmp_path, capability={}, check=lambda _: {})
    bind(mount.answers)
    mount.grant = {"analysis_id": "analysis"}
    sandbox.source_mount = mount
    context = SimpleNamespace(
        timeout_seconds=300,
        effective_tool_names=("Read", "Glob", "Grep"),
        mcp_bindings=(),
    )
    tools, turns = ToolCallBudget(10), TurnBudget(10, 10, context.effective_tool_names)
    if blocked == "tools":
        tools.attempted = 10
    elif blocked == "turns":
        turns.charged = 8
    elif blocked == "auth":
        mount.answers.failed("knowledge_principal_refresh_failed")
    elif blocked == "already_saved":
        mount.grant = None
    options = _code_source_hook_options(load_claude_agent_sdk(), sandbox, context, tools, turns)
    stop = options["hooks"]["Stop"][0].hooks[0]
    event = {
        "last_assistant_message": "已核验的业务回答",
        "stop_hook_active": blocked == "recursive",
    }
    try:
        first = asyncio.run(stop(event, None, None))
        assert (first.get("decision") == "block") == (blocked is None)
        assert asyncio.run(stop(event, None, None)) == {}
        if blocked is None:
            assert _code_save_fallback(sandbox, None, budget_failed=True) == "已核验的业务回答"
            cancelled = threading.Event()
            cancelled.set()
            assert _code_save_fallback(sandbox, cancelled, budget_failed=True) == ""
        assert _code_save_fallback(sandbox, None, budget_failed=False) == ""
    finally:
        sandbox.cleanup()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("missing", "not_attempted"),
        ("failure", "failed"),
        ("partial", "saved_partial"),
        ("supported", "saved"),
    ],
)
def test_persisted_save_outcome_is_independent_of_index_tasks(workspace, case, expected):
    _, store, _, _ = workspace
    ctx, analysis, result = prepared(workspace)
    if case == "failure":
        audit = McpAuditCoordinator(store.db, max_payload_bytes=16384)
        handle = audit.begin(
            McpAuditContext(
                correlation_id=ctx.job_id,
                job_id=ctx.job_id,
                session_id=store.db.execute_one(
                    "SELECT session_id FROM agent_job WHERE id=?", (ctx.job_id,)
                )["session_id"],
                invocation_id=ctx.invocation_id,
                actor_user_id=ctx.actor_id,
                server_code="knowledge-mcp",
                tool_identifier="knowledge_save_code_answer",
            ),
            business_request={"tool": "knowledge_save_code_answer", "analysis_id": analysis["id"]},
        )
        audit.complete(
            handle,
            status="FAILED",
            duration_ms=1,
            error_code="CODE_QUESTION_MISMATCH",
            business_response={"error_code": "CODE_QUESTION_MISMATCH"},
        )
        store.db.execute(
            "UPDATE agent_runtime_invocation SET execution_quiesced_at=? WHERE invocation_id=?",
            (analysis["created_at"], ctx.invocation_id),
        )
        store.release_stopped(ctx, analysis["id"])
        store.db.execute(
            "UPDATE agent_tool_call SET created_at='2099-01-01T00:00:00+00:00' WHERE id=?",
            (handle.agent_tool_call_id,),
        )
    elif case in {"partial", "supported"}:
        result["support_status"] = case
        store.save(
            ctx,
            analysis["id"],
            question="Synthetic code question",
            result=result,
            visibility_scope={"paths": ["set_server"]},
            request_key="save",
        )
    record_save_outcomes(store.db, ctx.job_id, ctx.invocation_id)
    record_save_outcomes(store.db, ctx.job_id, ctx.invocation_id)
    report = json_value(store.row("code_analysis", analysis["id"])["report_json"])
    outcome = report["knowledge_save"]
    assert outcome["state"] == expected
    assert "private-text" not in json.dumps(outcome)
    assert outcome["error_code"] == ("CODE_QUESTION_MISMATCH" if case == "failure" else None)
    assert len(store.db.execute(f"SELECT id FROM {store.t('code_index_task')}")) == int(
        case == "supported"
    )


@pytest.mark.parametrize(
    "failure", ["timeout", "tool_budget", "turn_budget", "cancelled", "unverifiable"]
)
def test_sdk_budget_failure_during_save_reminder_preserves_answer_but_not_cancellation(
    tmp_path, failure
):
    cancellation = threading.Event()
    captured = {}

    class Sandboxes(JobSandboxManager):
        def create(self, job_id):
            sandbox = super().create(job_id)
            mount = CodeSourceMount(root=tmp_path, capability={}, check=lambda _: {})
            bind(mount.answers)
            mount.grant = {"analysis_id": "analysis"}
            sandbox.source_mount = mount
            return sandbox

    class Client(ClaudeSdkClient):
        def _build_options(self, sdk, context, server, stderr, binding, **kwargs):
            options = super()._build_options(sdk, context, server, stderr, binding, **kwargs)
            captured["budget"] = kwargs["tool_call_budget"]
            captured["turn_budget"] = kwargs["turn_budget"]
            options.update(
                _code_source_hook_options(
                    sdk,
                    self._sandbox.get(),
                    context,
                    kwargs["tool_call_budget"],
                    kwargs["turn_budget"],
                )
            )
            return options

    async def query(*, options, **kwargs):
        yield {
            "type": "assistant",
            "message": {
                "id": "draft",
                "content": [{"type": "text", "text": "保留的业务回答"}],
            },
        }
        stop = options["hooks"]["Stop"][0].hooks[0]
        assert (await stop({"last_assistant_message": "保留的业务回答"}, None, None))[
            "decision"
        ] == "block"
        if failure == "timeout":
            raise _LocalExecutionTimeout()
        if failure == "turn_budget":
            raise DiagnosticLoopExhausted("SDK max turns reached", error_code="max_turns_exhausted")
        if failure == "cancelled":
            cancellation.set()
            raise NonRetryableExecutionError("cancelled", error_code="runtime_cancelled")
        if failure == "unverifiable":
            captured["turn_budget"].failure = NonRetryableExecutionError(
                "unverifiable", error_code="runtime_turn_budget_unverifiable"
            )
            captured["turn_budget"].raise_if_failed()
        budget = captured["budget"]
        budget.attempted = budget.maximum
        budget.consume()

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kwargs: kwargs,
        tool=None,
        create_sdk_mcp_server=None,
        tool_annotations=None,
        hook_matcher=load_claude_agent_sdk().hook_matcher,
    )
    client = Client(
        model="synthetic-model",
        limits=build_settings().execution,
        api_key="runtime-model-key-value",
        sdk_loader=lambda: sdk,
        sandbox_manager=Sandboxes(tmp_path / "runtime"),
        cancellation_event=cancellation,
    )
    context = AgentExecutionContext(
        system_role="synthetic",
        safety_rules=[],
        user_question="合成问题",
        project_code="test",
        allowed_tools=[],
        tool_restrictions=[],
        skills={},
        conversation_summary="",
        retrieved_context={"code_source": {"contract": "code-source-capability/v3"}},
        effective_tool_names=("Read",),
    )
    request = AgentRunRequest(
        job_id="test-save-reminder", user_id="user", project_code="test", context=context
    )
    if failure in {"cancelled", "unverifiable"}:
        with pytest.raises(NonRetryableExecutionError) as error:
            client.run(request)
        assert error.value.error_code == (
            "runtime_cancelled" if failure == "cancelled" else "runtime_turn_budget_unverifiable"
        )
    else:
        assert client.run(request).final_answer == "保留的业务回答"
    assert not list((tmp_path / "runtime").glob("job-*"))
