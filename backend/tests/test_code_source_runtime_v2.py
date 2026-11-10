"""Host-only grant/evidence barriers; synthetic files and SDK events, no model calls."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
from app.modules.knowledge.domain.code_answers import code_authorization_hash
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.python_runtime.code_source_mount import CodeSourceMount
from backend.tests.support.code_answers import analysis_context, code_configuration, confirm
from backend.tests.support.runtime import container


def proof():
    return dict(
        text="if (a.empty()) return reject;\n",
        line_start=1,
        line_end=1,
        repository_content_hash="a" * 64,
        read_content_hash="b" * 64,
        representation=dict(
            source_encoding="gb18030",
            newline="LF",
            keyword_policy="repository_unexpanded",
            working_content_hash="c" * 64,
            line_mapping="identity",
        ),
    )


@pytest.fixture
def source_grant(tmp_path):
    runtime = container()
    try:
        _, source, checkout, _ = code_configuration(runtime, tmp_path)
        ctx = analysis_context(runtime, source, checkout)
        access = KnowledgeJobAccess(
            ctx.job_id, ctx.actor_id, "app", "pub", "a" * 64, "b" * 64, ("code-kb",), "c" * 64
        )
        ctx = replace(ctx, authorization_hash=code_authorization_hash(access))
        grant = runtime.code_source_grant
        assert grant is not None
        grant.gate = SimpleNamespace(
            resolve=lambda **kw: access,
            snapshots=SimpleNamespace(
                verify=lambda job: {
                    "snapshot": {"tools": [{"tool_identifier": "knowledge_svn_update"}]}
                }
            ),
        )
        grant.store.authorize_context = lambda context: None
        grant.resources = SimpleNamespace(
            store=GovernanceStore(runtime.database),
            resolve=lambda base: SimpleNamespace(
                revision_id="code-config", source_id=source, fingerprint="d" * 64
            ),
        )
        capability = grant.for_job(ctx.job_id)
        request = RuntimePoolStore(runtime.database).request(ctx.invocation_id)
        request["prompt"]["retrieved_context"]["code_source"] = capability
        request["request_digest"] = canonical_request_digest(request)
        runtime.database.execute(
            "UPDATE agent_runtime_invocation SET request_digest=? WHERE invocation_id=?",
            (request["request_digest"], ctx.invocation_id),
        )
        runtime.database.execute(
            "UPDATE agent_runtime_request_snapshot SET request_digest=?,request_json=? WHERE invocation_id=?",
            (request["request_digest"], canonical_json(request), ctx.invocation_id),
        )
        binding = {k: request[k] for k in ("job_id", "invocation_id", "request_digest")}
        analysis = confirm(grant.store, ctx, grant.store.begin(ctx, "analysis"))
        yield grant, ctx, analysis, capability, binding
    finally:
        runtime.database.close()


def test_grant_is_frozen_to_original_invocation_and_shared_reader(source_grant):
    grant, ctx, analysis, capability, binding = source_grant
    assert grant.check_invocation(binding) == capability
    result = grant.check_invocation({**binding, "action": "grant", "analysis_id": analysis["id"]})
    assert result["revision"] == 100 and result["directory"] == "mes"
    assert "manifest" not in str(result) and "files" not in result
    with pytest.raises(CodeKnowledgeError):
        grant.check_invocation({**binding, "action": "grant", "analysis_id": "other"})
    grant.store.revoke(ctx, analysis["id"])
    with pytest.raises(CodeKnowledgeError, match="CODE_READ_GRANT_EXPIRED"):
        grant.check_invocation({**binding, "action": "grant", "analysis_id": analysis["id"]})


def test_runtime_evidence_is_metadata_only_and_quiesce_is_idempotent(source_grant):
    grant, ctx, analysis, _, binding = source_grant
    data = {k: v for k, v in proof().items() if k != "text"}
    data.update(
        kind="file_read", relative_path="set_server/Order.cpp", tool_call_id="toolu_synthetic"
    )
    request = {**binding, "action": "evidence", "analysis_id": analysis["id"], "evidence": data}
    first = grant.check_invocation(request)
    assert grant.check_invocation(request) == first
    row = grant.database.execute_one(
        f"SELECT * FROM {grant.store.t('code_evidence')} WHERE id=?", (first["evidence_id"],)
    )
    assert row["line_start"] == 1 and row["validated_at"]
    assert "return reject" not in str(row)
    with pytest.raises(CodeKnowledgeError):
        grant.check_invocation({**request, "evidence": {**data, "text": "fake source"}})
    quiesce = {**binding, "action": "quiesce", "analysis_id": analysis["id"]}
    assert grant.check_invocation(quiesce) == grant.check_invocation(quiesce)
    with pytest.raises(CodeKnowledgeError, match="CODE_READ_GRANT_EXPIRED"):
        grant.check_invocation(request)


def test_capability_change_never_expands_running_job(source_grant):
    grant, _, _, _, binding = source_grant
    grant.database.execute(
        f"UPDATE {grant.store.t('code_resource_config')} SET allowed_paths_json=? WHERE revision_id='code-config'",
        ('["other"]',),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_SOURCE_CAPABILITY_CHANGED"):
        grant.check_invocation(binding)


@pytest.fixture
def mount(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    calls = []
    grant = {"analysis_id": "analysis", "revision": 100}

    def check(value):
        calls.append(value)
        if value["action"] == "grant":
            return deepcopy(grant)
        if value["action"] == "evidence":
            return {"evidence_id": "verified", "svn_revision": 100}
        return {"analysis_id": "analysis", "state": "validating"}

    mount = CodeSourceMount(root=root, capability={"capability_hash": "f" * 64}, check=check)
    mount.grant = grant
    mount.reader = SimpleNamespace(
        root=root, read=lambda *args: proof(), tracked=lambda *a, **kw: {}
    )
    return mount, calls


def test_native_read_replaced_only_after_host_evidence_and_save_waits(mount):
    mount, calls = mount

    async def run():
        args = await mount.before_native(
            "Read",
            {"file_path": str(mount.root / "Order.cpp"), "offset": 1, "limit": 1},
            "toolu_read",
        )
        saving = asyncio.create_task(
            mount.before_mcp("knowledge_save_code_answer", {"analysis_id": "analysis"})
        )
        await asyncio.sleep(0)
        assert not saving.done() and not any(c["action"] == "quiesce" for c in calls)
        with pytest.raises(CodeKnowledgeError):
            await mount.before_native("Read", args, "toolu_late")
        output = {
            "type": "text",
            "file": {
                "filePath": args["file_path"],
                "content": "broken decoding",
                "numLines": 1,
                "startLine": 1,
                "totalLines": 1,
            },
        }
        response = await mount.after_native("toolu_read", output)
        assert (
            response["hookSpecificOutput"]["updatedToolOutput"]["file"]["content"]
            == proof()["text"]
        )
        assert "verified" in response["hookSpecificOutput"]["additionalContext"]
        await saving
        assert [c["action"] for c in calls][-2:] == ["evidence", "quiesce"]
        assert mount.pending == {}

    asyncio.run(run())


def test_no_grant_write_metadata_and_unknown_output_fail_closed(mount):
    mount, _ = mount

    async def run():
        for name, args in [
            ("Write", {"file_path": "source/a.cpp"}),
            ("Read", {"file_path": "source/.svn/wc.db"}),
            ("Read", {"file_path": "/outside/a.cpp"}),
            ("Glob", {"path": str(mount.root), "pattern": "**/*"}),
        ]:
            with pytest.raises(CodeKnowledgeError):
                await mount.before_native(name, args, "toolu_rejected")
            assert not mount.pending
        await mount.before_native(
            "Read", {"file_path": "source/a.cpp", "offset": 1, "limit": 1}, "toolu_read"
        )
        with pytest.raises(CodeKnowledgeError, match="CODE_SOURCE_READ_OUTPUT_UNSUPPORTED"):
            await mount.after_native("toolu_read", {"unexpected": "native shape"})
        assert not mount.pending
        mount.grant = None
        with pytest.raises(CodeKnowledgeError, match="CODE_READ_GRANT_REQUIRED"):
            await mount.before_native("Read", {"file_path": "source/a.cpp"}, "toolu_nogrant")

    asyncio.run(run())


def test_code_capability_preserves_existing_sandbox_files_without_a_source_grant(mount, tmp_path):
    from app.python_runtime.job_sandbox import JobSandboxManager
    from app.python_runtime.mcp_config import _code_source_hook_options
    from app.modules.agent.domain.runtime import ToolCallBudget
    from app.python_runtime.tool_contract import _builtin_tools

    source, _ = mount
    source.grant = None
    sandbox = JobSandboxManager(tmp_path / "mixed-sandboxes").create("mixed-job")
    sandbox.source_mount = source
    (sandbox.path / "inputs" / "context.md").write_text("synthetic attachment")
    context = SimpleNamespace(
        effective_tool_names=("Read", "Glob", "Grep", "Write", "Edit"),
        retrieved_context={"code_source": {}},
        mcp_bindings=(SimpleNamespace(server_code="file-service"),),
    )
    sdk = SimpleNamespace(hook_matcher=lambda **kwargs: SimpleNamespace(**kwargs))
    options = _code_source_hook_options(sdk, sandbox, context, ToolCallBudget(20))
    before = options["hooks"]["PreToolUse"][0].hooks[0]
    after = options["hooks"]["PostToolUse"][0].hooks[0]

    async def call(name, args, identifier):
        result = await before({"tool_name": name, "tool_input": args}, identifier, None)
        return result["hookSpecificOutput"]["permissionDecision"]

    async def run():
        assert (
            await call("Read", {"file_path": str(sandbox.path / "inputs/context.md")}, "file-read")
            == "allow"
        )
        assert await after({"tool_name": "Read", "tool_response": {}}, "file-read", None) == {}
        assert (
            await call(
                "Write", {"file_path": "work/notes.md", "content": "synthetic note"}, "file-write"
            )
            == "allow"
        )
        assert await call("Read", {"file_path": "source/Order.cpp"}, "source-read") == "deny"
        assert source.tool_denials["source-read"] == "CODE_READ_GRANT_REQUIRED"
        assert (
            await call("Glob", {"path": "source/set_server", "pattern": "*.cpp"}, "source-glob")
            == "deny"
        )
        assert source.tool_denials["source-glob"] == "CODE_READ_GRANT_REQUIRED"
        from app.python_runtime.tool_policy import normalize_tool_events

        event = normalize_tool_events(
            [
                {
                    "tool_name": "Glob",
                    "tool_call_id": "source-glob",
                    "status": "DENIED",
                    "error_code": source.tool_denials["source-glob"],
                }
            ],
            request={"protocol_version": "1.5", "mcp_servers": []},
        )[0]
        assert event["status"] == "DENIED"
        assert event["failure"]["retry_class"] == "NEVER"
        assert event["failure"]["code"] == "CODE_READ_GRANT_REQUIRED"
        assert (
            await call("Write", {"file_path": "source/Order.cpp", "content": "x"}, "source-write")
            == "deny"
        )
        assert await call("Read", {"file_path": "/etc/passwd"}, "outside-read") == "deny"
        context.effective_tool_names = ("Read", "Glob", "Grep")
        assert (
            await call("Write", {"file_path": "outputs/notes.md", "content": "x"}, "readonly-write")
            == "deny"
        )

    try:
        asyncio.run(run())
        context.retrieved_context = {"code_source": {"contract": "code-source-capability/v3"}}
        assert {t["tool_name"] for t in _builtin_tools(context, True)} == {
            "Read",
            "Glob",
            "Grep",
            "Write",
            "Edit",
        }
        assert {t["tool_name"] for t in _builtin_tools(context, False)} == {
            "Read",
            "Glob",
            "Grep",
            "Write",
        }
    finally:
        sandbox.cleanup()


@pytest.mark.parametrize(
    "code,expected_hint",
    [
        ("CODE_SOURCE_READ_LIMIT", "1–400"),
        ("CODE_CHECKOUT_SOURCE_MISMATCH", "授权目录或文件"),
        ("CODE_CHECKOUT_PERMISSION_DENIED", "权限"),
        ("CODE_SOURCE_SENSITIVE", "敏感内容"),
        ("synthetic-private-error", "不允许"),
    ],
)
def test_source_hook_keeps_safe_denial_reason_through_tool_audit(
    mount, tmp_path, code, expected_hint
):
    from app.modules.agent.domain.runtime import ToolCallBudget
    from app.python_runtime.job_sandbox import JobSandboxManager
    from app.python_runtime.mcp_config import _code_source_hook_options
    from app.python_runtime.tool_policy import normalize_tool_events

    source, _ = mount
    sandbox = JobSandboxManager(tmp_path / "denial-sandbox").create("denial-job")
    sandbox.source_mount = source
    context = SimpleNamespace(effective_tool_names=("Read", "Glob", "Grep"), mcp_bindings=())
    sdk = SimpleNamespace(hook_matcher=lambda **kwargs: SimpleNamespace(**kwargs))
    before = _code_source_hook_options(sdk, sandbox, context, ToolCallBudget(10))["hooks"][
        "PreToolUse"
    ][0].hooks[0]

    def reject(*args):
        raise CodeKnowledgeError(code)

    source.reader.read = reject
    try:
        result = asyncio.run(
            before(
                {"tool_name": "Read", "tool_input": {"file_path": str(source.root / "Order.cpp")}},
                "denied-read",
                None,
            )
        )
        decision = result["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert expected_hint in decision["permissionDecisionReason"]
        assert "synthetic-private" not in str(result)
        events = [{"tool_name": "Read", "tool_call_id": "denied-read", "status": "FAILED"}]
        source.apply_denials(events)
        audited = normalize_tool_events(
            events, request={"protocol_version": "1.5", "mcp_servers": []}
        )[0]
        assert audited["status"] == "DENIED"
        failure = audited["failure"]
        assert failure["code"] == (
            code if code != "synthetic-private-error" else "CODE_SOURCE_TOOL_DENIED"
        )
        assert failure["retry_class"] == "NEVER" and expected_hint in failure["safe_message"]
    finally:
        sandbox.cleanup()
