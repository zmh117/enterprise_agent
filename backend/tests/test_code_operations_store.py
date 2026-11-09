"""History operation admission/replay and transient delivery, without production SVN."""

import json
from datetime import UTC, datetime

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_svn_requests import history_request, time_range
from app.modules.knowledge.infrastructure.code_operation_store import CodeOperationStore
from app.modules.knowledge.infrastructure.code_result_authorizer import CodeResultAuthorizer
from app.modules.knowledge.infrastructure.code_result_buffer import CodeResultBuffer
from backend.tests.support.code_answers import analysis_context, code_configuration, confirm
from backend.tests.support.runtime import container


@pytest.fixture
def operation_setup(tmp_path):
    runtime = container()
    try:
        _, source, checkout, _ = code_configuration(runtime, tmp_path)
        store = CodeOperationStore(runtime.database, authorize=lambda context: None)
        context = analysis_context(runtime, source, checkout)
        analysis = confirm(store, context, store.begin(context, "start"))
        yield store, context, analysis
    finally:
        runtime.database.close()


def test_history_result_only_persists_metadata_and_replay_checks_digest(operation_setup):
    store, ctx, analysis = operation_setup
    request = {
        "path": "set_server",
        "selector": {"kind": "revision_range", "from_revision": 90, "to_revision": 100},
    }
    op = store.submit_history(
        ctx, analysis["id"], kind="log", request=request, request_key="log-one"
    )
    assert (
        store.submit_history(
            ctx, analysis["id"], kind="log", request=request, request_key="log-one"
        )["id"]
        == op["id"]
    )
    op = store.claim(op["id"], owner="synthetic-worker")
    buffer = CodeResultBuffer()
    payload = {"entries": [{"message": "synthetic private commit"}]}
    result_hash = buffer.put(op["id"], op["claim_version"], payload, deadline_at=op["deadline_at"])
    store.complete_history(
        ctx,
        op["id"],
        owner="synthetic-worker",
        claim=op["claim_version"],
        result_hash=result_hash,
        metadata={"count": 1},
    )
    assert json.loads(store.row("code_svn_operation", op["id"])["result_json"]) == {"count": 1}
    permitted = CodeResultAuthorizer(store.db, authorize=lambda context: None).authorize(
        op["id"], op["claim_version"]
    )
    assert (
        buffer.get(op["id"], op["claim_version"], expected_hash=permitted["result_hash"]) == payload
    )
    store.replay_history(ctx, op["id"])
    repeated = store.claim(op["id"], owner="replacement-worker")
    assert repeated["claim_version"] == op["claim_version"] + 1
    with pytest.raises(CodeKnowledgeError, match="CODE_RESULT_DENIED"):
        CodeResultAuthorizer(store.db, authorize=lambda context: None).authorize(
            op["id"], op["claim_version"]
        )
    with pytest.raises(CodeKnowledgeError, match="CODE_HISTORY_RESULT_CHANGED"):
        store.complete_history(
            ctx,
            op["id"],
            owner="replacement-worker",
            claim=repeated["claim_version"],
            result_hash="f" * 64,
            metadata={"count": 1},
        )
    store.complete_history(
        ctx,
        op["id"],
        owner="replacement-worker",
        claim=repeated["claim_version"],
        result_hash=result_hash,
        metadata={"count": 1},
    )
    store.revoke(ctx, analysis["id"])
    with pytest.raises(CodeKnowledgeError):
        CodeResultAuthorizer(store.db, authorize=lambda context: None).authorize(
            op["id"], repeated["claim_version"]
        )


def test_running_work_is_not_reclaimed_by_expiry_and_raw_metadata_is_rejected(operation_setup):
    store, ctx, analysis = operation_setup
    op = store.submit_history(
        ctx,
        analysis["id"],
        kind="blame",
        request={"path": "set_server/Order.cpp", "revision": 100, "start_line": 1, "end_line": 10},
        request_key="one",
    )
    op = store.claim(op["id"], owner="worker")
    with pytest.raises(CodeKnowledgeError, match="CODE_OPERATION_METADATA_INVALID"):
        store.complete_history(
            ctx,
            op["id"],
            owner="worker",
            claim=op["claim_version"],
            result_hash="f" * 64,
            metadata={"text": "synthetic raw text"},
        )
    store.db.execute(
        f"UPDATE {store.t('code_svn_operation')} SET lease_until=? WHERE id=?",
        (datetime(2000, 1, 1, tzinfo=UTC).isoformat(), op["id"]),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_OPERATION_NOT_CLAIMABLE"):
        store.claim(op["id"], owner="another-worker")
    with pytest.raises(CodeKnowledgeError):
        store.replay_history(ctx, op["id"])


def test_history_parameters_bind_fixed_range_scope_and_timezone():
    request = history_request(
        "log", {"path": "", "selector": {"kind": "latest"}}, upper=100, paths=["set_server"]
    )
    assert request["end"] == request["peg"] == 100
    assert time_range("2026-10-01", "2026-11-09", "Asia/Shanghai") == (
        "2026-09-30T16:00:00+00:00",
        "2026-11-09T16:00:00+00:00",
    )
    for arguments in (
        {"path": "set_server", "selector": {"kind": "revision", "revision": 101}},
        {"path": "private", "selector": {"kind": "latest"}},
        {"path": ".svn/wc.db", "selector": {"kind": "latest"}},
        {"path": "", "selector": {"kind": "latest"}, "command": "svn log"},
    ):
        with pytest.raises(CodeKnowledgeError):
            history_request("log", arguments, upper=100, paths=["set_server"])
    with pytest.raises(CodeKnowledgeError):
        time_range("2026-10-01T12:00:00", "2026-10-02T12:00:00", "Asia/Shanghai")


def test_executor_delivers_transient_payload_and_replay_never_reexecutes_update(
    operation_setup, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from app.modules.knowledge.infrastructure.code_operation_executor import CodeOperationExecutor

    store, ctx, analysis = operation_setup
    buffer = CodeResultBuffer()
    executor = CodeOperationExecutor(
        store,
        buffer,
        owner="worker",
        registry_file=tmp_path / "unused.json",
        auth_root=tmp_path,
        checkout_root=tmp_path,
        stopped=lambda: False,
    )
    calls = []
    payload = {"entries": [{"message": "synthetic private commit"}]}

    def client(operation, cancelled):
        assert not cancelled()
        return SimpleNamespace(
            source=SimpleNamespace(preflight=lambda revision: calls.append(revision))
        )

    class History:
        def __init__(self, source, **kwargs):
            assert kwargs["upper"] == 100

        def log(self, **kwargs):
            assert kwargs["end"] == 100
            return payload

        diff = blame = log

    monkeypatch.setattr(executor, "_client", client)
    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_operation_executor.SvnCodeHistory", History
    )
    operation = store.submit_history(
        ctx,
        analysis["id"],
        kind="log",
        request={"path": "", "selector": {"kind": "latest"}},
        request_key="transient",
    )
    executor.execute(operation["id"])
    completed = store.row("code_svn_operation", operation["id"])
    assert completed["state"] == "succeeded" and completed["quiesced_at"]
    assert "synthetic private commit" not in str(completed)
    assert (
        buffer.get(
            completed["id"], completed["claim_version"], expected_hash=completed["result_hash"]
        )
        == payload
    )
    buffer.clear()  # A restarted process has no cached raw payload.
    store.replay_history(ctx, completed["id"])
    executor.execute(completed["id"])
    repeated = store.row("code_svn_operation", completed["id"])
    assert repeated["state"] == "succeeded" and calls == [100, 100]
    assert repeated["result_hash"] == completed["result_hash"]
    admission = store.db.execute_one(
        f"SELECT id FROM {store.t('code_svn_operation')} WHERE analysis_id=? AND operation_kind='info'",
        (analysis["id"],),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_OPERATION_REPLAY_DENIED"):
        store.replay_history(ctx, admission["id"])


def test_executor_cancellation_waits_before_releasing_only_its_own_operation(
    operation_setup, tmp_path, monkeypatch
):
    from app.modules.knowledge.infrastructure.code_operation_executor import CodeOperationExecutor

    store, ctx, analysis = operation_setup
    operation = store.submit_history(
        ctx,
        analysis["id"],
        kind="log",
        request={"path": "", "selector": {"kind": "latest"}},
        request_key="cancelled",
    )
    executor = CodeOperationExecutor(
        store,
        CodeResultBuffer(),
        owner="worker",
        registry_file=tmp_path / "unused.json",
        auth_root=tmp_path,
        checkout_root=tmp_path,
        stopped=lambda: True,
    )
    monkeypatch.setattr(
        executor, "_client", lambda *args: pytest.fail("cancelled operation launched SVN")
    )
    executor.execute(operation["id"])
    stopped = store.row("code_svn_operation", operation["id"])
    assert stopped["state"] == "failed" and stopped["quiesced_at"]
    assert stopped["error_code"] == "CODE_OPERATION_CANCELLED"
    assert store.require_reader(ctx, analysis["id"])["read_released_at"] is None
