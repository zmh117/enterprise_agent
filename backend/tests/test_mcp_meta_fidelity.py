from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    UserMessage,
    create_sdk_mcp_server,
    query,
)

from app.python_runtime.claude_agent_sdk_adapter import _streaming_user_prompt
from app.python_runtime.job_sandbox import JobSandboxManager


MCP_CALL_ID = "mcp_contract_probe"
AGENT_TOOL_CALL_ID = "agent_tool_call_contract_probe"
BUSINESS_RESULT = {"business": "result"}
PLATFORM_META = {
    "enterprise-agent/mcp-call-id": MCP_CALL_ID,
    "enterprise-agent/agent-tool-call-id": AGENT_TOOL_CALL_ID,
}


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *args: Any) -> None:
        del args

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        value = json.loads(self.rfile.read(length))
        assert isinstance(value, dict)
        return value

    def _write_json(self, status: int, payload: dict[str, Any] | None = None) -> None:
        encoded = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if payload is not None:
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)


class _McpHandler(_QuietHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = self._json_body()
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            self._write_json(202)
            return
        if method == "initialize":
            result = {
                "protocolVersion": request.get("params", {}).get(
                    "protocolVersion", "2025-06-18"
                ),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "audit-contract-probe", "version": "1.0.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "meta_probe",
                        "description": "Return a business result with platform MCP metadata.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    }
                ]
            }
        elif method == "tools/call":
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(BUSINESS_RESULT, separators=(",", ":")),
                    }
                ],
                "structuredContent": BUSINESS_RESULT,
                "_meta": PLATFORM_META,
            }
        else:
            self._write_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "method not found"},
                },
            )
            return
        self._write_json(200, {"jsonrpc": "2.0", "id": request_id, "result": result})


class _ModelHandler(_QuietHandler):
    requests: list[dict[str, Any]] = []
    tool_name = "mcp__audit__meta_probe"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = self._json_body()
        type(self).requests.append(request)
        messages = request.get("messages") or []
        has_tool_result = any(
            message.get("role") == "user"
            and isinstance(message.get("content"), list)
            and any(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in message["content"]
            )
            for message in messages
            if isinstance(message, dict)
        )
        events = self._final_events(request) if has_tool_result else self._tool_events(request)
        payload = "".join(
            f"event: {event_name}\ndata: {json.dumps(data)}\n\n"
            for event_name, data in events
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @classmethod
    def _tool_events(
        cls, request: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        return [
            ("message_start", cls._message_start(request, "message-contract-tool")),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool-use-contract-probe",
                        "name": cls.tool_name,
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": "{}"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]

    @classmethod
    def _final_events(
        cls, request: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        return [
            ("message_start", cls._message_start(request, "message-contract-final")),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "done"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]

    @staticmethod
    def _message_start(request: dict[str, Any], message_id: str) -> dict[str, Any]:
        return {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": request.get("model", "contract-model"),
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }


class _BuiltinWriteModelHandler(_ModelHandler):
    tool_name = "Write"

    @classmethod
    def _tool_events(
        cls, request: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        tool_input = {
            "file_path": "outputs/runtime-write.txt",
            "content": "written by the real Claude CLI",
        }
        return [
            ("message_start", cls._message_start(request, "message-runtime-write")),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool-use-runtime-write",
                        "name": cls.tool_name,
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(tool_input),
                    },
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]


class _LocalHttpServer:
    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> _LocalHttpServer:
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _options(*, model_url: str, mcp_url: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model="contract-model",
        max_turns=2,
        permission_mode="bypassPermissions",
        allowed_tools=[_ModelHandler.tool_name],
        mcp_servers={"audit": {"type": "http", "url": f"{mcp_url}/mcp"}},
        env={
            "ANTHROPIC_BASE_URL": model_url,
            "ANTHROPIC_API_KEY": "contract-test-key",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        },
    )


def _assert_fidelity(tool_use_result: object, model_requests: list[dict[str, Any]]) -> None:
    assert isinstance(tool_use_result, dict)
    assert tool_use_result.get("_meta") == PLATFORM_META
    assert tool_use_result.get("structuredContent") == BUSINESS_RESULT
    model_visible = json.dumps(model_requests, sort_keys=True)
    assert MCP_CALL_ID not in model_visible
    assert AGENT_TOOL_CALL_ID not in model_visible


def test_python_claude_agent_sdk_preserves_remote_mcp_result_meta() -> None:
    assert version("claude-agent-sdk") == "0.2.134"
    _ModelHandler.requests = []
    with ExitStack() as stack:
        mcp = stack.enter_context(_LocalHttpServer(_McpHandler))
        model = stack.enter_context(_LocalHttpServer(_ModelHandler))

        async def collect() -> list[UserMessage]:
            messages: list[UserMessage] = []
            async for message in query(
                prompt="Call the contract probe once.",
                options=_options(model_url=model.url, mcp_url=mcp.url),
            ):
                if isinstance(message, UserMessage):
                    messages.append(message)
            return messages

        user_messages = asyncio.run(collect())

    assert len(user_messages) == 1
    _assert_fidelity(user_messages[0].tool_use_result, _ModelHandler.requests)


def test_python_claude_cli_executes_permission_checked_builtin_write(
    tmp_path: Path,
) -> None:
    _BuiltinWriteModelHandler.requests = []
    sandbox = JobSandboxManager(tmp_path / "sandboxes").create("job-runtime-write")
    permission_calls: list[str] = []

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        _context: Any,
    ) -> PermissionResultAllow:
        permission_calls.append(tool_name)
        return PermissionResultAllow(
            updated_input=sandbox.authorize_tool(tool_name, tool_input)
        )

    with _LocalHttpServer(_BuiltinWriteModelHandler) as model:

        async def collect() -> None:
            async for _message in query(
                prompt=_streaming_user_prompt("Create the requested TXT output."),
                options=ClaudeAgentOptions(
                    model="contract-model",
                    max_turns=2,
                    permission_mode="default",
                    tools=["Read", "Glob", "Grep", "Edit", "Write"],
                    allowed_tools=[],
                    disallowed_tools=[
                        "Bash",
                        "WebFetch",
                        "WebSearch",
                        "NotebookEdit",
                        "Shell",
                    ],
                    can_use_tool=can_use_tool,
                    mcp_servers={
                        "files": create_sdk_mcp_server(
                            name="runtime-write-probe",
                            version="1.0.0",
                            tools=[],
                        )
                    },
                    cwd=sandbox.path,
                    setting_sources=[],
                    skills=[],
                    env={
                        "ANTHROPIC_BASE_URL": model.url,
                        "ANTHROPIC_API_KEY": "contract-test-key",
                        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    },
                ),
            ):
                pass

        asyncio.run(collect())

    model_tools = {
        str(tool.get("name"))
        for request in _BuiltinWriteModelHandler.requests
        for tool in request.get("tools", [])
        if isinstance(tool, dict)
    }
    assert {"Read", "Glob", "Grep", "Edit", "Write"} <= model_tools
    tool_results = [
        block
        for request in _BuiltinWriteModelHandler.requests
        for message in request.get("messages", [])
        if isinstance(message, dict) and message.get("role") == "user"
        for block in message.get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert permission_calls == ["Write"], tool_results
    output = sandbox.path / "outputs/runtime-write.txt"
    assert output.exists(), tool_results
    assert output.read_text(encoding="utf-8") == (
        "written by the real Claude CLI"
    )


def test_typescript_claude_agent_sdk_preserves_remote_mcp_result_meta() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    runtime_root = repository_root / "agent-runtime"
    package = json.loads(
        (runtime_root / "node_modules/@anthropic-ai/claude-agent-sdk/package.json").read_text()
    )
    assert package["version"] == "0.3.226"
    _ModelHandler.requests = []
    with ExitStack() as stack:
        mcp = stack.enter_context(_LocalHttpServer(_McpHandler))
        model = stack.enter_context(_LocalHttpServer(_ModelHandler))
        script = f"""
import {{ query }} from '@anthropic-ai/claude-agent-sdk';
const messages = [];
for await (const message of query({{
  prompt: 'Call the contract probe once.',
  options: {{
    model: 'contract-model',
    maxTurns: 2,
    permissionMode: 'bypassPermissions',
    allowedTools: ['{_ModelHandler.tool_name}'],
    mcpServers: {{ audit: {{ type: 'http', url: '{mcp.url}/mcp' }} }},
    env: {{
      ...process.env,
      ANTHROPIC_BASE_URL: '{model.url}',
      ANTHROPIC_API_KEY: 'contract-test-key',
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1'
    }}
  }}
}})) {{
  if (message.type === 'user') messages.push(message);
}}
console.log(JSON.stringify(messages));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=runtime_root,
            env=os.environ.copy(),
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )

    user_messages = json.loads(completed.stdout)
    assert len(user_messages) == 1
    _assert_fidelity(user_messages[0]["tool_use_result"], _ModelHandler.requests)
