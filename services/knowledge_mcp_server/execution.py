"""四个真实在途槽位；超时/取消不提前释放仍在工作的线程槽位。"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import threading
import time
from typing import TypeVar

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from services.knowledge_mcp_server.errors import failure

T = TypeVar("T")


class CallControl:
    def __init__(self, *, deadline_ms: int | None = None, seconds: float = 60) -> None:
        # seconds 只供服务装配/测试收紧；不是客户端参数。
        seconds = min(60, seconds)
        wall = time.time()
        if deadline_ms is not None:
            seconds = min(seconds, deadline_ms / 1000 - wall)
        self.deadline = time.monotonic() + seconds
        self.deadline_ms = int((wall + seconds) * 1000)
        self.cancelled = threading.Event()

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def check(self) -> None:
        if self.cancelled.is_set():
            raise failure("knowledge_mcp_cancelled")
        if self.remaining() <= 0:
            raise KnowledgeGovernanceError("knowledge_search_budget_exhausted")


class BoundedCalls:
    def __init__(self) -> None:
        self._slots = threading.BoundedSemaphore(4)
        self._workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="knowledge-mcp")

    async def run(self, work: Callable[[], T], control: CallControl) -> T:
        control.check()
        if not self._slots.acquire(blocking=False):
            raise failure("knowledge_mcp_busy")

        def invoke() -> T:
            try:
                control.check()
                result = work()
                control.check()
                return result
            finally:
                self._slots.release()

        try:
            future = self._workers.submit(copy_context().run, invoke)
        except Exception:
            self._slots.release()
            raise failure("knowledge_mcp_unavailable") from None
        pending = asyncio.wrap_future(future)
        # 超时后仍观察异常，但绝不记录其字符串，也不回收工作线程拥有的槽位。
        pending.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, control.remaining())):
                return await asyncio.shield(pending)
        except TimeoutError:
            control.cancelled.set()
            raise KnowledgeGovernanceError("knowledge_search_budget_exhausted") from None
        except asyncio.CancelledError:
            control.cancelled.set()
            raise

    def close(self) -> None:
        self._workers.shutdown(wait=True)
