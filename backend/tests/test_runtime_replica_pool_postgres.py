from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.modules.agent.infrastructure.runtime_pool_store import (
    RuntimePoolError,
    RuntimePoolStore,
    database_now,
    timestamp,
)
from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
from app.modules.job.infrastructure.execution_control import JobExecutionControl, WorkerLeaseLost
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator

DSN = os.environ.get("RUNTIME_POOL_TEST_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="requires an isolated RUNTIME_POOL_TEST_DSN")


@pytest.fixture(scope="module")
def database() -> Iterator[Database]:
    database = Database(DSN)
    Migrator(database, default_migrations_dir(), migrator_build="runtime-pool-isolated-test").run()
    yield database
    database.close()


def prepare(database: Database) -> dict[str, Any]:
    key = "rpool-" + uuid.uuid4().hex
    now = timestamp(database_now(database))
    database.execute(
        "insert into agent_session (id, session_key, created_at, updated_at) values (?, ?, ?, ?)",
        (key, key, now, now),
    )
    database.execute(
        "insert into agent_job (id, session_id, idempotency_key, status, created_at) values (?, ?, ?, 'PENDING', ?)",
        (key, key, key, now),
    )
    request: dict[str, Any] = json.loads(
        Path("contracts/agent-runtime/v1.5/golden/execution-request.json").read_text()
    )
    request.update(job_id=key, invocation_id=f"{key}.attempt-0", mcp_servers=[])
    request["request_digest"] = canonical_request_digest(request)
    RuntimePoolStore(database).prepare(
        request,
        attempt=0,
        admission_deadline_at=timestamp(database_now(database) + timedelta(seconds=3600)),
    )
    return request


def test_postgres_independent_connections_admit_exactly_one_owner(database: Database) -> None:
    request = prepare(database)
    barrier = threading.Barrier(2)

    def admit(node: str) -> bool:
        connection = Database(DSN)
        try:
            barrier.wait(timeout=10)
            return RuntimePoolStore(connection).admit(
                request["invocation_id"], request["request_digest"], node, node
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(admit, ("a", "b")))
    assert sorted(results) == [False, True]
    row = RuntimePoolStore(database).get(request["invocation_id"])
    assert row is not None and row["node_id"] in {"a", "b"}


def test_postgres_cancel_and_admission_have_one_linear_order(database: Database) -> None:
    request = prepare(database)
    barrier = threading.Barrier(2)

    def operation(cancel: bool) -> object:
        connection = Database(DSN)
        store = RuntimePoolStore(connection)
        try:
            barrier.wait(timeout=10)
            if cancel:
                return store.request_cancel(
                    request["invocation_id"], request["request_digest"], "JOB_CANCELLED"
                )
            return store.admit(request["invocation_id"], request["request_digest"], "a", "boot-a")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(operation, (True, False)))
    row = RuntimePoolStore(database).get(request["invocation_id"])
    assert row is not None and row["cancel_requested_at"] is not None
    assert results in [["cancelled", False], ["cancel_requested", True]]


def test_postgres_cancel_and_completion_cannot_commit_two_outcomes(database: Database) -> None:
    request = prepare(database)
    store = RuntimePoolStore(database)
    args = request["invocation_id"], request["request_digest"]
    store.admit(*args, "a", "boot-a")
    store.quiesce(args[0], "a", "boot-a")
    barrier = threading.Barrier(2)

    def operation(cancel: bool) -> str:
        connection = Database(DSN)
        candidate = RuntimePoolStore(connection)
        try:
            barrier.wait(timeout=10)
            if cancel:
                return candidate.request_cancel(*args, "JOB_CANCELLED")
            try:
                with connection.unit_of_work():
                    candidate.finish(*args, "a", "boot-a", "runtime_succeeded")
                return "succeeded"
            except RuntimePoolError as exc:
                assert exc.code == "runtime_cancel_requested"
                with connection.unit_of_work():
                    candidate.finish(*args, "a", "boot-a", "runtime_cancelled")
                return "cancelled"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(operation, (True, False)))
    assert results in [["already_terminal", "succeeded"], ["cancel_requested", "cancelled"]]
    assert store.require(*args)["state"] == "TERMINAL"


def test_postgres_stale_worker_result_transaction_is_rejected(database: Database) -> None:
    request = prepare(database)
    job_id = request["job_id"]
    control = JobExecutionControl(database)
    assert control.claim(job_id, "old-worker")
    database.execute(
        "update agent_job set worker_lease_until = '2000-01-01T00:00:00+00:00' where id = ?",
        (job_id,),
    )
    replacement = Database(DSN)
    try:
        assert JobExecutionControl(replacement).claim(job_id, "new-worker")
        with pytest.raises(WorkerLeaseLost), control.transaction(job_id, "old-worker", 1):
            database.execute("update agent_job set result = 'stale' where id = ?", (job_id,))
        with JobExecutionControl(replacement).transaction(job_id, "new-worker", 2):
            replacement.execute("update agent_job set result = 'current' where id = ?", (job_id,))
        assert database.execute_one("select result from agent_job where id = ?", (job_id,)) == {
            "result": "current"
        }
    finally:
        replacement.close()


def test_postgres_runtime_role_can_admit_but_cannot_prepare_or_write_jobs(
    database: Database,
) -> None:
    request = prepare(database)
    if (
        database.execute_one("select 1 from pg_roles where rolname = 'agent_runtime_reader'")
        is None
    ):
        database.execute("create role agent_runtime_reader")
    for statement in Path("backend/maintenance/agent_runtime_grants.sql").read_text().split(";"):
        if statement.strip():
            database.execute(statement)
    from app.cli.apply_agent_runtime_grants import verify_agent_runtime_grants

    database.execute("alter role agent_runtime_reader noinherit")
    verify_agent_runtime_grants(database)
    # SET LOCAL ROLE on one transaction exercises the actual role's grants,
    # including SELECT FOR UPDATE, without introducing credentials to fixtures.
    with database.unit_of_work():
        database.execute("set local role agent_runtime_reader")
        assert RuntimePoolStore(database).admit(
            request["invocation_id"], request["request_digest"], "a", "boot-a"
        )
    for statement in (
        "select * from agent_job",
        "update agent_job set status = 'FAILED'",
        "update agent_runtime_invocation set job_id = 'forged'",
        "update agent_runtime_request_snapshot set request_json = '{}'",
        "select * from rbac_role",
    ):
        with pytest.raises(Exception, match="permission denied"):
            with database.unit_of_work():
                database.execute("set local role agent_runtime_reader")
                database.execute(statement)


def test_postgres_session_head_and_late_reply_use_job_order(database: Database) -> None:
    from app.modules.job.infrastructure.repositories import AgentRepository
    from app.modules.job.infrastructure.session_repository import SessionRepository

    first = prepare(database)
    first_id = first["job_id"]
    second_id = "rpool-" + uuid.uuid4().hex
    stamp = timestamp(database_now(database))
    database.execute(
        "insert into agent_job(id,session_id,idempotency_key,status,created_at) values(?,?,?,'PENDING',?)",
        (second_id, first_id, second_id, stamp),
    )
    for job_id, seq, role, text_value in (
        (first_id, 1, "user", "prior-input"),
        (second_id, 2, "user", "current-input"),
        (first_id, 3, "assistant", "late-prior-reply"),
    ):
        message_id = f"{job_id}-{seq}"
        database.execute(
            "insert into agent_message(id,session_id,job_id,role,content,sequence_no,created_at) values(?,?,?,?,?,?,?)",
            (message_id, first_id, job_id, role, text_value, seq, stamp),
        )
        if role == "user":
            database.execute(
                "update agent_job set input_message_id = ? where id = ?", (message_id, job_id)
            )
    control = JobExecutionControl(database)
    for pending_state in ("WAITING_INPUT", "RETRY_WAIT"):
        database.execute(
            "update agent_job set status = ?, next_retry_at = '2099-01-01T00:00:00+00:00' where id = ?",
            (pending_state, first_id),
        )
        assert not control.claim(second_id, "second")
    database.execute(
        "update agent_job set status = 'PENDING', next_retry_at = null where id = ?", (first_id,)
    )
    assert not control.claim(second_id, "second")
    assert control.claim(first_id, "first")
    pool = RuntimePoolStore(database)
    pool.admit(first["invocation_id"], first["request_digest"], "a", "boot-a")
    database.execute("update agent_job set status = 'FAILED' where id = ?", (first_id,))
    assert not control.claim(second_id, "second")  # Terminal is not stopped.
    pool.quiesce(first["invocation_id"], "a", "boot-a")
    assert control.claim(second_id, "second")
    rows = SessionRepository(database).list_messages_before_job(
        AgentRepository(database).get_job(second_id)
    )
    assert [row["content"] for row in rows] == ["prior-input", "late-prior-reply"]


def test_postgres_expiry_and_finish_have_one_terminal(database: Database) -> None:
    request = prepare(database)
    store = RuntimePoolStore(database)
    args = request["invocation_id"], request["request_digest"]
    store.admit(*args, "a", "boot-a")
    store.quiesce(args[0], "a", "boot-a")
    barrier = threading.Barrier(2)

    def operation(expire: bool) -> str:
        connection = Database(DSN)
        candidate = RuntimePoolStore(connection)
        try:
            barrier.wait(timeout=10)
            if expire:
                connection.execute(
                    "update agent_runtime_invocation set lease_until = '2000-01-01T00:00:00+00:00' where invocation_id = ? and state = 'RUNNING'",
                    (args[0],),
                )
                candidate.expire()
                return "scanned"
            try:
                with connection.unit_of_work():
                    candidate.finish(*args, "a", "boot-a", "runtime_succeeded")
                return "succeeded"
            except RuntimePoolError as exc:
                assert exc.code == "runtime_execution_lease_lost"
                return "fenced"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(operation, (True, False)))
    row = store.require(*args)
    assert row["state"] == "TERMINAL"
    assert row["terminal_code"] == (
        "runtime_succeeded" if results[1] == "succeeded" else "runtime_invocation_outcome_unknown"
    )


def test_postgres_snapshot_retention_preserves_execution_identity(database: Database) -> None:
    request = prepare(database)
    store = RuntimePoolStore(database)
    args = request["invocation_id"], request["request_digest"]
    assert store.admit(*args, "a", "boot-a")
    assert not store.prune_body(args[0])
    store.quiesce(args[0], "a", "boot-a")
    with database.unit_of_work():
        store.finish(*args, "a", "boot-a", "runtime_succeeded")
    assert not store.prune_body(args[0])
    database.execute("update agent_job set status = 'SUCCEEDED' where id = ?", (request["job_id"],))
    assert store.prune_body(args[0])
    assert not store.admit(*args, "b", "boot-b")
    with pytest.raises(RuntimePoolError, match="recovery_expired"):
        store.request(args[0])
