"""Timing-only observation of the unmodified real SDK/Provider path; no fake responses."""

from __future__ import annotations

from dataclasses import replace
import importlib.metadata
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from app.python_runtime.claude_client import ClaudeSdkClient
from app.python_runtime.service import create_app as runtime_app

ROOT = Path("/evidence")
ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def record(kind: str, invocation: str, **values: Any) -> None:
    with (ROOT / ("real-" + os.environ["PYTHON_AGENT_RUNTIME_NODE_ID"] + ".jsonl")).open(
        "a"
    ) as stream:
        stream.write(
            json.dumps(
                {
                    "kind": kind,
                    "invocation_id": invocation,
                    "node_id": os.environ["PYTHON_AGENT_RUNTIME_NODE_ID"],
                    "time": time.time(),
                    "pid": os.getpid(),
                    **values,
                }
            )
            + "\n"
        )


def create_app() -> Any:
    if (
        os.environ.get("APP_ENV") != "testing"
        or os.environ.get("AGENT_RUNTIME_TEST_PROVIDER_MODE") != "disabled"
    ):
        raise RuntimeError("Real acceptance must use the real Provider path in a test deployment")
    original = ClaudeSdkClient._run_in_sandbox_async
    executions = 0

    async def observed(self: Any, request: Any, binding: Any, api_key: str) -> Any:
        nonlocal executions
        executions += 1
        if executions > 12:
            raise RuntimeError("Bounded acceptance invocation budget exhausted")
        invocation = request.invocation_id
        sandbox = self._sandbox.get()
        assert sandbox is not None
        marker = re.search(r"RPOOL_SYNTH_[a-f0-9]+", request.context.user_question)
        canary = sandbox.path / "work" / "isolation.txt"
        assert not canary.exists()
        if marker is not None:
            canary.write_text(marker.group())
        before = not any(os.environ.get(key) for key in ENV_KEYS)
        assert before and binding.connection_revision_id == os.environ["RPOOL_MODEL_REVISION"]
        loader = self.sdk_loader
        sdk = loader()
        original_query = sdk.query

        async def query(**kwargs: Any) -> Any:
            assert Path(kwargs["options"].cwd) == sandbox.path
            record(
                "sdk_query_start",
                invocation,
                sandbox=sandbox.path.name,
                credential_revision=binding.connection_revision_id,
                credential_env_clean_before=before,
                sdk_cwd_matches_sandbox=True,
                sdk_version=importlib.metadata.version("claude-agent-sdk"),
            )
            first_assistant = True
            try:
                async for message in original_query(**kwargs):
                    kind = type(message).__name__
                    if kind == "AssistantMessage" and first_assistant:
                        record("first_assistant", invocation)
                        first_assistant = False
                    yield message
            finally:
                record("sdk_query_end", invocation)

        self.sdk_loader = lambda: replace(sdk, query=query)
        status, code = "SUCCEEDED", ""
        try:
            return await original(self, request, binding, api_key)
        except BaseException as exc:
            status, code = "FAILED", str(getattr(exc, "error_code", type(exc).__name__))
            raise
        finally:
            self.sdk_loader = loader
            usage = self.last_run_audit.get("usage", {})
            result_usage = usage.get("result") or {}
            path = sandbox.path / "work" / "isolation.txt"
            isolated = (
                path.is_file() and marker is not None and path.read_text().strip() == marker.group()
            )
            record(
                "sdk_finished",
                invocation,
                status=status,
                error_code=code,
                sandbox=sandbox.path.name,
                sandbox_file_matches=isolated,
                credential_env_clean_after=not any(os.environ.get(key) for key in ENV_KEYS),
                duration_ms=usage.get("duration_ms"),
                duration_api_ms=usage.get("duration_api_ms"),
                num_turns=usage.get("num_turns"),
                input_tokens=result_usage.get("input_tokens"),
                output_tokens=result_usage.get("output_tokens"),
                model_request_count=len(self.last_run_audit.get("model_requests", [])),
            )

    ClaudeSdkClient._run_in_sandbox_async = observed
    return runtime_app()
