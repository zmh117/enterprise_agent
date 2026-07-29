from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.shared.database import (
    Database,
    ExternalIOInUnitOfWorkError,
    assert_external_io_allowed,
    operation_unit_of_work,
)


def test_unit_of_work_commits_and_returns_connection() -> None:
    database = Database(
        "sqlite:///:memory:",
        pool_min_size=1,
        pool_max_size=2,
    )
    try:
        database.execute(
            "create table example (id integer primary key, value text not null)"
        )

        with database.unit_of_work():
            database.execute(
                "insert into example (id, value) values (?, ?)",
                (1, "committed"),
            )
            assert database.current_unit_of_work is not None
            assert database.pool_snapshot().checked_out == 1

        assert database.current_unit_of_work is None
        assert database.pool_snapshot().checked_out == 0
        assert database.execute_one(
            "select value from example where id = ?",
            (1,),
        ) == {"value": "committed"}
    finally:
        database.close()


def test_unit_of_work_rolls_back_and_returns_connection_after_error() -> None:
    database = Database("sqlite:///:memory:")
    try:
        database.execute(
            "create table example (id integer primary key, value text not null)"
        )

        with pytest.raises(RuntimeError, match="force rollback"):
            with database.unit_of_work():
                database.execute(
                    "insert into example (id, value) values (?, ?)",
                    (1, "rolled-back"),
                )
                raise RuntimeError("force rollback")

        assert database.execute_one(
            "select count(*) as count from example"
        ) == {"count": 0}
        assert database.pool_snapshot().checked_out == 0
    finally:
        database.close()


def test_nested_unit_of_work_uses_savepoint() -> None:
    database = Database("sqlite:///:memory:")
    try:
        database.execute(
            "create table example (id integer primary key, value text not null)"
        )

        with database.unit_of_work():
            database.execute(
                "insert into example (id, value) values (?, ?)",
                (1, "outer"),
            )
            with pytest.raises(RuntimeError, match="nested rollback"):
                with database.unit_of_work():
                    database.execute(
                        "insert into example (id, value) values (?, ?)",
                        (2, "nested"),
                    )
                    raise RuntimeError("nested rollback")
            assert database.execute_one(
                "select count(*) as count from example"
            ) == {"count": 1}

        assert database.execute(
            "select id, value from example order by id"
        ) == [{"id": 1, "value": "outer"}]
    finally:
        database.close()


def test_operation_unit_of_work_rolls_back_multi_statement_service() -> None:
    database = Database("sqlite:///:memory:")

    class ExampleService:
        def __init__(self, value: Database) -> None:
            self.database = value

        @operation_unit_of_work(lambda service: service.database)
        def fail_after_two_writes(self) -> None:
            self.database.execute(
                "insert into example (id, value) values (?, ?)",
                (1, "first"),
            )
            self.database.execute(
                "insert into example (id, value) values (?, ?)",
                (2, "second"),
            )
            raise RuntimeError("operation failed")

    try:
        database.execute(
            "create table example (id integer primary key, value text not null)"
        )

        with pytest.raises(RuntimeError, match="operation failed"):
            ExampleService(database).fail_after_two_writes()

        assert database.execute_one(
            "select count(*) as count from example"
        ) == {"count": 0}
        assert database.pool_snapshot().checked_out == 0
    finally:
        database.close()


def test_external_io_guard_rejects_active_uow_and_resets_after_exit() -> None:
    database = Database("sqlite:///:memory:")
    try:
        assert_external_io_allowed("test.before")
        with database.unit_of_work():
            with pytest.raises(
                ExternalIOInUnitOfWorkError,
                match="test.blocked",
            ):
                assert_external_io_allowed("test.blocked")
        assert_external_io_allowed("test.after")
    finally:
        database.close()


def test_pool_leases_distinct_connections_to_concurrent_operations(
    tmp_path: Path,
) -> None:
    database = Database(
        f"sqlite:///{tmp_path / 'pool.db'}",
        pool_min_size=1,
        pool_max_size=2,
    )
    barrier = threading.Barrier(3)
    connection_ids: list[int] = []
    errors: list[BaseException] = []

    def hold_connection() -> None:
        try:
            with database.session() as connection:
                connection_ids.append(id(connection))
                barrier.wait(timeout=5)
                barrier.wait(timeout=5)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=hold_connection)
    second = threading.Thread(target=hold_connection)
    try:
        first.start()
        second.start()
        barrier.wait(timeout=5)
        snapshot = database.pool_snapshot()
        assert snapshot.checked_out == 2
        assert len(set(connection_ids)) == 2
        barrier.wait(timeout=5)
        first.join(timeout=5)
        second.join(timeout=5)

        assert errors == []
        assert database.pool_snapshot().checked_out == 0
    finally:
        if first.is_alive() or second.is_alive():
            barrier.abort()
        first.join(timeout=5)
        second.join(timeout=5)
        database.close()
