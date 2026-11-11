"""Renew a claimed SVN operation independently of source filesystem I/O.

The monitor may stop its own child, but never releases a writer or marks a
working copy ready. The executing thread must still wait and finish cleanup.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
import logging
import re
import subprocess
from threading import Event, Lock, Thread
import time
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.shared.exceptions import PermissionDenied
from app.shared.io_deadline import io_deadline

HEARTBEAT_INTERVAL = 3.0
HEARTBEAT_IO_TIMEOUT = 5.0
LEASE_SECONDS = 30.0
_CURRENT: ContextVar["CodeOperationHeartbeat | None"] = ContextVar(
    "code_operation_heartbeat", default=None
)
logger = logging.getLogger(__name__)


class CodeOperationHeartbeat:
    def __init__(
        self,
        *,
        operation_id: str,
        renew: Callable[[], None],
        stopped: Callable[[], bool],
        permission_error: str,
    ) -> None:
        self.operation_id, self.renew, self.stopped = operation_id, renew, stopped
        self.permission_error = permission_error
        self._done = Event()
        self._lock = Lock()
        self._error: str | None = None
        self._renewed = 0.0
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: Thread | None = None
        self._token: Token[Any] | None = None

    def __enter__(self) -> "CodeOperationHeartbeat":
        self._renew()
        self.check()
        self._thread = Thread(target=self._run, name="code-svn-heartbeat", daemon=True)
        try:
            self._thread.start()
        except Exception:
            self._thread = None
            raise CodeKnowledgeError("CODE_OPERATION_HEARTBEAT_FAILED") from None
        self._token = _CURRENT.set(self)
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _fail(self, code: str) -> None:
        safe_code = (
            code if re.fullmatch(r"[A-Za-z0-9_]{1,96}", code) else "CODE_OPERATION_HEARTBEAT_FAILED"
        )
        with self._lock:
            if self._error is not None:
                return
            self._error = safe_code
            process = self._process
        self._done.set()
        if process is not None:
            self._kill(process)
        # This is the interruption time, before potentially slow process/directory
        # cleanup. Only operation identity and a machine code enter the log.
        logger.warning(
            "Code SVN operation interrupted: id=%s code=%s", self.operation_id, safe_code
        )

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            # The owner still waits; a failed signal is never proof of quiescence.
            pass

    def _renew(self) -> None:
        started = time.monotonic()
        try:
            if self.stopped():
                raise CodeKnowledgeError("CODE_EXECUTOR_STOPPING")
            with io_deadline(HEARTBEAT_IO_TIMEOUT, cancelled=self.stopped):
                self.renew()
            with self._lock:
                # Conservative bound: the DB renewal occurred after this instant.
                self._renewed = started
        except CodeKnowledgeError as exc:
            self._fail(exc.code)
        except PermissionDenied:
            self._fail(self.permission_error)
        except Exception:
            self._fail(
                "CODE_EXECUTOR_STOPPING" if self.stopped() else "CODE_OPERATION_HEARTBEAT_FAILED"
            )

    def _run(self) -> None:
        while not self._done.wait(HEARTBEAT_INTERVAL):
            self._renew()
            with self._lock:
                if self._error is not None:
                    return

    def check(self) -> bool:
        """Cancellation polling does no database or filesystem I/O."""
        if self.stopped():
            self._fail("CODE_EXECUTOR_STOPPING")
        with self._lock:
            renewed = self._renewed
        if time.monotonic() - renewed >= LEASE_SECONDS:
            self._fail("CODE_OPERATION_LEASE_LOST")
        with self._lock:
            error = self._error
        if error:
            raise CodeKnowledgeError(error)
        return False

    def close(self) -> None:
        self._done.set()
        if self._thread is not None:
            # The DB operation has an I/O budget. Never detach a renewal that
            # could race the final transaction or another owner's recovery.
            self._thread.join()
        if self._token is not None:
            _CURRENT.reset(self._token)
            self._token = None

    def finish(self) -> None:
        """Join before the caller's atomic success / writer-to-reader transition."""
        self.close()
        self.check()

    @contextmanager
    def watch(self, process: subprocess.Popen[bytes]) -> Iterator[None]:
        with self._lock:
            self._process = process
            failed = self._error is not None
        try:
            if failed:
                self._kill(process)
            self.check()
            try:
                yield
            except Exception:
                self.check()
                raise
            else:
                self.check()
        finally:
            with self._lock:
                self._process = None


@contextmanager
def watch_svn_process(process: subprocess.Popen[bytes]) -> Iterator[None]:
    monitor = _CURRENT.get()
    if monitor is None:
        yield
    else:
        with monitor.watch(process):
            yield
