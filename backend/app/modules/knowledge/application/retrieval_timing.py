"""请求内安全计时；只投影固定阶段、随机标识与数字，不接收业务文本。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import time
from typing import Any
from uuid import uuid4

STAGES = frozenset(
    {"access_check", "resource", "embedding", "vector_search", "rerank", "readability", "response"}
)
_CURRENT: ContextVar["RetrievalTiming | None"] = ContextVar("knowledge_timing", default=None)


class RetrievalTiming:
    def __init__(self, deadline_ms: int, *, source: str = "call_limit") -> None:
        self.request_id = uuid4().hex
        self.started = time.monotonic()
        self.deadline_ms, self.deadline_source = deadline_ms, source
        self.entry_budget_ms = max(0, deadline_ms - int(time.time() * 1000))
        self.budget_after_auth_ms: int | None = None
        self.dispatch_wait_ms = 0
        self.stage_ms: dict[str, float] = {}
        self.stopped_stage: str | None = None
        self.rerank_timing: dict[str, Any] | None = None

    def limit(self, deadline_ms: int, source: str) -> None:
        if source not in {"call_limit", "job", "upstream", "parent"}:
            raise ValueError("Invalid deadline source")
        if deadline_ms < self.deadline_ms:
            self.deadline_ms, self.deadline_source = deadline_ms, source

    def observe_rerank(self, value: Any) -> None:
        if (
            not isinstance(value, dict)
            or set(value) != {"queue_ms", "compute_ms", "state"}
            or not isinstance(value["state"], str)
            or value["state"] not in {"not_admitted", "queued", "running", "finished"}
        ):
            return
        for name in ("queue_ms", "compute_ms"):
            number = value[name]
            if type(number) not in (float, int) or not 0 <= number <= 3_600_000:
                return
        self.rerank_timing = dict(value)

    def snapshot(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "deadline_ms": self.deadline_ms,
            "deadline_source": self.deadline_source,
            "entry_budget_ms": self.entry_budget_ms,
            "budget_after_auth_ms": self.budget_after_auth_ms,
            "dispatch_wait_ms": self.dispatch_wait_ms,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000, 3),
            "stage_ms": {name: round(value, 3) for name, value in self.stage_ms.items()},
            "stopped_stage": self.stopped_stage,
            "rerank": self.rerank_timing,
        }


def current_timing() -> RetrievalTiming | None:
    return _CURRENT.get()


@contextmanager
def retrieval_timing(timing: RetrievalTiming) -> Iterator[None]:
    previous = _CURRENT.set(timing)
    try:
        yield
    finally:
        _CURRENT.reset(previous)


@contextmanager
def stage(name: str) -> Iterator[None]:
    if name not in STAGES:
        raise ValueError("Invalid retrieval stage")
    timing = current_timing()
    started = time.monotonic()
    try:
        yield
    except BaseException:
        if timing is not None and timing.stopped_stage is None:
            timing.stopped_stage = name
        raise
    finally:
        if timing is not None:
            timing.stage_ms[name] = (
                timing.stage_ms.get(name, 0.0) + (time.monotonic() - started) * 1000
            )
