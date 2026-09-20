"""内部批量 ONES 读取的调用内预算；普通 ONES 调用保持原超时配置。"""

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
import time

from app.shared.exceptions import RetryableExecutionError
from app.shared.io_deadline import io_wait_timeout

_DEADLINE: ContextVar[float | None] = ContextVar("ones_io_deadline", default=None)


def has_ones_io_budget() -> bool:
    return _DEADLINE.get() is not None


def ones_io_timeout(configured: float) -> float:
    deadline = _DEADLINE.get()
    if deadline is None:
        return configured
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RetryableExecutionError(
            "ONES read budget exhausted",
            safe_message="ONES 可读性检查超时，请重试",
            error_code="ones_read_budget_exhausted",
        )
    return io_wait_timeout(min(configured, remaining) if configured >= 0 else remaining)


@contextmanager
def ones_io_budget(seconds: float) -> Iterator[None]:
    if not 0 < seconds <= 120:
        raise ValueError("invalid ONES read budget")
    deadline = time.monotonic() + seconds
    parent = _DEADLINE.get()
    token = _DEADLINE.set(min(parent, deadline) if parent is not None else deadline)
    try:
        yield
        ones_io_timeout(120)
    finally:
        _DEADLINE.reset(token)
