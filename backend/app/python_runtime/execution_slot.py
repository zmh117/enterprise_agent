from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from app.modules.agent.infrastructure.runtime_pool_store import (
    LEASE_SECONDS,
    RENEW_SECONDS,
    RuntimePoolError,
)


class ExecutionSlot:
    """Admission never waits. Control endpoints never acquire this slot."""

    def __init__(self, drain_file: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._draining = False
        self.drain_file = drain_file

    @property
    def draining(self) -> bool:
        return self._draining or (self.drain_file is not None and self.drain_file.exists())

    @draining.setter
    def draining(self, value: bool) -> None:
        self._draining = value

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def acquire(self) -> None:
        if self.draining:
            raise RuntimePoolError("runtime_pool_unavailable", status=503)
        if not self._lock.acquire(blocking=False):
            raise RuntimePoolError("runtime_pool_busy", status=429)

    def release(self) -> None:
        self._lock.release()

    @contextmanager
    def probe(self) -> Iterator[None]:
        self.acquire()
        try:
            yield
        finally:
            self.release()


class ExecutionWatchdog:
    """A blocked DB renewal must not block local cancellation or containment."""

    def __init__(
        self,
        cancel: threading.Event,
        renew: Callable[[], bool],
        *,
        remaining_seconds: float,
        terminate: Callable[[int], object] = os._exit,
    ) -> None:
        self.cancel = cancel
        self.renew = renew
        self.terminate = terminate
        self.stopped = threading.Event()
        now = time.monotonic()
        self.deadline = now + max(0.0, remaining_seconds)
        # Margin covers transit and clock sampling; an expired lease cannot be
        # revived, even if the database becomes available again.
        self.lease_deadline = min(self.deadline, now + LEASE_SECONDS - RENEW_SECONDS)

    def start(self) -> None:
        for target, name in ((self._renew, "runtime-lease"), (self._watch, "runtime-watchdog")):
            threading.Thread(target=target, name=name, daemon=True).start()

    def _renew(self) -> None:
        while not self.stopped.wait(RENEW_SECONDS):
            started = time.monotonic()
            try:
                renewed = self.renew()
            except Exception:
                renewed = False
            if not renewed:
                self.cancel.set()
                return
            self.lease_deadline = min(self.deadline, started + LEASE_SECONDS - RENEW_SECONDS)

    def _watch(self) -> None:
        cancellation_started: float | None = None
        while not self.stopped.wait(0.1):
            now = time.monotonic()
            if now >= min(self.deadline, self.lease_deadline):
                self.cancel.set()
            if self.cancel.is_set():
                cancellation_started = cancellation_started or now
                if now - cancellation_started >= 10:
                    # This process must be the container's foreground process.
                    # Its exit tears down the SDK children; never release a slot
                    # just because a Python task stopped responding.
                    self.terminate(70)
                    return
