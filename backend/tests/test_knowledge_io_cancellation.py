"""Real local blocking I/O with synthetic data only; no deployment endpoints."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import socket
import sys
import threading
import time

import pytest

from app.modules.knowledge.application.retrieval_budget import (
    RetrievalBudget,
    MAX_RETRIEVAL_SECONDS,
)
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.shared.bounded_read_http import request_bytes
from app.shared import bounded_dns
from app.shared.database import Database
from app.shared.io_deadline import IODeadlineExceeded, current_io_deadline, io_deadline
from services.knowledge_mcp_server.execution import BoundedCalls, CallControl
from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS
from backend.tests.test_knowledge_deadline import local_server


@pytest.mark.parametrize("legacy", [False, True])
def test_psycopg_connect_generator_preserves_driver_owned_arguments(monkeypatch, legacy):
    from psycopg import Connection
    from app.shared.deadline_postgres import DeadlineConnection

    def modern(cls, conninfo=""):
        assert conninfo == "synthetic"
        yield (123, 1)
        return "connected"

    def old(cls, conninfo="", *, timeout=0.0):
        assert timeout == 0.25
        return (yield from modern(cls, conninfo))

    monkeypatch.setattr(Connection, "_connect_gen", classmethod(old if legacy else modern))
    with io_deadline(1):
        generator = DeadlineConnection._connect_gen(
            "synthetic", **({"timeout": 0.25} if legacy else {})
        )
        assert next(generator) == (123, 1)
        with pytest.raises(StopIteration) as done:
            generator.send(1)
        assert done.value.value == "connected"


@contextmanager
def held_connection(database):
    acquired, release = threading.Event(), threading.Event()

    def hold():
        with database.session():
            acquired.set()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold)
        assert acquired.wait(1)
        try:
            yield
        finally:
            release.set()
            future.result(timeout=2)


def test_budget_is_120_and_cannot_expand_parent():
    assert MAX_RETRIEVAL_SECONDS == 120
    assert all("120 秒" in tool.description for tool in KNOWLEDGE_TOOL_CONTRACTS.values())
    assert 119 < CallControl(seconds=10000).remaining() <= 120
    with io_deadline(0.15) as parent:
        with io_deadline(120) as child:
            assert child.expires == parent.expires
    assert current_io_deadline() is None


def test_sqlite_pool_wait_is_bounded_and_reusable():
    db = Database("sqlite:///:memory:", pool_max_size=1, pool_timeout_seconds=3)
    try:
        with held_connection(db):
            started = time.monotonic()
            with pytest.raises(IODeadlineExceeded), io_deadline(0.08):
                db.execute("select 1")
            assert time.monotonic() - started < 0.5
        assert db.execute_one("select 7 as value") == {"value": 7}
        assert db.pool_snapshot().checked_out == 0
    finally:
        db.close()


def test_first_job_read_is_already_bounded():
    db = Database("sqlite:///:memory:", pool_max_size=1, pool_timeout_seconds=3)
    try:
        with held_connection(db):
            started = time.monotonic()
            with pytest.raises(KnowledgeGovernanceError, match="budget_exhausted"):
                RetrievalBudget(
                    lambda: db.execute_one("select 1"), deadline_ms=int(time.time() * 1000) + 80
                )
            assert time.monotonic() - started < 0.5
        assert db.execute("select 1")
    finally:
        db.close()


def test_sqlite_running_query_stops_and_next_query_succeeds():
    db = Database("sqlite:///:memory:")
    try:
        started = time.monotonic()
        with pytest.raises(IODeadlineExceeded), io_deadline(0.08):
            db.execute(
                "with recursive n(x) as (select 1 union all select x+1 from n where x<100000000) select sum(x) from n"
            )
        assert time.monotonic() - started < 0.5
        assert db.execute_one("select 8 as value") == {"value": 8}
        assert db.pool_snapshot().checked_out == 0
    finally:
        db.close()


def test_sqlite_expired_uow_rolls_back_and_clears_scope():
    db = Database("sqlite:///:memory:")
    db.execute("create table synthetic_deadline(value integer)")
    try:
        with pytest.raises(IODeadlineExceeded), io_deadline(0.05):
            with db.unit_of_work():
                db.execute("insert into synthetic_deadline values (1)")
                time.sleep(0.08)
        assert db.current_unit_of_work is None
        assert db.execute("select * from synthetic_deadline") == []
        assert db.pool_snapshot().checked_out == 0
    finally:
        db.close()


def test_dns_stall_kills_and_reaps_child_without_waiting_for_sleep(monkeypatch):
    original = asyncio.create_subprocess_exec
    children = []

    async def stall(*args, **kwargs):
        assert args[:3] == (sys.executable, "-I", "-S")
        assert kwargs["env"] == {}
        child = await original(
            sys.executable, "-I", "-S", "-c", "import time; time.sleep(5)", **kwargs
        )
        children.append(child)
        return child

    monkeypatch.setattr(bounded_dns.asyncio, "create_subprocess_exec", stall)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        request_bytes(
            "GET",
            "http://synthetic-no-lookup.invalid:9999/",
            headers={},
            content=None,
            timeout=0.15,
            max_bytes=1024,
        )
    assert time.monotonic() - started < 0.8
    assert len(children) == 1 and children[0].returncode is not None
    assert not [t for t in threading.enumerate() if t.name.startswith("asyncio_")]


def test_numeric_address_has_no_child_and_hostname_uses_os_resolution(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("numeric address must not spawn resolver")

    with monkeypatch.context() as patch:
        patch.setattr(bounded_dns.asyncio, "create_subprocess_exec", forbidden)
        with local_server() as (url, _, _):
            assert (
                request_bytes(
                    "GET", url + "/ok", headers={}, content=None, timeout=1, max_bytes=1024
                )[0]
                == 200
            )
    rows = asyncio.run(bounded_dns.resolve("localhost", 80, kind=socket.SOCK_STREAM))
    assert rows and all(row[4][0] in {"127.0.0.1", "::1"} for row in rows)
    with local_server() as (url, _, _):
        url = url.replace("127.0.0.1", "localhost")
        status, body = request_bytes(
            "GET", url + "/host", headers={}, content=None, timeout=1, max_bytes=1024
        )
        assert status == 200 and body.decode() == url.removeprefix("http://")


def test_client_cancellation_stops_blocking_pool_work_and_reclaims_all_slots():
    db = Database("sqlite:///:memory:", pool_max_size=1, pool_timeout_seconds=3)
    executor = BoundedCalls()
    finished = threading.Event()

    def work():
        try:
            db.execute("select 1")
        finally:
            finished.set()

    async def run():
        control = CallControl()
        task = asyncio.create_task(executor.run(work, control))
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(finished.wait, 0.5)
        assert await executor.run(lambda: 7, CallControl()) == 7
        for _ in range(4):
            assert executor._slots.acquire(blocking=False)
        for _ in range(4):
            executor._slots.release()

    try:
        with held_connection(db):
            asyncio.run(run())
    finally:
        executor.close()
        db.close()


def test_postgres_connect_handshake_stall_closes_socket():
    from app.shared.deadline_postgres import DeadlineConnection

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    ended = threading.Event()

    def server():
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(2)
            while connection.recv(4096):
                pass
        ended.set()

    thread = threading.Thread(target=server)
    thread.start()
    try:
        started = time.monotonic()
        with pytest.raises(OSError, match="bounded_database_connect_unavailable"):
            DeadlineConnection.connect(
                f"host=127.0.0.1 port={listener.getsockname()[1]} dbname=synthetic user=synthetic sslmode=disable",
                bounded_connect_timeout=0.15,
            )
        assert time.monotonic() - started < 0.8
        assert ended.wait(1)
    finally:
        listener.close()
        thread.join(2)
        assert not thread.is_alive()


def test_cold_content_pool_close_stops_dns_worker(monkeypatch):
    original = asyncio.create_subprocess_exec
    children = []

    async def stall(*args, **kwargs):
        child = await original(
            sys.executable, "-I", "-S", "-c", "import time; time.sleep(5)", **kwargs
        )
        children.append(child)
        return child

    monkeypatch.setattr(bounded_dns.asyncio, "create_subprocess_exec", stall)
    db = Database(
        "postgresql://synthetic@synthetic-no-lookup.invalid/synthetic",
        pool_min_size=0,
        pool_max_size=1,
        pool_timeout_seconds=3,
    )
    started = time.monotonic()
    try:
        with pytest.raises(IODeadlineExceeded), io_deadline(0.15):
            db.execute("select 1")
    finally:
        db.close()
    assert time.monotonic() - started < 1
    assert children and all(child.returncode is not None for child in children)


def test_sqlite_file_lock_wait_cancels_and_releases(tmp_path):
    dsn = f"sqlite:///{tmp_path / 'synthetic.sqlite'}"
    locked, reader = Database(dsn), Database(dsn)
    locked.execute("create table synthetic_locked(value integer)")
    try:
        with locked.session() as connection:
            connection.execute("BEGIN EXCLUSIVE")
            started = time.monotonic()
            with pytest.raises(IODeadlineExceeded), io_deadline(0.1):
                reader.execute("select * from synthetic_locked")
            assert time.monotonic() - started < 0.5
            connection.rollback()
        assert reader.execute("select * from synthetic_locked") == []
        assert reader.pool_snapshot().checked_out == 0
    finally:
        locked.close()
        reader.close()
