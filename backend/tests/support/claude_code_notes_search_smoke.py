"""Actual bundled SDK/CLI plus synthetic Provider and source; no external model.

Mount only this support directory at /smoke (read-only) in the fresh Runtime image.
Run --network none --read-only --user 10002 --tmpfs /tmp:rw,size=256m,mode=1777.
"""

import asyncio
from contextlib import aclosing
from copy import deepcopy
import json
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer

from claude_agent_sdk import ClaudeAgentOptions
from claude_turn_budget_smoke import Provider
from code_search_fixture import make_reader
from app.modules.agent.domain.runtime import ToolCallBudget
from app.python_runtime.claude_client import load_claude_agent_sdk
from app.python_runtime.code_source_mount import CodeSourceMount
from app.python_runtime.job_sandbox import JobSandboxManager
from app.python_runtime.mcp_config import _code_source_hook_options
from app.python_runtime.turn_budget import TurnBudget


async def main():  # noqa: PLR0915
    with tempfile.TemporaryDirectory(prefix="code-search-smoke-") as directory:
        root = Path(directory)
        reader = make_reader(root / "sources")
        manager = JobSandboxManager(root / "jobs")
        sandbox = manager.create("synthetic-sdk-job")
        mount = CodeSourceMount(
            root=root / "sources", capability={}, check=lambda _: deepcopy(reader.grant)
        )
        mount.reader, mount.grant = reader, reader.grant
        sandbox.source_mount = mount
        sdk = load_claude_agent_sdk()
        tools = ("Read", "Glob", "Grep", "Write")
        context = SimpleNamespace(effective_tool_names=tools, mcp_bindings=())
        calls, turns = ToolCallBudget(20), TurnBudget(10, 20, tools)
        hooks = _code_source_hook_options(sdk, sandbox, context, calls, turns)
        after = hooks["hooks"]["PostToolUse"][0].hooks[0]
        before = hooks["hooks"]["PreToolUse"][0].hooks[0]
        results = []
        decisions = []
        tool_results = []

        async def capture_before(event, call_id, ctx):
            result = await before(event, call_id, ctx)
            decisions.append((event.get("tool_name"), result))
            return result

        hooks["hooks"]["PreToolUse"][0].hooks = [capture_before]

        async def capture(event, call_id, ctx):
            result = await after(event, call_id, ctx)
            if event.get("tool_name") == "Grep":
                results.append(result)
                if result.get("decision") == "block":
                    print(
                        json.dumps(
                            {"synthetic_grep_output": event.get("tool_response")},
                            ensure_ascii=False,
                        )
                    )
            return result

        hooks["hooks"]["PostToolUse"][0].hooks = [capture]
        Provider.sequence = [
            [
                (
                    "Grep",
                    {
                        "path": str(reader.root / "src"),
                        "pattern": "发布失败",
                        "output_mode": "content",
                        "-C": 1,
                    },
                )
            ],
            [
                (
                    "Grep",
                    {
                        "path": str(reader.root / "src"),
                        "pattern": "发布失败",
                        "output_mode": "files_with_matches",
                    },
                )
            ],
            [
                (
                    "Write",
                    {
                        "file_path": "work/notes/findings.md",
                        "content": "SVN r7; search located two files; source verification still needed.",
                    },
                )
            ],
            [("Read", {"file_path": "work/notes/findings.md"})],
            [("Grep", {"path": str(reader.root / "src"), "pattern": "never-matches-synthetic"})],
            [("Write", {"file_path": "outputs/forbidden.md", "content": "must not execute"})],
        ]
        Provider.requests, Provider.facts = 0, []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            terminal = None
            async with aclosing(
                sdk.query(
                    prompt="Execute synthetic tool test.",
                    options=ClaudeAgentOptions(
                        model="synthetic",
                        system_prompt="Synthetic fixture test.",
                        cwd=str(sandbox.path),
                        env={
                            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                            "ANTHROPIC_API_KEY": "synthetic-key",
                            "CLAUDE_CONFIG_DIR": str(root / "config"),
                            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                            "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
                        },
                        tools=list(tools),
                        allowed_tools=[],
                        permission_mode="default",
                        max_turns=turns.sdk_maximum,
                        mcp_servers={},
                        strict_mcp_config=True,
                        setting_sources=[],
                        skills=[],
                        **hooks,
                    ),
                )
            ) as messages:
                async for message in messages:
                    turns.observe(message)
                    if type(message).__name__ == "UserMessage":
                        tool_results.append(str(message))
                    if type(message).__name__ == "ResultMessage":
                        terminal = message
            assert terminal and not terminal.is_error
            assert len(results) == 3, results
            first = results[0]["hookSpecificOutput"]["updatedToolOutput"]
            assert "订单.cpp:2:发布失败" in first["content"], first
            assert "Review.cpp:2:发布失败" in first["content"], first
            assert ".code-search" not in json.dumps(results, ensure_ascii=False)
            assert len(results[1]["hookSpecificOutput"]["updatedToolOutput"]["filenames"]) == 2
            assert results[2]["hookSpecificOutput"]["updatedToolOutput"]["content"] == ""
            assert (sandbox.path / "work/notes/findings.md").exists(), (decisions, tool_results)
            assert not (sandbox.path / "outputs/forbidden.md").exists()
            assert not list((sandbox.path / ".code-search").glob("**/*.md"))
            assert calls.attempted == 6 and turns.snapshot()["exempt"] == 4
            print(
                json.dumps(
                    {
                        "passed": True,
                        "searched_files": 2,
                        "gb18030_chinese_match": True,
                        "notes_write_read": True,
                        "outside_notes_denied": True,
                        "search_cache_cleaned": True,
                        "turn_budget": turns.snapshot(),
                        "real_model_invoked": False,
                    }
                )
            )
        finally:
            server.shutdown()
            sandbox.cleanup()
            assert not sandbox.path.exists()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=60))
