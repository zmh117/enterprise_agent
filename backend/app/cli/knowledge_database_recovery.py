"""知识采集 CLI 的数据库恢复；不在丢失 advisory lock 后原地续写。"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import signal
from threading import Event
from typing import Any, TypeVar

import psycopg
from psycopg_pool import PoolTimeout

from app.modules.knowledge.domain.normalization import ExportValidationError


T = TypeVar("T")
_DISCONNECT_MESSAGES = (
    "connection refused",
    "connection reset by peer",
    "server closed the connection unexpectedly",
    "connection is closed",
    "the connection is closed",
    "connection is bad",
    "consuming input failed",
    "ssl syscall error: eof detected",
    "timeout expired",
    "could not receive data from server",
    "could not send data to server",
    "the database system is starting up",
    "the database system is shutting down",
    "the database system is in recovery mode",
    "temporary failure in name resolution",
    "network is unreachable",
    "no route to host",
)


def database_error(error: BaseException) -> BaseException | None:
    """只沿显式 cause 追踪，清理失败不得把业务拒绝变成可重试错误。"""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (psycopg.Error, PoolTimeout)):
            return current
        current = current.__cause__
    return None


def _transient(error: BaseException, *, previously_connected: bool = False) -> bool:
    if not isinstance(error, psycopg.Error):
        return False
    state = error.sqlstate
    if state:
        return state.startswith("08") or state in {"57P01", "57P02", "57P03"}
    # libpq 在建立连接期间（含密码错误）不一定提供 SQLSTATE。
    # 仅允许已知传输诊断；不将所有 OperationalError 当作临时故障。
    diagnostic = str(error).lower()
    if any(
        message in diagnostic
        for message in (
            "password authentication failed",
            "no pg_hba.conf entry",
            "does not exist",
            "certificate verify failed",
            "server does not support ssl",
            "invalid connection option",
        )
    ):
        return False
    # Docker 重启期间服务名会短暂从 DNS 消失；只对本进程已成功校验过的
    # 固定数据库目标恢复，首次启动的拼错主机名仍失败关闭。
    if (
        previously_connected
        and isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))
        and any(
            message in diagnostic
            for message in (
                "name or service not known",
                "nodename nor servname provided, or not known",
            )
        )
    ):
        return True
    return isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError)) and any(
        message in diagnostic for message in _DISCONNECT_MESSAGES
    )


def transient_database_error(
    error: BaseException, dsn: str, *, previously_connected: bool = False
) -> bool:
    failure = database_error(error)
    if not isinstance(failure, PoolTimeout):
        return failure is not None and _transient(
            failure, previously_connected=previously_connected
        )
    # 连接池的超时会遮蔽启动时的认证/数据库名错误，单次有界直连区分，
    # 不输出底层异常、连接串或 libpq 诊断。
    try:
        with psycopg.connect(dsn, connect_timeout=5):
            return True
    except psycopg.Error as probe_error:
        return _transient(probe_error, previously_connected=previously_connected)


@dataclass
class RecoveryCheckpoint:
    run_id: str | None = None
    binding_identity: tuple[Any, ...] | None = None
    database_verified: bool = False

    def check_binding(self, binding: dict[str, Any]) -> None:
        identity = tuple(
            binding.get(key)
            for key in ("id", "source_id", "configuration_revision", "configuration_hash")
        )
        if self.binding_identity is not None and identity != self.binding_identity:
            raise ExportValidationError("knowledge_sync_configuration_changed")
        self.binding_identity = identity

    def select_run(self, run_id: str) -> None:
        if self.run_id is not None and self.run_id != run_id:
            raise ExportValidationError("knowledge_sync_run_changed")
        self.run_id = run_id


@contextmanager
def stop_signals(stop: Event) -> Iterator[None]:
    def request_stop(*_args: Any) -> None:
        stop.set()

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def recover_database(
    attempt: Callable[[], T],
    *,
    dsn: str,
    stop: Event,
    emit: Callable[[str, dict[str, Any]], None],
    prefix: str,
    previously_connected: Callable[[], bool] = lambda: False,
) -> T:
    delay = 5
    retries = 0
    while not stop.is_set():
        try:
            return attempt()
        except Exception as exc:
            if stop.is_set():
                break
            if not transient_database_error(exc, dsn, previously_connected=previously_connected()):
                raise
            retries += 1
            emit(
                f"{prefix}_database_retry_pending",
                {
                    "error_code": "knowledge_database_temporarily_unavailable",
                    "retry": retries,
                    "retry_after_seconds": delay,
                },
            )
            if stop.wait(delay):
                break
            delay = min(60, delay * 2)
    raise ExportValidationError("knowledge_sync_cancelled")
