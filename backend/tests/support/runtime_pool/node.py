"""Test-only instrumentation around the real Runtime and deterministic Provider."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.python_runtime.executor import PythonRuntimeExecutor
from app.python_runtime.service import create_app as runtime_app


def create_app() -> Any:
    if (
        os.environ.get("APP_ENV") != "testing"
        or os.environ.get("AGENT_RUNTIME_TEST_PROVIDER_MODE") != "deterministic"
    ):
        raise RuntimeError("Pool acceptance instrumentation is test-only")
    original = PythonRuntimeExecutor._execute_fake_provider
    execute = PythonRuntimeExecutor.execute
    root = Path("/evidence")

    def record(kind: str, invocation: str) -> None:
        with (root / (os.environ["PYTHON_AGENT_RUNTIME_NODE_ID"] + ".jsonl")).open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "kind": kind,
                        "invocation_id": invocation,
                        "node_id": os.environ["PYTHON_AGENT_RUNTIME_NODE_ID"],
                        "time": time.time(),
                        "pid": os.getpid(),
                    }
                )
                + "\n"
            )

    def observed(
        self: Any, request: dict[str, Any], cancel: Any, provenance: Any, secret_context: Any
    ) -> Any:
        invocation = request["invocation_id"]
        record("provider_start", invocation)
        try:
            if "[pool:block]" in request["prompt"]["user_question"]:
                deadline = time.monotonic() + 120
                while not (root / ("release-" + invocation)).exists() and (
                    "[pool:ignore-cancel]" in request["prompt"]["user_question"]
                    or not cancel.is_set()
                ):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Acceptance release was not supplied")
                    time.sleep(0.05)
            return original(self, request, cancel, provenance, secret_context)
        finally:
            record("provider_end", invocation)

    def before_execute(self: Any, request: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        if "[pool:crash-before-sdk]" in request["prompt"]["user_question"]:
            os._exit(77)
        return execute(self, request, *args, **kwargs)

    PythonRuntimeExecutor._execute_fake_provider = observed
    PythonRuntimeExecutor.execute = before_execute
    app = runtime_app()
    app.add_middleware(DropStreamOnce)
    return app


class DropStreamOnce:
    """Drop initial execute response while its detached invocation keeps running."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        body = bytearray()
        drop_after = 0
        chunks = 0

        async def observed_receive() -> Any:
            nonlocal drop_after
            message = await receive()
            if message["type"] == "http.request" and scope.get("path") == "/internal/v1/executions":
                body.extend(message.get("body", b""))
                if not message.get("more_body"):
                    request = json.loads(body)
                    question = request.get("prompt", {}).get("user_question", "")
                    drop_after = (
                        2
                        if "[pool:drop-stream]" in question
                        else 1
                        if "[pool:drop-response]" in question
                        else 0
                    )
            return message

        async def observed_send(message: Any) -> None:
            nonlocal chunks
            if message["type"] == "http.response.body" and message.get("body"):
                chunks += 1
            if drop_after and chunks >= drop_after:
                raise RuntimeError("Synthetic acceptance connection loss after admission")
            await send(message)

        await self.app(scope, observed_receive, observed_send)
