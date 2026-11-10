"""Invocation-local turn accounting. Stores identities and names, never content."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.python_runtime.sdk_event_normalizer import sdk_message_type, sdk_value
from app.shared.exceptions import DiagnosticLoopExhausted, NonRetryableExecutionError

READ_TOOLS = frozenset({"Read", "Glob", "Grep"})


@dataclass
class _Turn:
    identifiable: bool
    tools: set[str] = field(default_factory=set)
    closed: bool = False
    charged: bool = False


class TurnBudget:
    def __init__(self, maximum: int, max_tool_calls: int, tools: tuple[str, ...]) -> None:
        self.maximum = maximum
        self.exempt_tools = READ_TOOLS.intersection(tools)
        self.sdk_maximum = maximum + (max_tool_calls if self.exempt_tools else 0)
        self.failure: NonRetryableExecutionError | None = None
        self._turns: dict[str, _Turn] = {}
        self._tools: dict[str, str] = {}
        self._current: str | None = None
        self._changed = asyncio.Event()
        self.charged = 0

    def observe(self, message: Any) -> None:
        if not self.exempt_tools:
            return
        kind = sdk_message_type(message)
        if kind == "result":
            self._close_current()
            self.raise_if_failed()
            return
        if kind != "assistant":
            return
        body = sdk_value(message, "message") or message
        identifier = sdk_value(body, "id") or sdk_value(body, "message_id")
        identifiable = isinstance(identifier, str) and 0 < len(identifier) <= 256
        key = "id:" + identifier if identifiable else f"anonymous:{len(self._turns)}"
        if key not in self._turns:
            self._close_current()
            self._current = key
        turn = self._turns.setdefault(key, _Turn(identifiable=identifiable))
        blocks = sdk_value(body, "content") or []
        for block in blocks if isinstance(blocks, list) else []:
            kind = sdk_value(block, "type") or type(block).__name__
            if kind not in {"tool_use", "ToolUseBlock", "server_tool_use", "ServerToolUseBlock"}:
                continue
            name = str(sdk_value(block, "name") or "unknown")
            turn.tools.add(name)
            tool_id = sdk_value(block, "id")
            if isinstance(tool_id, str) and 0 < len(tool_id) <= 256:
                self._tools[tool_id] = name
        if not identifiable or turn.tools - self.exempt_tools or turn.closed:
            self._classify(turn)
        # A hook can arrive before this message is consumed. Wake it only after
        # classifying the entire observed block, including mixed tool requests.
        self._changed.set()
        self._changed = asyncio.Event()
        self.raise_if_failed()

    def _close_current(self) -> None:
        if self._current is not None:
            turn = self._turns[self._current]
            turn.closed = True
            self._classify(turn)

    def _classify(self, turn: _Turn) -> None:
        exempt = turn.identifiable and bool(turn.tools) and turn.tools <= self.exempt_tools
        if not exempt and not turn.charged:
            turn.charged = True
            self.charged += 1
        if self.charged > self.maximum and self.failure is None:
            self.failure = DiagnosticLoopExhausted(
                "Invocation chargeable turn limit exhausted",
                safe_message="任务已达到最大分析轮数，文件读取轮次已免计；执行已停止，不会自动重试。",
                error_code="max_turns_exhausted",
            )

    def raise_if_failed(self, *, tool_events: list[dict[str, Any]] | None = None) -> None:
        if self.failure is not None:
            if tool_events is not None:
                self.failure.tool_events = tool_events
            self.failure.diagnostics["turn_budget"] = self.snapshot()
            raise self.failure

    async def before_tool(self, name: str, tool_id: str | None) -> None:
        self.raise_if_failed()

        async def wait_for_message() -> None:
            while tool_id not in self._tools:
                await self._changed.wait()
                self.raise_if_failed()

        try:
            if not tool_id:
                raise ValueError("missing tool identity")
            await asyncio.wait_for(wait_for_message(), timeout=5)
            if self._tools[tool_id] != name:
                raise ValueError("tool identity mismatch")
        except (TimeoutError, ValueError):
            self.failure = NonRetryableExecutionError(
                "SDK tool request cannot be correlated to a model response",
                safe_message="无法核验工具请求所属的模型轮次，执行已停止，请管理员检查 Runtime。",
                error_code="runtime_turn_budget_unverifiable",
            )
        self.raise_if_failed()

    def snapshot(self) -> dict[str, int | str]:
        return {
            "policy": "file-reads-exempt-v1",
            "maximum": self.maximum,
            "sdk_maximum": self.sdk_maximum,
            "observed": len(self._turns),
            "charged": self.charged,
            "exempt": sum(t.closed and not t.charged for t in self._turns.values()),
            "pending": sum(not t.closed and not t.charged for t in self._turns.values()),
        }
