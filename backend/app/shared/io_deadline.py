"""Opt-in I/O deadline. No business authorization or database reads live here."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import time


POLL_SECONDS = 0.05
CLEANUP_SECONDS = 1.0


class IODeadlineExceeded(TimeoutError):
    def __init__(self) -> None:
        super().__init__("bounded_io_deadline_exceeded")


@dataclass(frozen=True)
class IODeadline:
    expires: float
    cancelled: Callable[[], bool]
    parent: "IODeadline | None" = None

    def expired(self) -> bool:
        return (
            time.monotonic() >= self.expires
            or self.cancelled()
            or (self.parent is not None and self.parent.expired())
        )

    def check(self) -> None:
        if self.expired():
            raise IODeadlineExceeded()

    def timeout(self, configured: float) -> float:
        self.check()
        return max(0.000001, min(configured, self.expires - time.monotonic()))


_CURRENT: ContextVar[IODeadline | None] = ContextVar("bounded_io_deadline", default=None)


def current_io_deadline() -> IODeadline | None:
    return _CURRENT.get()


def io_wait_timeout(configured: float) -> float:
    current = _CURRENT.get()
    return current.timeout(configured) if current is not None else configured


@contextmanager
def io_cleanup() -> Iterator[None]:
    """Failure audit/cleanup only; never use this to extend business reads."""
    previous = _CURRENT.set(None)
    try:
        with io_deadline(CLEANUP_SECONDS):
            yield
    finally:
        _CURRENT.reset(previous)


@contextmanager
def io_deadline(
    seconds: float, *, cancelled: Callable[[], bool] = lambda: False
) -> Iterator[IODeadline]:
    parent = _CURRENT.get()
    expires = time.monotonic() + seconds
    if parent is not None:
        expires = min(expires, parent.expires)
    budget = IODeadline(expires, cancelled, parent)
    token = _CURRENT.set(budget)
    try:
        budget.check()
        yield budget
        budget.check()
    finally:
        _CURRENT.reset(token)
