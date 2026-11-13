import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.agent.domain.runtime import ToolCallBudget
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.python_runtime.code_source_mount import CodeSourceMount
from app.python_runtime.code_source_search import SourceSearchBatch, search_options
from app.python_runtime.job_sandbox import JobSandboxManager, JobSandboxError, JobSandboxLimits
from app.python_runtime.mcp_config import _code_source_hook_options
from backend.tests.support.code_search_fixture import make_reader, add_file


@pytest.fixture
def setup(tmp_path):
    reader = make_reader(tmp_path / "sources")
    sandbox = JobSandboxManager(tmp_path / "jobs").create("synthetic-job")
    mount = CodeSourceMount(
        root=tmp_path / "sources", capability={}, check=lambda _: deepcopy(reader.grant)
    )
    mount.reader, mount.grant, mount.sandbox = reader, reader.grant, sandbox
    sandbox.source_mount = mount
    yield reader, sandbox, mount
    sandbox.cleanup()


def test_search_only_tracked_scoped_files_and_normalizes_chinese(setup):
    reader, sandbox, _ = setup
    assert list(reader.search_candidates("src", "*.cpp")) == ["src/Review.cpp", "src/订单.cpp"]
    assert [p for p in reader.search_candidates("src", "**/*订单*.cpp") if p] == ["src/订单.cpp"]
    with pytest.raises(CodeKnowledgeError, match="PATH_DENIED"):
        list(reader.search_candidates("other", "*"))
    batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "发布", "-C": 1}))
    args = batch.prepare("src")
    assert args["glob"] == "*.md" and len(batch.paths) == 2
    paths = [str(sandbox.path / p) for p in batch.paths]
    output = batch.render({"filenames": [], "content": "\n".join(p + ":2:发布失败" for p in paths)})
    rendered = output["hookSpecificOutput"]["updatedToolOutput"]["content"]
    assert "订单.cpp:2:发布失败" in rendered and ".code-search" not in rendered
    assert "searched_files=2" in output["hookSpecificOutput"]["additionalContext"]
    assert sandbox.usage()[0] == 2
    batch.close()
    assert sandbox.usage() == (0, 0)


def test_nontext_is_explicitly_incomplete_without_path_disclosure(setup):
    reader, sandbox, _ = setup
    add_file(reader, "src/credentials.cpp", b"synthetic fixture")
    add_file(reader, "src/image.cpp", b"\x00binary")
    batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "needle"}))
    batch.prepare("src")
    result = str(batch.render({"filenames": [], "content": ""}))
    assert batch.scanned == 3 and batch.skipped == 1
    assert "skipped_nontext_or_oversized=1" in result and "complete=false" in result
    assert "credentials" not in result and "image.cpp" not in result
    batch.close()


@pytest.mark.parametrize("change", ["dirty", "wrong_revision", "symlink"])
def test_changed_source_stops_batch_and_releases_files(setup, change):
    reader, sandbox, mount = setup
    target = reader.root / "src/订单.cpp"
    if change == "dirty":
        target.write_text("changed")
    elif change == "wrong_revision":
        reader.grant["revision"] = 8
    else:
        target.unlink()
        target.symlink_to(reader.root / "src/untracked.cpp")

    async def run():
        with pytest.raises(CodeKnowledgeError):
            await mount.before_native("Grep", {"path": "source/src", "pattern": "needle"}, "t")
        assert not mount.pending and not mount.search_lock.locked()
        assert sandbox.usage() == (0, 0)

    asyncio.run(run())


def test_candidate_and_sandbox_capacity_limits_never_return_false_no_matches(setup):
    reader, sandbox, mount = setup
    for n in range(63):
        add_file(reader, f"src/f{n}.cpp", b"needle")
    assert len(list(reader.search_candidates("src", "*"))) == 65
    assert [p for p in reader.search_candidates("src", "*Review*") if p] == ["src/Review.cpp"]
    sandbox.limits = JobSandboxLimits(capacity_bytes=10, max_file_bytes=10)

    async def run():
        with pytest.raises(JobSandboxError):
            await mount.before_native(
                "Grep", {"path": "source/src", "glob": "*Review*", "pattern": "needle"}, "t"
            )
        assert not mount.pending and sandbox.usage() == (0, 0)

    asyncio.run(run())


@pytest.mark.parametrize(
    "args",
    [
        {"head_limit": -1},
        {"-C": -1},
        {"glob": "../*.cpp"},
        {"output_mode": "count"},
        {"multiline": True},
    ],
)
def test_search_rejects_unbounded_or_unknown_options(args):
    with pytest.raises(CodeKnowledgeError, match="SEARCH_INVALID"):
        search_options({"pattern": "x", **args})


def test_unknown_output_and_tool_failure_clean_search_cache(setup):
    _, sandbox, mount = setup

    async def run():
        args = {"path": "source/src", "pattern": "发布"}
        await mount.before_native("Grep", args, "bad")
        with pytest.raises(CodeKnowledgeError):
            await mount.after_native("bad", {"content": "/outside:1:injected"})
        assert sandbox.usage() == (0, 0) and not mount.search_lock.locked()
        await mount.before_native("Grep", args, "failed")
        await mount.failed("failed")
        assert sandbox.usage() == (0, 0) and not mount.pending

    asyncio.run(run())


def test_concurrent_searches_are_serial_and_cancel_waiter_is_clean(setup):
    _, sandbox, mount = setup

    async def run():
        args = {"path": "source/src", "pattern": "发布"}
        await mount.before_native("Grep", args, "first")
        next_search = asyncio.create_task(mount.before_native("Grep", args, "second"))
        await asyncio.sleep(0.01)
        assert not next_search.done() and sandbox.usage()[0] == 2
        next_search.cancel()
        with pytest.raises(asyncio.CancelledError):
            await next_search
        assert mount.search_lock.locked() and set(mount.pending) == {"first"}
        await mount.after_native("first", {"filenames": [], "content": ""})
        assert not mount.search_lock.locked() and sandbox.usage() == (0, 0)

    asyncio.run(run())


def test_cancel_preparation_waits_for_thread_before_removing_cache(setup, monkeypatch):
    import threading

    _, sandbox, mount = setup
    entered, finish = threading.Event(), threading.Event()
    prepare = SourceSearchBatch.prepare

    def slow_prepare(batch, path):
        entered.set()
        assert finish.wait(5)
        return prepare(batch, path)

    monkeypatch.setattr(SourceSearchBatch, "prepare", slow_prepare)

    async def run():
        task = asyncio.create_task(
            mount.before_native("Grep", {"path": "source/src", "pattern": "x"}, "cancel")
        )
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and mount.search_lock.locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not mount.pending and not mount.search_lock.locked()
        assert sandbox.usage() == (0, 0)

    asyncio.run(run())


def test_notes_only_write_and_cleanup_do_not_expand_source_or_other_job_access(setup, tmp_path):
    reader, sandbox, mount = setup
    context = SimpleNamespace(
        timeout_seconds=300, effective_tool_names=("Read", "Glob", "Grep", "Write"), mcp_bindings=()
    )
    hooks = _code_source_hook_options(
        SimpleNamespace(hook_matcher=lambda **k: SimpleNamespace(**k)),
        sandbox,
        context,
        ToolCallBudget(20),
    )
    before = hooks["hooks"]["PreToolUse"][0].hooks[0]
    other = JobSandboxManager(tmp_path / "jobs").create("other-job")

    async def run():
        def call(p):
            return before(
                {
                    "tool_name": "Write",
                    "tool_input": {"file_path": p, "content": "SVN r7; provisional finding"},
                },
                p,
                None,
            )

        result = await call("work/notes/investigation.md")
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        (sandbox.path / "work/notes/investigation.md").write_text("synthetic note")
        for p in (
            "outputs/note.md",
            "inputs/note.md",
            ".code-search/note.md",
            "work/note.md",
            "work/notes/../../escape.md",
            str(other.path / "work/notes/x.md"),
            str(reader.root / "src/订单.cpp"),
        ):
            assert (await call(p))["hookSpecificOutput"]["permissionDecision"] == "deny"
        (sandbox.path / "work/notes/link.md").symlink_to(other.path / "work/x.md")
        assert (await call("work/notes/link.md"))["hookSpecificOutput"][
            "permissionDecision"
        ] == "deny"
        (sandbox.path / "work/notes/link.md").unlink()
        await mount.before_native("Grep", {"path": "source/src", "pattern": "发布"}, "search")
        for name, args in (
            ("Read", {"file_path": next(iter(mount.searches["search"].paths))}),
            ("Glob", {"path": ".", "pattern": "**/*.md"}),
        ):
            with pytest.raises(JobSandboxError):
                sandbox.authorize_tool(name, args)
        await mount.failed("search")

    try:
        asyncio.run(run())
        sandbox.cleanup()
        assert not sandbox.path.exists() and other.path.exists()
    finally:
        other.cleanup()


def test_automatic_batches_find_business_reference_after_old_candidate_limit(setup):
    reader, sandbox, _ = setup
    for n in range(80):
        add_file(reader, f"src/F{n:03}.cpp", b"// unrelated business logic\n")
    add_file(reader, "src/ZSplit.cpp", b"throw ERR_SPLIT_QUALITY;\n")
    batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "ERR_SPLIT_QUALITY"}))
    try:
        batch.prepare("src")
        assert batch.scanned == 83 and batch.batches >= 3
        assert list(batch.paths.values()) == [str(reader.root / "src/ZSplit.cpp")]
        assert not batch.stopped_reason
        assert sandbox.usage()[0] == 1
    finally:
        batch.close()
    assert sandbox.usage() == (0, 0)


def test_filtering_pages_beyond_10000_metadata_entries_without_exposing_siblings(setup):
    import sqlite3

    reader, sandbox, _ = setup
    with sqlite3.connect(reader.root / ".svn/wc.db") as conn:
        conn.executemany(
            "INSERT INTO NODES(local_relpath,kind) VALUES(?,'file')",
            [(f"src/A{n:05}.txt",) for n in range(10005)],
        )
    batch = SourceSearchBatch(
        sandbox, reader, search_options({"pattern": "发布", "glob": "*.{cpp,h}", "type": "cpp"})
    )
    try:
        batch.prepare("")  # parent of the grant is a search anchor, never a read permission
        assert batch.enumerated == 10007 and batch.scanned == 2
        assert len(batch.paths) == 2 and not batch.stopped_reason
        assert all("/src/" in path for path in batch.paths.values())
        with pytest.raises(CodeKnowledgeError, match="PATH_DENIED"):
            reader.read("other/hidden.cpp", 1, 20)
    finally:
        batch.close()


def test_high_match_rate_returns_partial_and_bounds_live_artifacts(setup):
    reader, sandbox, _ = setup
    for n in range(80):
        add_file(reader, f"src/F{n:03}.cpp", b"needle\n")
    batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "needle"}))
    try:
        batch.prepare("src")
        assert len(batch.paths) == 32 and batch.stopped_reason == "match_capacity"
        context = batch.render({"filenames": [], "content": ""})["hookSpecificOutput"][
            "additionalContext"
        ]
        assert "complete=false" in context and "match_capacity" in context
        assert sandbox.usage()[0] == 32
    finally:
        batch.close()


def test_native_search_settings_are_safely_corrected_without_guessing_query():
    args = search_options(
        {
            "pattern": "ERR_SPLIT_QUALITY",
            "glob": "*.{cpp,h}",
            "type": "cpp",
            "-C": 20,
            "head_limit": 1000,
            "-n": False,
            "multiline": False,
        }
    )
    assert args["pattern"] == "ERR_SPLIT_QUALITY"
    assert args["glob"] == ("*.cpp", "*.h")
    assert args["head_limit"] == 200 and args["-C"] == 5 and args["-n"] is True
    assert args["corrections"]
    for glob in ("{..,src}/*.cpp", "*.{cpp,{h,hpp}}", "../*.cpp"):
        with pytest.raises(CodeKnowledgeError):
            search_options({"pattern": "x", "glob": glob})


def test_parameter_refusal_has_field_specific_hint_without_echoing_values(setup):
    from app.python_runtime.tool_policy import normalize_tool_events
    from app.shared.tool_response_summary import tool_response_summary

    reader, sandbox, mount = setup
    hooks = _code_source_hook_options(
        SimpleNamespace(hook_matcher=lambda **k: SimpleNamespace(**k)),
        sandbox,
        SimpleNamespace(
            timeout_seconds=300, effective_tool_names=("Read", "Glob", "Grep"), mcp_bindings=()
        ),
        ToolCallBudget(20),
    )
    before = hooks["hooks"]["PreToolUse"][0].hooks[0]

    async def run():
        result = await before(
            {
                "tool_name": "Grep",
                "tool_input": {
                    "path": "source/src",
                    "pattern": "synthetic private pattern",
                    "output_mode": "count",
                },
            },
            "bad",
            None,
        )
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "output_mode" in reason and "count" in reason
        assert "synthetic private" not in reason
        events = [{"tool_name": "Grep", "tool_call_id": "bad", "status": "FAILED"}]
        mount.apply_denials(events)
        audited = normalize_tool_events(
            events, request={"protocol_version": "1.5", "mcp_servers": []}
        )[0]
        summary = tool_response_summary({"failure": audited["failure"]})
        assert summary["error_code"] == "CODE_SOURCE_SEARCH_INVALID"
        assert "output_mode" in summary["error"] and "不支持 count" in summary["error"]
        assert "synthetic private" not in str(audited)
        assert not mount.pending and not mount.answers.unavailable
        corrected = await before(
            {
                "tool_name": "Grep",
                "tool_input": {
                    "path": "source/src",
                    "pattern": "发布",
                    "output_mode": "files_with_matches",
                },
            },
            "corrected",
            None,
        )
        assert corrected["hookSpecificOutput"]["permissionDecision"] == "allow"
        await mount.failed("corrected")
        assert not mount.pending and not mount.search_lock.locked()

    asyncio.run(run())


def test_invalid_regex_is_actionable_and_cleans_temporary_files(setup):
    _, sandbox, mount = setup

    async def run():
        with pytest.raises(CodeKnowledgeError) as failure:
            await mount.before_native("Grep", {"path": "source/src", "pattern": "("}, "regex")
        assert failure.value.location == "regex"
        assert sandbox.usage() == (0, 0) and not mount.search_lock.locked()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "src/zh-CN.js",
            "export default { password: '请输入密码', access_token: '访问令牌' };\n"
            "const splitError = '该批次质量状态不允许拆批！';\n",
        ),
        ("src/config.ts", "// ordinary configuration\nconst splitError = '批次不能拆批';\n"),
        ("src/token.cpp", '// ordinary field\nconst char *splitError = "批次不能拆批";\n'),
        (
            "src/Split.cpp",
            'const char *password = "synthetic-fixture-only";\n'
            'const char *splitError = "批次不能拆批";\n',
        ),
    ],
)
def test_authorized_source_names_and_content_reach_batch_search_and_read(setup, path, source):
    reader, sandbox, _ = setup
    add_file(reader, path, source.encode())
    batch = SourceSearchBatch(
        sandbox, reader, search_options({"pattern": "拆批", "output_mode": "files_with_matches"})
    )
    try:
        batch.prepare("src")
        original = str(reader.root / path)
        assert batch.skipped == 0 and list(batch.paths.values()) == [original]
        staged = sandbox.path / next(iter(batch.paths))
        assert staged.read_text() == source
        result = batch.render({"filenames": [str(staged)], "content": ""})["hookSpecificOutput"]
        assert result["updatedToolOutput"]["filenames"] == [original]
        assert "complete=true" in result["additionalContext"]
        assert reader.read(path, 1, 2)["text"] == source
        assert reader.read(path, 2, 1)["text"] == source.splitlines(keepends=True)[1]
    finally:
        batch.close()
    assert sandbox.usage() == (0, 0)


def test_closed_grant_stops_later_batches_and_cleans_every_file(setup, monkeypatch):
    reader, sandbox, mount = setup
    for n in range(80):
        add_file(reader, f"src/F{n:03}.cpp", b"irrelevant\n")
    original = SourceSearchBatch._filter

    def filter_then_revoke(batch, pending, deadline):
        original(batch, pending, deadline)
        mount.closing = True

    monkeypatch.setattr(SourceSearchBatch, "_filter", filter_then_revoke)

    async def run():
        with pytest.raises(CodeKnowledgeError, match="READS_CLOSED"):
            await mount.before_native(
                "Grep", {"path": "source/src", "pattern": "missing"}, "cancel"
            )
        assert sandbox.usage() == (0, 0) and not mount.pending and not mount.search_lock.locked()

    asyncio.run(run())


def test_split_error_trace_reaches_condition_and_state_definition(setup):
    reader, sandbox, _ = setup
    for n in range(70):
        add_file(reader, f"src/A{n:03}.cpp", b"// unrelated\n")
    add_file(reader, "src/Errors.h", 'ERR_SPLIT_QUALITY = "批次质量状态不允许拆批";\n'.encode())
    add_file(
        reader,
        "src/Quality.h",
        "enum Quality { Pending, Released, RiskReleased }; // 待检、放行、风险放行\n".encode(),
    )
    add_file(
        reader,
        "src/Split.cpp",
        b"void split(Quality quality) {\n if (quality != Released && quality != RiskReleased)\n  throw ERR_SPLIT_QUALITY;\n createChildBatch();\n}\n",
    )
    found = []
    for pattern in ("批次质量状态不允许拆批", "ERR_SPLIT_QUALITY", "enum Quality"):
        batch = SourceSearchBatch(
            sandbox, reader, search_options({"pattern": pattern, "glob": "*.{cpp,h}"})
        )
        try:
            batch.prepare("src")
            assert not batch.stopped_reason
            found.append({str(p).rsplit("/", 1)[-1] for p in batch.paths.values()})
        finally:
            batch.close()
    assert found == [{"Errors.h"}, {"Errors.h", "Split.cpp"}, {"Quality.h"}]
    branch = reader.read("src/Split.cpp", 1, 20)
    assert "quality != Released && quality != RiskReleased" in branch["text"]
    assert branch["text"].index("throw ERR_SPLIT_QUALITY") < branch["text"].index(
        "createChildBatch"
    )
    assert reader.read("src/Quality.h", 1, 20)["repository_content_hash"]


@pytest.mark.parametrize(
    "bound,value,reason",
    [
        ("MAX_SCAN_BYTES", 1, "byte_budget"),
        ("MAX_ENUMERATED", 1, "enumeration_budget"),
        ("MAX_SEARCH_SECONDS", 0, "time_budget"),
    ],
)
def test_scan_budgets_return_explicit_incomplete_and_release_cache(
    setup, monkeypatch, bound, value, reason
):
    import app.python_runtime.code_source_search as search

    reader, sandbox, _ = setup
    monkeypatch.setattr(search, bound, value)
    batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "发布"}))
    try:
        batch.prepare("src")
        context = batch.render({"filenames": [], "content": ""})["hookSpecificOutput"][
            "additionalContext"
        ]
        assert f"stopped_reason={reason}" in context
        assert "complete=false" in context
    finally:
        batch.close()
    assert sandbox.usage() == (0, 0)


def test_oversized_dependency_does_not_abort_search_or_weaken_direct_read(setup, monkeypatch):
    import app.python_runtime.code_checkout_reader as reader_module
    from app.python_runtime.code_tool_errors import code_tool_failure

    reader, sandbox, _ = setup
    add_file(reader, "src/A-large.lib", b"x" * 2000)
    add_file(reader, "src/Z-rule.cpp", b"ERR_SPLIT_QUALITY\n")
    monkeypatch.setattr(reader_module, "MAX_FILE", 1024)
    batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "ERR_SPLIT_QUALITY"}))
    try:
        batch.prepare("src")
        assert len(batch.paths) == 1 and batch.skipped == 1
        context = batch.render({"filenames": [], "content": ""})["hookSpecificOutput"][
            "additionalContext"
        ]
        assert "complete=false" in context and "A-large.lib" not in context
        with pytest.raises(CodeKnowledgeError, match="code_source_file_size_or_type"):
            reader.read("src/A-large.lib", 1, 1)
        assert (
            code_tool_failure("code_source_file_size_or_type")["code"]
            == "code_source_file_size_or_type"
        )
    finally:
        batch.close()
    assert sandbox.usage() == (0, 0)
