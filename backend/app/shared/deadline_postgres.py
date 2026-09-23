"""Psycopg opt-in cancellation, including SQL, fetch and transaction completion."""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
import math
import asyncio
import socket
from typing import Any, Self

from psycopg import Connection, pq, waiting
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from app.shared.bounded_dns import resolve

from app.shared.io_deadline import (
    CLEANUP_SECONDS,
    IODeadlineExceeded,
    POLL_SECONDS,
    current_io_deadline,
    io_deadline,
)


class DeadlineConnection(Connection):
    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: Any) -> Self:
        bounded_connect_timeout = kwargs.pop("bounded_connect_timeout", None)
        cancelled = kwargs.pop("bounded_connect_cancelled", lambda: False)
        if bounded_connect_timeout is None:
            return super().connect(conninfo, **kwargs)
        connection = None
        try:
            with io_deadline(bounded_connect_timeout, cancelled=cancelled):
                params = {
                    key: str(value)
                    for key, value in conninfo_to_dict(conninfo).items()
                    if value is not None
                }
                host = params.get("host", "")
                if host and not host.startswith("/") and not params.get("hostaddr"):
                    # Managed content config is one explicit host, not a libpq service file.
                    async def addresses() -> list[Any]:
                        async with asyncio.timeout(bounded_connect_timeout):
                            return await resolve(
                                host, int(params.get("port", "5432")), kind=socket.SOCK_STREAM
                            )

                    rows = asyncio.run(addresses())
                    addresses_list = list(dict.fromkeys(row[4][0] for row in rows))
                    params["hostaddr"] = ",".join(addresses_list)
                    params["host"] = ",".join(host for _ in addresses_list)
                connection = super().connect(make_conninfo("", **params), **kwargs)
                return connection
        except Exception:
            if connection is not None:
                connection.close()
            # The pool logs connection failures outside the request context.
            raise OSError("bounded_database_connect_unavailable") from None

    @classmethod
    def _connect_gen(cls, conninfo: str = "", **kwargs: Any) -> Any:
        budget = current_io_deadline()
        # Psycopg 3.3.4 supplies timeout here; 3.3.6 owns it in wait_conn instead.
        # Forward only the arguments supplied by the installed driver's connect().
        gen = super()._connect_gen(conninfo, **kwargs)
        if budget is None:
            return (yield from gen)
        try:
            budget.check()
            state = next(gen)
            while True:
                ready = yield state
                budget.check()
                state = gen.send(ready)
        except StopIteration as done:
            return done.value
        finally:
            gen.close()

    def wait(
        self,
        gen: Generator[Any, Any, Any],
        interval: float = 0.1,
        timeout: float | None = None,
    ) -> Any:
        # Psycopg 3.3.6 added timeout to wait(); 3.3.4 accepts neither the keyword nor callers
        # that pass it, so forward it only when the installed driver supplied one.
        timeout_argument: dict[str, float] = {} if timeout is None else {"timeout": timeout}
        budget = current_io_deadline()
        if budget is None:
            return super().wait(gen, interval, **timeout_argument)

        def guarded() -> Generator[Any, Any, Any]:
            try:
                budget.check()
                state = next(gen)
                while True:
                    ready = yield state
                    budget.check()
                    state = gen.send(ready)
            except StopIteration as done:
                budget.check()
                return done.value
            finally:
                gen.close()

        try:
            return waiting.wait(
                guarded(), self.pgconn.socket, interval=POLL_SECONDS, **timeout_argument
            )
        except IODeadlineExceeded:
            try:
                # Older libpq falls back to unbounded cancel(); never take that fallback.
                if pq.version() >= 170000:
                    self.cancel_safe(timeout=CLEANUP_SECONDS)
            except Exception:
                pass  # Do not log driver diagnostics, SQL or connection material.
            finally:
                self.close()
            raise IODeadlineExceeded() from None


@contextmanager
def postgres_deadline(connection: Any) -> Iterator[None]:
    budget = current_io_deadline()
    if budget is None:
        yield
        return
    try:
        # Server-side bounds complement socket cancellation, including a lost cancel packet.
        previous = connection.execute(
            "select name,setting from pg_settings where name in ('statement_timeout','lock_timeout')"
        ).fetchall()
        milliseconds = max(1, math.ceil(budget.timeout(120) * 1000))
        for setting in previous:
            old = int(setting["setting"])
            value = min(old, milliseconds) if old > 0 else milliseconds
            connection.execute("select set_config(%s,%s,false)", (setting["name"], str(value)))
        yield
        budget.check()
        for setting in previous:
            connection.execute(
                "select set_config(%s,%s,false)", (setting["name"], setting["setting"])
            )
    except BaseException:
        # No expired/aborted session or request-specific GUCs can return to the pool.
        connection.close()
        raise
