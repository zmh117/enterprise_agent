"""Real installed CLI tool response/hook proof against an isolated loopback provider.

Run with read/block/glob/grep. No real model calls or repository files are used.
"""

import asyncio
import json
import tempfile
import threading
import sys

from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query

mode = sys.argv[1] if len(sys.argv) > 1 else "read"
assert mode in {"read", "block", "glob", "grep"}
tool = {"glob": "Glob", "grep": "Grep"}.get(mode, "Read")

captured = {}
requests = []
with tempfile.TemporaryDirectory(prefix="code-native-hook-") as temp:
    root = Path(temp)
    source = root / "input.cpp"
    source.write_text("ORIGINAL_SYNTHETIC\n")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("count_tokens"):
                data = json.dumps({"input_tokens": 10}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            requests.append(value)
            first = not any(
                block.get("type") == "tool_result"
                for m in value.get("messages", [])
                for block in (m.get("content") if isinstance(m.get("content"), list) else [])
            )
            block = (
                {
                    "type": "tool_use",
                    "id": "toolu_synthetic_read",
                    "name": tool,
                    "input": (
                        {"path": str(root), "pattern": "*.cpp"}
                        if mode == "glob"
                        else {
                            "path": str(source),
                            "pattern": "SYNTHETIC",
                            "output_mode": "files_with_matches",
                            "head_limit": 1,
                        }
                        if mode == "grep"
                        else {"file_path": str(source), "offset": 1, "limit": 1}
                    ),
                }
                if first
                else {"type": "text", "text": "synthetic done"}
            )
            stop = "tool_use" if first else "end_turn"
            message = {
                "id": "msg_synthetic",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": [block],
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }
            if not value.get("stream"):
                data = json.dumps(message).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
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
                        "content_block": {**block, "input": {}}
                        if first
                        else {"type": "text", "text": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(block["input"]),
                        }
                        if first
                        else {"type": "text_delta", "text": block["text"]},
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                (
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": stop, "stop_sequence": None},
                        "usage": {"output_tokens": 10},
                    },
                ),
                ("message_stop", {"type": "message_stop"}),
            ]
            data = "".join(
                "event: " + kind + "\ndata: " + json.dumps(body) + "\n\n" for kind, body in events
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def before(event, call_id, ctx):
        return {
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
        }

    async def after(event, call_id, ctx):
        response = event["tool_response"]
        captured["shape"] = response
        if mode == "block":
            return {
                "continue_": False,
                "decision": "block",
                "stopReason": "synthetic guard blocked",
            }
        if mode in ("glob", "grep"):
            return {}
        altered = json.loads(json.dumps(response))
        altered["file"]["content"] = "REPLACED_SYNTHETIC\n"
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": altered,
                "additionalContext": "synthetic evidence",
            }
        }

    async def run():
        options = ClaudeAgentOptions(
            cwd=str(root),
            setting_sources=[],
            tools=[tool],
            allowed_tools=[],
            permission_mode="dontAsk",
            mcp_servers={},
            strict_mcp_config=True,
            extra_args={"no-session-persistence": None},
            max_turns=2,
            env={
                "ANTHROPIC_API_KEY": "synthetic-loopback-only",
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "CLAUDE_CONFIG_DIR": str(root / "cli-config"),
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_TELEMETRY": "1",
                "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
            },
            hooks={
                "PreToolUse": [HookMatcher(hooks=[before], on_failure="block")],
                "PostToolUse": [HookMatcher(hooks=[after], on_failure="block")],
            },
        )
        async with asyncio.timeout(30):
            async for message in query(prompt="Read the synthetic file once.", options=options):
                pass

    try:
        asyncio.run(run())
        returned = [
            block
            for r in requests
            for m in r.get("messages", [])
            for block in (m.get("content") if isinstance(m.get("content"), list) else [])
            if block.get("type") == "tool_result"
        ]
        evidence = json.dumps(returned)
        if mode == "block":
            assert not returned
        elif mode == "read":
            assert (
                returned
                and "REPLACED_SYNTHETIC" in evidence
                and "ORIGINAL_SYNTHETIC" not in evidence
            )
        else:
            assert "filenames" in captured["shape"] and len(captured["shape"]["filenames"]) == 1
        config_files = [p for p in (root / "cli-config").rglob("*") if p.is_file()]
        assert not list((root / "cli-config" / "projects").rglob("*.jsonl"))
        for file in config_files:
            assert b"ORIGINAL_SYNTHETIC" not in file.read_bytes()
            assert b"REPLACED_SYNTHETIC" not in file.read_bytes()
        print(
            json.dumps(
                {
                    "mode": mode,
                    "response_keys": sorted(captured["shape"]),
                    "file_keys": sorted(captured["shape"].get("file", {})),
                    "tool_result_sent": bool(returned),
                    "provider": "local synthetic HTTP, no real model",
                    "transcript_persisted": False,
                },
                ensure_ascii=False,
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
