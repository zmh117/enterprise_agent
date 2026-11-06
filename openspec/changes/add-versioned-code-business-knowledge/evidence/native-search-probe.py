"""Synthetic loopback-only native SDK probe; no source, credentials or business data."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher
from types import SimpleNamespace
from app.modules.agent.domain.runtime import ToolCallBudget
from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory
from app.python_runtime.code_source_mount import CodeSourceMount
from app.python_runtime.job_sandbox import JobSandboxManager
from app.python_runtime.mcp_config import _code_source_hook_options


async def main():
    with TemporaryDirectory(dir="/tmp/python-agent-runtime", prefix="native-search-probe-") as temp:
        root = Path(temp)
        (root / "file.txt").write_text("synthetic needle\n")
        for component in ("set_server", "set_web/EBR", "set_web/JTH"):
            (root / "source" / component).mkdir(parents=True)
        (root / "source/set_server/file.cpp").write_text("synthetic needle\n")
        (root / "source/set_web/JTH/outside.js").write_text("synthetic outside scope\n")
        collector = LocalCodeCollector(root / "source")
        frozen = collector.freeze()
        store = CodeSnapshotDirectory(root / "snapshots")
        store.publish("synthetic-probe", frozen, collector)
        sandbox = JobSandboxManager(root / "sandboxes").create("synthetic-probe")
        sandbox.source_mount = CodeSourceMount(
            root=store.root,
            snapshot_id="synthetic-probe",
            manifest_hash=frozen.source_ref["manifest_hash"],
            allowed_prefixes=("set_server",),
            recheck=lambda: None,
        )
        actual_hook = _code_source_hook_options(
            SimpleNamespace(hook_matcher=HookMatcher),
            sandbox,
            SimpleNamespace(effective_tool_names=("Read", "Grep", "Glob")),
            ToolCallBudget(maximum=10),
        )["hooks"]["PreToolUse"][0].hooks[0]
        steps = [
            (
                "Grep",
                {
                    "path": str(sandbox.source_mount.root / "set_server/file.cpp"),
                    "pattern": "needle",
                    "output_mode": "content",
                },
            ),
            (
                "Grep",
                {
                    "path": str(sandbox.source_mount.root / "set_web/JTH/outside.js"),
                    "pattern": "outside",
                },
            ),
            ("Glob", {"path": str(sandbox.source_mount.root / "set_server"), "pattern": "*.cpp"}),
            ("Read", {"file_path": str(sandbox.source_mount.root / "set_server/file.cpp")}),
        ]
        sent = [0]
        results = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if "count_tokens" in self.path:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"input_tokens":100}')
                    return
                index = sent[0]
                sent[0] += 1
                block = (
                    {
                        "type": "tool_use",
                        "id": "probe-" + str(index),
                        "name": steps[index][0],
                        "input": steps[index][1],
                    }
                    if index < len(steps)
                    else {"type": "text", "text": "Synthetic probe finished."}
                )
                reason = "tool_use" if index < len(steps) else "end_turn"
                message = {
                    "id": "msg_probe_" + str(index),
                    "type": "message",
                    "role": "assistant",
                    "model": body.get("model", "synthetic"),
                    "content": [block],
                    "stop_reason": reason,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": 30},
                }
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/event-stream" if body.get("stream") else "application/json",
                )
                self.end_headers()
                if not body.get("stream"):
                    self.wfile.write(json.dumps(message).encode())
                    return
                events = [
                    (
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {**message, "content": [], "stop_reason": None},
                        },
                    ),
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {
                                **block,
                                **({"input": {}} if block["type"] == "tool_use" else {"text": ""}),
                            },
                        },
                    ),
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": (
                                {
                                    "type": "input_json_delta",
                                    "partial_json": json.dumps(block["input"]),
                                }
                                if block["type"] == "tool_use"
                                else {"type": "text_delta", "text": block["text"]}
                            ),
                        },
                    ),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    (
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": reason, "stop_sequence": None},
                            "usage": {"output_tokens": 30},
                        },
                    ),
                    ("message_stop", {"type": "message_stop"}),
                ]
                for event, data in events:
                    self.wfile.write(
                        ("event: " + event + "\ndata: " + json.dumps(data) + "\n\n").encode()
                    )
                self.wfile.flush()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        async def hook(event, *_):
            print(
                json.dumps(
                    {
                        "hook_tool": event.get("tool_name"),
                        "input_keys": sorted(event.get("tool_input", {})),
                    }
                ),
                flush=True,
            )
            result = await actual_hook(event, None, None)
            print(json.dumps({"decision": result}), flush=True)
            return result

        env = {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:" + str(server.server_port),
            "ANTHROPIC_API_KEY": "synthetic-probe-only",
            "CLAUDE_CONFIG_DIR": str(root / ".claude"),
            "HOME": str(root),
            "TMPDIR": str(root),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        options = ClaudeAgentOptions(
            cwd=str(sandbox.path),
            tools=["Grep", "Glob", "Read"],
            allowed_tools=["Grep", "Glob", "Read"],
            model="claude-sonnet-4-5",
            max_turns=6,
            env=env,
            setting_sources=[],
            hooks={"PreToolUse": [HookMatcher(hooks=[hook])]},
            stderr=lambda _: None,
        )
        try:
            async for message in query(
                prompt="Run the three synthetic file tool checks.", options=options
            ):
                for block in getattr(message, "content", []) or []:
                    if hasattr(block, "tool_use_id"):
                        results.append((block.tool_use_id, bool(block.is_error), block.content))
                        print(
                            json.dumps(
                                {
                                    "tool_use_id": block.tool_use_id,
                                    "is_error": block.is_error,
                                    "synthetic_result": block.content,
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
            assert [item[1] for item in results] == [False, True, False, False], results
            assert "synthetic needle" in results[0][2]
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            for path in [root, *root.rglob("*")]:
                path.chmod(0o700 if path.is_dir() else 0o600)


asyncio.run(asyncio.wait_for(main(), timeout=50))
