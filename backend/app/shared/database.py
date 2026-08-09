from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Iterable
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from queue import Empty, LifoQueue
from typing import Any, Callable, Iterator, Literal, ParamSpec, Protocol, TypeVar, cast


DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 10
DEFAULT_POOL_TIMEOUT_SECONDS = 10.0

P = ParamSpec("P")
R = TypeVar("R")
_ACTIVE_UNIT_OF_WORK_DEPTH: ContextVar[int] = ContextVar(
    "active_database_unit_of_work_depth",
    default=0,
)


class ExternalIOInUnitOfWorkError(RuntimeError):
    """Raised before external I/O can run inside a local DB transaction."""


def assert_external_io_allowed(operation: str) -> None:
    if _ACTIVE_UNIT_OF_WORK_DEPTH.get() > 0:
        raise ExternalIOInUnitOfWorkError(
            f"External I/O is not allowed inside a database Unit of Work: {operation}"
        )


@dataclass(frozen=True)
class PoolSnapshot:
    opened: int
    idle: int
    checked_out: int
    max_size: int


class _ConnectionPool(Protocol):
    def connection(self) -> AbstractContextManager[Any]: ...

    def close(self) -> None: ...

    def snapshot(self) -> PoolSnapshot: ...


class _SQLiteConnectionPool:
    def __init__(
        self,
        dsn: str,
        *,
        min_size: int,
        max_size: int,
        timeout_seconds: float,
    ) -> None:
        raw_path = dsn.removeprefix("sqlite:///")
        self._is_memory = raw_path == ":memory:"
        self._path = (
            f"file:enterprise_agent_{uuid.uuid4().hex}?mode=memory&cache=shared"
            if self._is_memory
            else raw_path
        )
        self._timeout_seconds = timeout_seconds
        self._max_size = max_size
        self._idle: LifoQueue[sqlite3.Connection] = LifoQueue(maxsize=max_size)
        self._lock = threading.Lock()
        self._opened = 0
        self._checked_out = 0
        self._closed = False
        for _ in range(min_size):
            self._idle.put_nowait(self._open_connection())
            self._opened += 1

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            check_same_thread=False,
            timeout=self._timeout_seconds,
            uri=self._is_memory,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {max(1, int(self._timeout_seconds * 1000))}")
        return connection

    def _acquire(self) -> sqlite3.Connection:
        try:
            connection = self._idle.get_nowait()
        except Empty:
            create = False
            with self._lock:
                if self._closed:
                    raise RuntimeError("Database connection pool is closed")
                if self._opened < self._max_size:
                    self._opened += 1
                    create = True
            if create:
                try:
                    connection = self._open_connection()
                except Exception:
                    with self._lock:
                        self._opened -= 1
                    raise
            else:
                try:
                    connection = self._idle.get(timeout=self._timeout_seconds)
                except Empty as exc:
                    raise TimeoutError("Timed out waiting for a database connection") from exc
        with self._lock:
            if self._closed:
                connection.close()
                self._opened -= 1
                raise RuntimeError("Database connection pool is closed")
            self._checked_out += 1
        return connection

    def _release(self, connection: sqlite3.Connection) -> None:
        try:
            if connection.in_transaction:
                connection.rollback()
        finally:
            with self._lock:
                self._checked_out -= 1
                closed = self._closed
                if closed:
                    self._opened -= 1
            if closed:
                connection.close()
            else:
                self._idle.put_nowait(connection)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._acquire()
        try:
            yield connection
        finally:
            self._release(connection)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        while True:
            try:
                connection = self._idle.get_nowait()
            except Empty:
                break
            connection.close()
            with self._lock:
                self._opened -= 1

    def snapshot(self) -> PoolSnapshot:
        with self._lock:
            return PoolSnapshot(
                opened=self._opened,
                idle=self._idle.qsize(),
                checked_out=self._checked_out,
                max_size=self._max_size,
            )


class _PostgresConnectionPool:
    def __init__(
        self,
        dsn: str,
        *,
        min_size: int,
        max_size: int,
        timeout_seconds: float,
    ) -> None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "psycopg with the pool extra is required for PostgreSQL connections"
            ) from exc
        self._timeout_seconds = timeout_seconds
        self._max_size = max_size
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_seconds,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
            },
            open=False,
            name=f"enterprise-agent-{uuid.uuid4().hex[:8]}",
        )
        self._open_lock = threading.Lock()
        self._opened = False

    def _ensure_open(self) -> None:
        if self._opened:
            return
        with self._open_lock:
            if self._opened:
                return
            self._pool.open(wait=True, timeout=self._timeout_seconds)
            self._opened = True

    @contextmanager
    def connection(self) -> Iterator[Any]:
        self._ensure_open()
        with self._pool.connection(timeout=self._timeout_seconds) as connection:
            yield connection

    def close(self) -> None:
        if self._opened:
            self._pool.close(timeout=self._timeout_seconds)
            self._opened = False

    def snapshot(self) -> PoolSnapshot:
        if not self._opened:
            return PoolSnapshot(
                opened=0,
                idle=0,
                checked_out=0,
                max_size=self._max_size,
            )
        stats = self._pool.get_stats()
        opened = int(stats.get("pool_size", 0))
        idle = int(stats.get("pool_available", 0))
        return PoolSnapshot(
            opened=opened,
            idle=idle,
            checked_out=max(0, opened - idle),
            max_size=int(stats.get("pool_max", self._max_size)),
        )


@dataclass(frozen=True)
class _ConnectionScope:
    connection: Any


class UnitOfWork:
    """One operation-scoped database transaction.

    Nested units use savepoints on the parent's connection. The active unit is
    held in a ContextVar, so concurrent requests and worker threads never share
    transaction state.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self.connection: Any | None = None
        self._parent: UnitOfWork | None = None
        self._savepoint = ""
        self._session_manager: AbstractContextManager[Any] | None = None
        self._token: Token[UnitOfWork | None] | None = None
        self._external_io_token: Token[int] | None = None
        self._entered = False

    def __enter__(self) -> UnitOfWork:
        if self._entered:
            raise RuntimeError("Unit of Work cannot be entered more than once")
        self._entered = True
        self._parent = self.database.current_unit_of_work
        self._session_manager = self.database.session()
        self.connection = self._session_manager.__enter__()
        if self.connection is None:
            raise RuntimeError("Database session returned no connection")
        connection = self.connection
        assert connection is not None
        try:
            if self._parent is None:
                connection.execute(
                    "BEGIN IMMEDIATE" if self.database.engine == "sqlite" else "BEGIN"
                )
            else:
                if connection is not self._parent.connection:
                    raise RuntimeError("Nested Unit of Work must reuse the parent connection")
                self._savepoint = f"uow_{uuid.uuid4().hex}"
                assert connection is not None
                connection.execute(f"SAVEPOINT {self._savepoint}")
            self._token = self.database._active_uow.set(self)
            self._external_io_token = _ACTIVE_UNIT_OF_WORK_DEPTH.set(
                _ACTIVE_UNIT_OF_WORK_DEPTH.get() + 1
            )
            return self
        except Exception:
            self._session_manager.__exit__(None, None, None)
            self._session_manager = None
            self.connection = None
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> Literal[False]:
        if self.connection is None or self._token is None or self._external_io_token is None:
            raise RuntimeError("Unit of Work was not entered")
        try:
            if self._parent is None:
                if exc_type is None:
                    self.connection.commit()
                else:
                    self.connection.rollback()
            elif exc_type is None:
                self.connection.execute(f"RELEASE SAVEPOINT {self._savepoint}")
            else:
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint}")
                self.connection.execute(f"RELEASE SAVEPOINT {self._savepoint}")
        finally:
            _ACTIVE_UNIT_OF_WORK_DEPTH.reset(self._external_io_token)
            self.database._active_uow.reset(self._token)
            assert self._session_manager is not None
            self._session_manager.__exit__(exc_type, exc_value, traceback)
            self._session_manager = None
            self.connection = None
        return False


class Database:
    def __init__(
        self,
        dsn: str,
        *,
        pool_min_size: int = DEFAULT_POOL_MIN_SIZE,
        pool_max_size: int = DEFAULT_POOL_MAX_SIZE,
        pool_timeout_seconds: float = DEFAULT_POOL_TIMEOUT_SECONDS,
    ) -> None:
        if pool_min_size < 0:
            raise ValueError("pool_min_size must be non-negative")
        if pool_max_size < 1 or pool_min_size > pool_max_size:
            raise ValueError("pool_max_size must be positive and >= pool_min_size")
        if pool_timeout_seconds <= 0:
            raise ValueError("pool_timeout_seconds must be positive")
        self.dsn = dsn
        self.engine = "sqlite" if dsn.startswith("sqlite://") else "postgres"
        self._pool_min_size = pool_min_size
        self._pool_max_size = pool_max_size
        self._pool_timeout_seconds = pool_timeout_seconds
        self._pool: _ConnectionPool | None = None
        self._pool_lock = threading.Lock()
        self._closed = False
        self._scope: ContextVar[_ConnectionScope | None] = ContextVar(
            f"database_scope_{id(self)}",
            default=None,
        )
        self._active_uow: ContextVar[UnitOfWork | None] = ContextVar(
            f"database_uow_{id(self)}",
            default=None,
        )

    def _connection_pool(self) -> _ConnectionPool:
        if self._closed:
            raise RuntimeError("Database is closed")
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                pool_type = (
                    _SQLiteConnectionPool if self.engine == "sqlite" else _PostgresConnectionPool
                )
                self._pool = pool_type(
                    self.dsn,
                    min_size=self._pool_min_size,
                    max_size=self._pool_max_size,
                    timeout_seconds=self._pool_timeout_seconds,
                )
        return self._pool

    @property
    def current_unit_of_work(self) -> UnitOfWork | None:
        return self._active_uow.get()

    def pool_snapshot(self) -> PoolSnapshot:
        if self._pool is None:
            return PoolSnapshot(
                opened=0,
                idle=0,
                checked_out=0,
                max_size=self._pool_max_size,
            )
        return self._pool.snapshot()

    @contextmanager
    def session(self) -> Iterator[Any]:
        current = self._scope.get()
        if current is not None:
            yield current.connection
            return
        with self._connection_pool().connection() as connection:
            token = self._scope.set(_ConnectionScope(connection=connection))
            try:
                yield connection
            finally:
                self._scope.reset(token)

    def unit_of_work(self) -> UnitOfWork:
        return UnitOfWork(self)

    def close(self) -> None:
        with self._pool_lock:
            if self._closed:
                return
            self._closed = True
            pool = self._pool
        if pool is not None:
            pool.close()

    def ping(self) -> bool:
        try:
            self.execute("select 1")
            return True
        except Exception:
            return False

    def execute(
        self,
        sql: str,
        params: Iterable[Any] = (),
    ) -> list[dict[str, Any]]:
        with self.session() as connection:
            implicit = self.current_unit_of_work is None
            try:
                translated = self._translate_placeholders(sql)
                cursor = connection.execute(translated, tuple(params))
                try:
                    rows = cursor.fetchall() if cursor.description else []
                finally:
                    cursor.close()
                if implicit and self.engine == "sqlite":
                    connection.commit()
                return [dict(row) for row in rows]
            except Exception:
                if implicit:
                    connection.rollback()
                raise

    def execute_one(
        self,
        sql: str,
        params: Iterable[Any] = (),
    ) -> dict[str, Any] | None:
        rows = self.execute(sql, params)
        return rows[0] if rows else None

    def execute_script(
        self,
        script: str,
        *,
        ignore_existing_errors: bool = True,
    ) -> None:
        with self.session() as connection:
            implicit = self.current_unit_of_work is None
            for statement in self._split_statements(script):
                prepared_statement = self._statement_for_engine(statement)
                if prepared_statement is None:
                    continue
                if self.engine == "sqlite" and self._is_postgres_comment_statement(
                    prepared_statement
                ):
                    continue
                try:
                    cursor = connection.execute(prepared_statement)
                    cursor.close()
                    if implicit and self.engine == "sqlite":
                        connection.commit()
                except Exception as exc:
                    if not ignore_existing_errors or not self._is_ignorable_migration_error(
                        exc,
                        statement=prepared_statement,
                    ):
                        if implicit:
                            connection.rollback()
                        raise
                    if implicit:
                        connection.rollback()

    def run_migrations(self, migrations_dir: Path) -> None:
        for path in sorted(migrations_dir.glob("*.sql")):
            self.execute_script(path.read_text())

    def _translate_placeholders(self, sql: str) -> str:
        if self.engine == "postgres":
            return sql.replace("?", "%s")
        return sql

    def _split_statements(self, script: str) -> list[str]:
        return [statement.strip() for statement in script.split(";") if statement.strip()]

    def _is_ignorable_migration_error(
        self,
        exc: Exception,
        *,
        statement: str = "",
    ) -> bool:
        message = str(exc).lower()
        normalized_statement = " ".join(statement.lower().split())
        repeated_column_rename = (
            normalized_statement.startswith("alter table ")
            and " rename column " in normalized_statement
            and " to " in normalized_statement
            and ("no such column" in message or "does not exist" in message)
        )
        return (
            "duplicate column" in message
            or "already exists" in message
            or "column" in message
            and "already" in message
            or repeated_column_rename
        )

    def _is_postgres_comment_statement(self, statement: str) -> bool:
        return statement.lstrip().upper().startswith("COMMENT ON ")

    def _statement_for_engine(self, statement: str) -> str | None:
        if "-- sqlite-only" in statement:
            return statement if self.engine == "sqlite" else None
        if "-- postgres-only" in statement:
            return statement if self.engine == "postgres" else None
        return statement


class _DatabaseRepositoryOwner(Protocol):
    @property
    def database(self) -> Database: ...


class _UnitOfWorkOwner(Protocol):
    @property
    def repository(self) -> _DatabaseRepositoryOwner: ...


def operation_unit_of_work(
    database_getter: Callable[[_UnitOfWorkOwner], Database],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Declare a synchronous service/repository method as one local UoW."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if not args:
                raise RuntimeError("Unit of Work method requires an owner")
            owner = cast(_UnitOfWorkOwner, args[0])
            database = database_getter(owner)
            with database.unit_of_work():
                return function(*args, **kwargs)

        return wrapped

    return decorate


def default_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"
