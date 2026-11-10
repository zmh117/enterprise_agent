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
    assert reader.search_candidates("src", "*.cpp") == ["src/Review.cpp", "src/订单.cpp"]
    assert reader.search_candidates("src", "**/*订单*.cpp") == ["src/订单.cpp"]
    with pytest.raises(CodeKnowledgeError, match="PATH_DENIED"):
        reader.search_candidates("other", "*")
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


def test_sensitive_or_binary_are_explicitly_incomplete_without_path_disclosure(setup):
    reader, sandbox, _ = setup
    add_file(reader, "src/credentials.cpp", b"synthetic fixture")
    add_file(reader, "src/image.cpp", b"\x00binary")
    batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "needle"}))
    batch.prepare("src")
    result = str(batch.render({"filenames": [], "content": ""}))
    assert "skipped_restricted_or_nontext=2" in result and "complete=false" in result
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
    with pytest.raises(CodeKnowledgeError, match="SEARCH_LIMIT"):
        reader.search_candidates("src", "*")
    assert reader.search_candidates("src", "*Review*") == ["src/Review.cpp"]
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
        {"head_limit": 0},
        {"-C": 6},
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
        args = {"path": "source/src", "pattern": "needle"}
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
        args = {"path": "source/src", "pattern": "needle"}
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
        effective_tool_names=("Read", "Glob", "Grep", "Write"), mcp_bindings=()
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
        await mount.before_native("Grep", {"path": "source/src", "pattern": "x"}, "search")
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
