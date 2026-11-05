"""在线推理：一个工作线程、三个 FIFO 等待位置；取消不提前释放执行槽位。"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
import threading
import time
from typing import Any

from app.modules.knowledge.domain.vector_contract import MAX_RETRIEVAL_SECONDS, VectorError


class InferenceDeadline:
    def __init__(
        self, values: list[str], *, invalid_code: str = "knowledge_embedding_input_invalid"
    ) -> None:
        seconds: float = MAX_RETRIEVAL_SECONDS
        if values:
            if (
                len(values) != 1
                or len(values[0]) != 13
                or not values[0].isascii()
                or not values[0].isdigit()
                or not 10**12 <= int(values[0]) < 10**13
            ):
                raise VectorError(invalid_code)
            seconds = min(seconds, int(values[0]) / 1000 - time.time())
        self.expires = time.monotonic() + seconds
        self.cancelled = threading.Event()
        self.check()

    def remaining(self) -> float:
        return self.expires - time.monotonic()

    def check(self) -> None:
        if self.cancelled.is_set() or self.remaining() <= 0:
            raise TimeoutError


@dataclass(eq=False)
class _Inference:
    work: Callable[[], dict[str, Any]]
    deadline: InferenceDeadline
    result: asyncio.Future[dict[str, Any]]
    timing: "InferenceTiming"


@dataclass
class InferenceTiming:
    queued: float | None = None
    started: float | None = None
    finished: float | None = None

    def snapshot(self) -> dict[str, Any]:
        end = self.finished or time.monotonic()
        return {
            "queue_ms": round(((self.started or end) - self.queued) * 1000, 3)
            if self.queued is not None
            else 0.0,
            "compute_ms": round((end - self.started) * 1000, 3)
            if self.started is not None
            else 0.0,
            "state": "finished"
            if self.finished is not None
            else "running"
            if self.started is not None
            else "queued"
            if self.queued is not None
            else "not_admitted",
        }


class OnlineInferenceQueue:
    """仅由一个 ASGI 事件循环访问；线程仅执行模型并检查取消事件。"""

    def __init__(
        self, *, busy_code: str = "knowledge_embedding_busy", thread_name: str = "knowledge-embed"
    ) -> None:
        self._waiting: deque[_Inference] = deque()
        self._active: _Inference | None = None
        self._pump: asyncio.Task[None] | None = None
        self._workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name)
        self._busy_code = busy_code
        self._closed = False

    async def run(
        self,
        work: Callable[[], dict[str, Any]],
        deadline: InferenceDeadline,
        disconnected: Callable[[], Awaitable[bool]],
        *,
        timing: InferenceTiming | None = None,
    ) -> dict[str, Any]:
        deadline.check()
        if self._closed or len(self._waiting) + int(self._active is not None) >= 4:
            raise VectorError(self._busy_code)
        result: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        # 请求结束后仍安全观察异常，不打印异常字符串或业务文本。
        result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        timing = timing or InferenceTiming()
        timing.queued = time.monotonic()
        item = _Inference(work, deadline, result, timing)
        self._waiting.append(item)
        if self._pump is None:
            self._pump = asyncio.create_task(self._drain())
        stopped = asyncio.Event()
        watcher = asyncio.create_task(self._watch_disconnect(disconnected, stopped))
        try:
            async with asyncio.timeout(deadline.remaining()):
                done, _ = await asyncio.wait((result, watcher), return_when=asyncio.FIRST_COMPLETED)
                if watcher in done:
                    watcher.result()
                deadline.check()
                return result.result()
        finally:
            deadline.cancelled.set()
            if item in self._waiting:
                self._waiting.remove(item)
            result.cancel()
            stopped.set()
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher

    @staticmethod
    async def _watch_disconnect(
        disconnected: Callable[[], Awaitable[bool]], stopped: asyncio.Event
    ) -> None:
        # ASGI disconnect polling may consume cancellation inside its own cancel scope.
        # An explicit stop condition also lets that poll finish without a leaked watcher.
        while not stopped.is_set():
            if await disconnected():
                raise asyncio.CancelledError
            if not stopped.is_set():
                await asyncio.sleep(0.05)

    async def _drain(self) -> None:
        try:
            while self._waiting:
                item = self._waiting.popleft()
                self._active = item
                try:
                    item.deadline.check()
                    item.timing.started = time.monotonic()
                    value = await asyncio.get_running_loop().run_in_executor(
                        self._workers, item.work
                    )
                    item.deadline.check()
                    if not item.result.done():
                        item.result.set_result(value)
                except Exception as exc:
                    if not item.result.done():
                        item.result.set_exception(exc)
                finally:
                    if item.timing.started is not None:
                        item.timing.finished = time.monotonic()
                    # HTTP 超时或断连不会取消 pump；实际线程退出后才轮到下一项。
                    self._active = None
        finally:
            self._pump = None

    async def close(self) -> None:
        self._closed = True
        for item in self._waiting:
            item.deadline.cancelled.set()
            item.result.cancel()
        self._waiting.clear()
        if self._active is not None:
            self._active.deadline.cancelled.set()
        if self._pump is not None:
            await asyncio.shield(self._pump)
        self._workers.shutdown(wait=True)
