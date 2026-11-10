"""Actual SDK/CLI loop against an in-container synthetic provider; no real model.

Run on a Runtime image with --network none --read-only --tmpfs /tmp:rw,size=256m.
Pass this script on stdin; mount no secrets or source checkouts.
"""

import asyncio
import json
import os
import tempfile
import threading
from contextlib import aclosing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from app.modules.agent.domain.runtime import ToolCallBudget
from app.python_runtime.claude_client import load_claude_agent_sdk
from app.python_runtime.mcp_config import _file_turn_budget_hooks
from app.python_runtime.turn_budget import TurnBudget
from app.shared.exceptions import DiagnosticLoopExhausted


class Provider(BaseHTTPRequestHandler):
    sequence = []
    requests = 0
    facts = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if "count_tokens" in self.path:
            data = json.dumps({"input_tokens": 10}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        index = Provider.requests
        Provider.requests += 1
        blocks = Provider.sequence[index] if index < len(Provider.sequence) else []
        Provider.facts.append(
            {
                "path": self.path,
                "stream": body.get("stream"),
                "model": body.get("model"),
                "max_tokens": body.get("max_tokens"),
                "tool_count": len(body.get("tools", [])),
                "responded_tools": [name for name, _ in blocks],
            }
        )
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": f"msg_{index}",
                    "type": "message",
                    "role": "assistant",
                    "model": body.get("model", "synthetic"),
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            }
        ]
        for block_index, (name, arguments) in enumerate(blocks):
            events.extend(
                [
                    {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": f"tool_{index}_{block_index}",
                            "name": name,
                            "input": {},
                        },
                    },
                    {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(arguments),
                        },
                    },
                    {"type": "content_block_stop", "index": block_index},
                ]
            )
        if not blocks:
            events.extend(
                [
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "Synthetic completed."},
                    },
                    {"type": "content_block_stop", "index": 0},
                ]
            )
        events.extend(
            [
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": "tool_use" if blocks else "end_turn",
                        "stop_sequence": None,
                    },
                    "usage": {"output_tokens": 5},
                },
                {"type": "message_stop"},
            ]
        )
        data = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


async def scenario(root, server, kind):
    folder = root / kind
    folder.mkdir()
    fixture = folder / "fixture.txt"
    fixture.write_text("synthetic needle\n")
    write1, write2 = folder / "first.txt", folder / "must-not-exist.txt"
    reads = [
        [("Glob", {"path": str(folder), "pattern": "fixture.txt"})],
        [
            (
                "Grep",
                {"path": str(fixture), "pattern": "needle", "output_mode": "files_with_matches"},
            )
        ],
        [("Read", {"file_path": str(fixture), "offset": 1, "limit": 1})],
    ]
    Provider.sequence = (
        reads
        if kind != "mixed-limit"
        else [
            [("Write", {"file_path": str(write1), "content": "synthetic"})],
            reads[-1],
            [("Write", {"file_path": str(write2), "content": "must not execute"})],
        ]
    )
    Provider.requests = 0
    Provider.facts = []
    calls = ToolCallBudget(2 if kind == "tool-limit" else 10)
    turns = TurnBudget(1, calls.maximum, ("Read", "Glob", "Grep", "Write"))
    hooks = _file_turn_budget_hooks(SimpleNamespace(hook_matcher=HookMatcher), calls, turns)
    terminal = None
    failure = None
    try:
        async with aclosing(
            load_claude_agent_sdk().query(
                prompt="Execute the synthetic fixture test.",
                options=ClaudeAgentOptions(
                    model="synthetic",
                    system_prompt="Synthetic fixture test.",
                    cwd=str(folder),
                    env={
                        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                        "ANTHROPIC_API_KEY": "synthetic-key",
                        "CLAUDE_CONFIG_DIR": str(folder / "config"),
                        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    },
                    tools=["Read", "Glob", "Grep", "Write"],
                    allowed_tools=["Read", "Glob", "Grep", "Write"],
                    max_turns=turns.sdk_maximum,
                    permission_mode="dontAsk",
                    mcp_servers={},
                    strict_mcp_config=True,
                    setting_sources=[],
                    skills=[],
                    extra_args={"no-session-persistence": None},
                    **hooks,
                ),
            )
        ) as messages:
            async for item in messages:
                turns.observe(item)
                if type(item).__name__ == "ResultMessage":
                    terminal = item
    except Exception as exc:
        failure = type(exc).__name__
    if kind == "reads":
        assert failure is None and terminal is not None and not terminal.is_error, (
            failure,
            turns.snapshot(),
        )
        assert calls.attempted == 3
        assert turns.snapshot()["exempt"] == 3 and turns.charged == 1
    elif kind == "mixed-limit":
        assert isinstance(turns.failure, DiagnosticLoopExhausted), (failure, turns.snapshot())
        assert write1.exists() and not write2.exists()
    else:
        assert calls.exhausted and calls.attempted == 3, {
            "failure": failure,
            "requests": Provider.requests,
            "calls": calls.attempted,
            "budget": turns.snapshot(),
            "terminal_subtype": getattr(terminal, "subtype", None),
            "terminal_turns": getattr(terminal, "num_turns", None),
            "requests_metadata": Provider.facts,
        }
    print(
        json.dumps(
            {
                "scenario": kind,
                "passed": True,
                "provider_requests": Provider.requests,
                "tool_attempts": calls.attempted,
                "turn_budget": turns.snapshot(),
                "real_model_invoked": False,
            }
        )
    )


async def main():
    with tempfile.TemporaryDirectory(prefix="turn-budget-smoke-") as directory:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for kind in ("reads", "mixed-limit", "tool-limit"):
                await asyncio.wait_for(scenario(Path(directory), server, kind), timeout=45)
        finally:
            server.shutdown()


if __name__ == "__main__":
    os.environ["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    asyncio.run(main())
