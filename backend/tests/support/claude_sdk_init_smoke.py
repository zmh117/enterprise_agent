"""No-prompt SDK/CLI handshake; run in the Runtime image with --network none."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, PermissionResultDeny

from app.modules.agent.domain.runtime import ToolCallBudget
from app.python_runtime.code_source_mount import CodeSourceMount
from app.python_runtime.claude_client import claude_cli_version, claude_sdk_version
from app.python_runtime.mcp_config import _code_source_hook_options


async def main() -> None:
    async def deny(*_args):
        return PermissionResultDeny(message="No tools execute in the initialization smoke")

    with tempfile.TemporaryDirectory(prefix="sdk-init-") as directory:
        tools = ["Read", "Glob", "Grep"]
        mount = CodeSourceMount(
            root=Path(directory).resolve(),
            capability={"contract": "code-source-capability/v2"},
            check=lambda _: {},
        )
        hooks = _code_source_hook_options(
            SimpleNamespace(hook_matcher=HookMatcher),
            SimpleNamespace(source_mount=mount),
            SimpleNamespace(effective_tool_names=tuple(tools)),
            ToolCallBudget(maximum=1),
        )
        options = ClaudeAgentOptions(
            cwd=directory,
            tools=tools,
            allowed_tools=[],
            setting_sources=[],
            skills=[],
            mcp_servers={},
            strict_mcp_config=True,
            permission_mode="default",
            can_use_tool=deny,
            env={
                "ANTHROPIC_API_KEY": "synthetic-unused",
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
                "CLAUDE_CONFIG_DIR": str(Path(directory) / "config"),
            },
            **hooks,
        )
        async with ClaudeSDKClient(options=options) as client:
            # No query()/prompt is sent. The CLI validates hook registration here.
            assert isinstance(await client.get_server_info(), dict)
        print(
            json.dumps(
                {
                    "initialization": "passed",
                    "sdk_version": claude_sdk_version(),
                    "cli_version": claude_cli_version(),
                    "hook_on_failure": hooks["hooks"]["PreToolUse"][0].on_failure,
                    "source_capability": "code-source-capability/v2",
                    "native_tools": tools,
                    "prompts_sent": 0,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=45))
