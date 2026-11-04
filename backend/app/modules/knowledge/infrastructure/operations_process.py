"""执行器拥有的子进程：有界输出、心跳和有序退出，不持久化原始输出。"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import selectors
import signal
import subprocess
from threading import Event
import time


@contextmanager
def exclusive_process(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def terminate_owned(process: subprocess.Popen[bytes], grace: float = 240) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def run_process(
    command: list[str],
    *,
    stop: Event,
    heartbeat: Callable[[], None],
    line: Callable[[str], None],
    timeout: float = 86400,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> int:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=cwd,
        start_new_session=True,
    )
    assert process.stdout is not None
    buffer, dropping = b"", False
    started, observed = time.monotonic(), 0.0
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                tick = time.monotonic()
                if tick - observed >= 5:
                    heartbeat()
                    observed = tick
                if stop.is_set() or tick - started > timeout:
                    terminate_owned(process)
                    return -signal.SIGTERM if stop.is_set() else -signal.SIGALRM
                for key, _ in selector.select(timeout=0.25):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer += chunk
                    while b"\n" in buffer:
                        raw, buffer = buffer.split(b"\n", 1)
                        if not dropping and len(raw) <= 16384:
                            line(raw.decode("utf-8", errors="replace"))
                        dropping = False
                    if len(buffer) > 16384:
                        buffer, dropping = b"", True
                if process.poll() is not None and not selector.get_map():
                    return process.returncode
    finally:
        terminate_owned(process)
        process.stdout.close()
