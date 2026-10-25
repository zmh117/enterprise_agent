from __future__ import annotations

import json
import threading
from collections.abc import Iterator
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
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.infrastructure.execution_control import JobExecutionControl, WorkerLeaseLost
from app.python_runtime.execution_slot import ExecutionSlot
from backend.tests.support.runtime import container


@pytest.fixture
def prepared() -> Iterator[tuple[RuntimePoolStore, dict[str, Any]]]:
    runtime = container()
    try:
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="pool-synthetic",
                requester_id="user_local_admin",
                user_message="synthetic pool test",
                source_channel="debug_api",
            )
        )
        request = json.loads(
            Path("contracts/agent-runtime/v1.5/golden/execution-request.json").read_text()
        )
        request.update(job_id=job.id, invocation_id=f"{job.id}.attempt-0", mcp_servers=[])
        request["request_digest"] = canonical_request_digest(request)
        store = RuntimePoolStore(runtime.database)
        store.prepare(
            request,
            attempt=0,
            admission_deadline_at=timestamp(
                database_now(runtime.database) + timedelta(seconds=3600),
            ),
        )
        yield store, request
    finally:
        runtime.database.close()


def test_admission_has_one_owner_and_cannot_transfer(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    args = request["invocation_id"], request["request_digest"]
    assert store.admit(*args, "a", "boot-a")
    assert not store.admit(*args, "b", "boot-b")
    row = store.require(*args)
    assert (row["node_id"], row["instance_id"], row["state"]) == ("a", "boot-a", "RUNNING")
    with pytest.raises(RuntimePoolError, match="owner_mismatch"):
        store.renew(*args, "b", "boot-b")


def test_cancel_before_admission_does_not_start_execution(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    args = request["invocation_id"], request["request_digest"]
    assert store.request_cancel(*args, "JOB_CANCELLED") == "cancelled"
    assert not store.admit(*args, "a", "boot-a")
    row = store.require(*args)
    assert row["accepted_at"] is None
    assert row["execution_quiesced_at"] is not None
    assert store.request_cancel(*args, "JOB_CANCELLED") == "already_terminal"


def test_expired_runtime_lease_is_not_revived_and_does_not_prove_stop(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    args = request["invocation_id"], request["request_digest"]
    store.admit(*args, "a", "boot-a")
    store.database.execute(
        "update agent_runtime_invocation set lease_until = ?", ("2000-01-01T00:00:00+00:00",)
    )
    with pytest.raises(RuntimePoolError, match="lease_lost"):
        store.renew(*args, "a", "boot-a")
    assert store.expire() == 1
    assert store.require(*args)["execution_quiesced_at"] is None
    assert not store.admit(*args, "b", "boot-b")
    store.quiesce(args[0], "b", "boot-b")
    assert store.require(*args)["execution_quiesced_at"] is None
    store.quiesce(args[0], "a", "boot-a")
    assert store.require(*args)["execution_quiesced_at"] is not None


def test_cancellation_wins_over_success_and_terminal_cannot_change(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    args = request["invocation_id"], request["request_digest"]
    store.admit(*args, "a", "boot-a")
    assert store.request_cancel(*args, "JOB_CANCELLED") == "cancel_requested"
    store.quiesce(args[0], "a", "boot-a")
    with store.database.unit_of_work():
        with pytest.raises(RuntimePoolError, match="cancel_requested"):
            store.finish(*args, "a", "boot-a", "runtime_succeeded")
        store.finish(*args, "a", "boot-a", "runtime_cancelled")
    with store.database.unit_of_work(), pytest.raises(RuntimePoolError, match="lease_lost"):
        store.finish(*args, "a", "boot-a", "runtime_succeeded")


def test_snapshot_digest_tampering_and_active_retention(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    assert store.request(request["invocation_id"]) == request
    assert not store.prune_body(request["invocation_id"])
    tampered = {**request, "app_user_id": "different-user"}
    store.database.execute(
        "update agent_runtime_request_snapshot set request_json = ?", (json.dumps(tampered),)
    )
    with pytest.raises(ValueError, match="digest"):
        store.request(request["invocation_id"])


def test_worker_redelivery_and_stale_commit_are_fenced(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    control = JobExecutionControl(store.database)
    job_id = request["job_id"]
    assert control.claim(job_id, "worker-a")
    assert not control.claim(job_id, "worker-b")
    store.database.execute(
        "update agent_job set worker_lease_until = ? where id = ?",
        ("2000-01-01T00:00:00+00:00", job_id),
    )
    assert control.claim(job_id, "worker-b")
    with pytest.raises(WorkerLeaseLost):
        with control.transaction(job_id, "worker-a", 1):
            pytest.fail("stale worker entered result transaction")
    with control.transaction(job_id, "worker-b", 2):
        pass


def test_slot_rejects_busy_without_waiting_and_probe_shares_capacity() -> None:
    slot = ExecutionSlot()
    slot.acquire()
    with pytest.raises(RuntimePoolError, match="busy"):
        with slot.probe():
            pytest.fail("probe acquired occupied execution slot")
    slot.release()
    with slot.probe():
        assert slot.busy
    assert not slot.busy
    slot.draining = True
    with pytest.raises(RuntimePoolError, match="unavailable"):
        slot.acquire()


def test_sqlite_admission_race_is_only_a_local_regression(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    # PostgreSQL independent-connection acceptance is separate from this test.
    store, request = prepared
    barrier = threading.Barrier(3)
    results: list[bool] = []

    def admit(node: str) -> None:
        barrier.wait()
        results.append(store.admit(request["invocation_id"], request["request_digest"], node, node))

    threads = [threading.Thread(target=admit, args=(node,)) for node in ("a", "b")]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert sorted(results) == [False, True]


def test_expired_unpublished_job_converges_without_a_worker() -> None:
    runtime = container()
    try:
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="never-published",
                requester_id="user_local_admin",
                user_message="synthetic",
                source_channel="debug_api",
            )
        )
        runtime.database.execute(
            "update agent_job set admission_deadline_at = '2000-01-01T00:00:00+00:00' where id = ?",
            (job.id,),
        )
        runtime.job_dispatcher.publish_pending()
        terminal = runtime.agent_repository.get_job(job.id)
        assert terminal.status.value == "TIMEOUT"
        assert terminal.last_error_code == "runtime_admission_timeout"
        assert terminal.retry_count == 0
        assert (
            runtime.database.execute_one(
                "select 1 from agent_runtime_invocation where job_id = ?", (job.id,)
            )
            is None
        )
        assert (
            runtime.database.execute_one(
                "select count(*) as n from delivery_outbox where job_id = ?", (job.id,)
            )["n"]
            == 1
        )
    finally:
        runtime.database.close()


def test_defer_transaction_failure_keeps_worker_and_outbox_atomic(
    prepared: tuple[RuntimePoolStore, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, request = prepared
    control = JobExecutionControl(store.database)
    assert control.claim(request["job_id"], "worker-a")

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic dispatch persistence failure")

    monkeypatch.setattr(control, "rearm", fail)
    with pytest.raises(RuntimeError, match="persistence failure"):
        control.defer(request["job_id"], "worker-a", 1, reason="runtime_capacity")
    row = store.database.execute_one(
        "select status, locked_by from agent_job where id = ?", (request["job_id"],)
    )
    assert row == {"status": "RUNNING", "locked_by": "worker-a"}


def test_late_admission_and_defer_keep_one_identity(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    control = JobExecutionControl(store.database)
    job = request["job_id"]
    assert control.claim(job, "worker-a")
    control.defer(job, "worker-a", 1, reason="runtime_capacity")
    assert store.admit(request["invocation_id"], request["request_digest"], "a", "boot-a")
    assert control.claim(job, "worker-b")
    assert not store.admit(request["invocation_id"], request["request_digest"], "b", "boot-b")
    assert (
        store.database.execute_one("select retry_count from agent_job where id = ?", (job,))[
            "retry_count"
        ]
        == 0
    )
    assert store.request(request["invocation_id"]) == request


def test_terminal_body_prune_retains_no_reexecution_tombstone(
    prepared: tuple[RuntimePoolStore, dict[str, Any]],
) -> None:
    store, request = prepared
    args = request["invocation_id"], request["request_digest"]
    store.admit(*args, "a", "boot-a")
    store.quiesce(args[0], "a", "boot-a")
    with store.database.unit_of_work():
        store.finish(*args, "a", "boot-a", "runtime_succeeded")
    assert not store.prune_body(args[0])  # Business result not committed yet.
    store.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = ?", (request["job_id"],)
    )
    assert store.prune_body(args[0])
    assert not store.admit(*args, "b", "boot-b")
    with pytest.raises(RuntimePoolError, match="runtime_recovery_expired"):
        store.request(args[0])
    with pytest.raises(RuntimePoolError, match="already_admitted"):
        store.prepare(request, attempt=0, admission_deadline_at="2099-01-01T00:00:00+00:00")


def test_watchdog_contains_a_cancelled_sdk_that_does_not_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.python_runtime import execution_slot

    cancel = threading.Event()
    cancelled: list[int] = []
    watchdog = execution_slot.ExecutionWatchdog(
        cancel, lambda: False, remaining_seconds=60, terminate=cancelled.append
    )
    ticks = iter([100.0, 111.0])

    class ImmediateWait:
        def wait(self, _seconds: float) -> bool:
            return False

    watchdog.stopped = ImmediateWait()  # type: ignore[assignment]
    watchdog.lease_deadline = 99
    monkeypatch.setattr(execution_slot.time, "monotonic", lambda: next(ticks))
    watchdog._watch()
    assert cancel.is_set() and cancelled == [70]


def test_cutover_preflight_blocks_existing_work_and_consumers() -> None:
    from app.cli.runtime_pool_preflight import inspect

    runtime = container()
    try:
        empty = {"job": {"messages": 0, "consumers": 0}}
        assert inspect(runtime.database, empty)["status"] == "ready"
        assert (
            inspect(runtime.database, {"job": {"messages": 0, "consumers": 1}})["status"]
            == "blocked"
        )
        runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="cutover-pending",
                requester_id="user_local_admin",
                user_message="synthetic",
                source_channel="debug_api",
            )
        )
        assert inspect(runtime.database, empty)["status"] == "blocked"
    finally:
        runtime.database.close()


@pytest.mark.parametrize("version", ["1.4", "1.5"])
def test_pool_control_contracts_are_strict_and_minimal(version: str) -> None:
    from app.modules.agent.infrastructure.runtime_protocol import validate_pool_contract

    golden = json.loads(
        Path(f"contracts/agent-runtime/v{version}/golden/pool-control.json").read_text()
    )
    errors = json.loads(Path(f"contracts/agent-runtime/v{version}/errors.json").read_text())
    assert (
        next(item for item in errors["errors"] if item["code"] == "runtime_timeout")["retry_class"]
        == "NEVER"
    )
    for name, definition in (
        ("recover", "RecoverRequest"),
        ("instance", "InstanceHeaders"),
        ("busy", "PoolControlError"),
    ):
        validate_pool_contract(definition, golden[name], version=version)
        with pytest.raises(ValueError):
            validate_pool_contract(
                definition, {**golden[name], "url": "http://untrusted.invalid"}, version=version
            )
    with pytest.raises(ValueError):
        validate_pool_contract(
            "InstanceHeaders", {"node_id": "a", "instance_id": "reused"}, version=version
        )


def test_stale_worker_cannot_schedule_retry_or_delivery() -> None:
    from app.shared.exceptions import RetryableExecutionError

    runtime = container()
    try:
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="stale-retry",
                requester_id="user_local_admin",
                user_message="synthetic",
                source_channel="debug_api",
            )
        )
        old = runtime.agent_repository.claim_job(job.id, "old")
        assert old
        runtime.database.execute(
            "update agent_job set worker_lease_until = '2000-01-01T00:00:00+00:00' where id = ?",
            (job.id,),
        )
        assert runtime.agent_repository.claim_job(job.id, "replacement")
        with pytest.raises(WorkerLeaseLost):
            runtime.retry_service.handle_failure(
                old, RetryableExecutionError("synthetic failure"), "synthetic"
            )
        assert runtime.agent_repository.get_job(job.id).retry_count == 0
        assert (
            runtime.database.execute_one(
                "select count(*) as n from delivery_outbox where job_id = ?", (job.id,)
            )["n"]
            == 0
        )
    finally:
        runtime.database.close()


@pytest.mark.parametrize(
    "code",
    [
        "runtime_timeout",
        "runtime_admission_timeout",
        "runtime_cancelled",
        "runtime_invocation_outcome_unknown",
        "runtime_recovery_expired",
    ],
)
def test_control_terminal_codes_never_become_business_retries(code: str) -> None:
    from app.shared.exceptions import RetryableExecutionError

    runtime = container()
    try:
        assert not runtime.retry_service.is_retryable(
            RetryableExecutionError("synthetic misclassified error", error_code=code)
        )
    finally:
        runtime.database.close()
