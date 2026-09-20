"""Opt-in disposable PostgreSQL cancellation tests; no platform/ONES data."""

import os
import threading
import time

import pytest
from psycopg.errors import QueryCanceled

from app.shared.database import Database
from app.shared.io_deadline import IODeadlineExceeded, io_deadline
from app.shared.deadline_postgres import DeadlineConnection
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from backend.tests.test_knowledge_io_cancellation import held_connection


@pytest.fixture
def disposable_db():
    dsn = os.environ.get("KNOWLEDGE_DEADLINE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("explicit disposable PostgreSQL DSN not supplied")
    db = Database(dsn, pool_max_size=1, pool_timeout_seconds=3)
    try:
        db.execute("select 1")
        yield db
    finally:
        db.close()


def test_postgres_pool_wait_cancels_and_reuses(disposable_db):
    with held_connection(disposable_db):
        started = time.monotonic()
        with pytest.raises(IODeadlineExceeded), io_deadline(0.1):
            disposable_db.execute("select 1")
        assert time.monotonic() - started < 0.5
    assert disposable_db.execute("select 1")


@pytest.mark.parametrize("cancelled", [False, True])
def test_postgres_query_cancels_and_connection_is_discarded(disposable_db, cancelled):
    old = disposable_db.execute_one("select pg_backend_pid() as pid")["pid"]
    signal = threading.Event()
    timer = threading.Timer(0.15, signal.set)
    timer.start()
    try:
        started = time.monotonic()
        with (
            pytest.raises((IODeadlineExceeded, QueryCanceled)),
            io_deadline(
                10 if cancelled else 0.15, cancelled=signal.is_set if cancelled else lambda: False
            ),
        ):
            disposable_db.execute("select pg_sleep(5)")
        assert time.monotonic() - started < 1.5
        new = disposable_db.execute_one("select pg_backend_pid() as pid")["pid"]
        assert new != old
        assert disposable_db.pool_snapshot().checked_out == 0
    finally:
        timer.cancel()
        timer.join()


def test_postgres_gucs_restored_and_nonknowledge_query_unaffected(disposable_db):
    original = disposable_db.execute(
        "select name,setting from pg_settings where name in ('statement_timeout','lock_timeout') order by name"
    )
    with io_deadline(0.3):
        assert disposable_db.execute("select 1")
    assert (
        disposable_db.execute(
            "select name,setting from pg_settings where name in ('statement_timeout','lock_timeout') order by name"
        )
        == original
    )
    started = time.monotonic()
    disposable_db.execute("select pg_sleep(0.35)")
    assert time.monotonic() - started >= 0.3


def test_postgres_expired_transaction_does_not_commit(disposable_db):
    disposable_db.execute("create table if not exists synthetic_deadline(value integer)")
    with pytest.raises(IODeadlineExceeded), io_deadline(0.08):
        with disposable_db.unit_of_work():
            disposable_db.execute("insert into synthetic_deadline values (1)")
            time.sleep(0.12)
    assert disposable_db.execute("select * from synthetic_deadline") == []
    assert disposable_db.current_unit_of_work is None
    assert disposable_db.pool_snapshot().checked_out == 0


def test_postgres_bounded_hostname_connect_preserves_host(disposable_db):
    params = conninfo_to_dict(disposable_db.dsn)
    # Preserve a container/service hostname; localhost would target the test runner.
    if params.get("host") in {"127.0.0.1", "::1"}:
        params["host"] = "localhost"
    expected_host = params["host"]
    with DeadlineConnection.connect(
        make_conninfo("", **params), bounded_connect_timeout=1
    ) as connection:
        assert all(host == expected_host for host in connection.info.host.split(","))
        assert connection.execute("select 1").fetchone() == (1,)


def test_postgres_lock_wait_and_nested_uow_are_bounded(disposable_db):
    disposable_db.execute("create table if not exists synthetic_deadline_lock(value integer)")
    locker = Database(disposable_db.dsn)
    try:
        with locker.unit_of_work():
            locker.execute("lock table synthetic_deadline_lock in access exclusive mode")
            started = time.monotonic()
            with pytest.raises((IODeadlineExceeded, QueryCanceled)), io_deadline(0.1):
                with disposable_db.unit_of_work():
                    with disposable_db.unit_of_work():
                        disposable_db.execute("select * from synthetic_deadline_lock")
            assert time.monotonic() - started < 1.5
        assert disposable_db.current_unit_of_work is None
        assert disposable_db.execute("select 1")
        assert disposable_db.pool_snapshot().checked_out == 0
    finally:
        locker.close()
