"""A blocked source thread cannot starve lease renewal or conceal revocation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
import time

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure import code_operation_heartbeat as monitoring
from app.shared.exceptions import PermissionDenied


def monitor(renew, stopped=lambda: False):
    return monitoring.CodeOperationHeartbeat(
        operation_id="synthetic-operation",
        renew=renew,
        stopped=stopped,
        permission_error="code_checkout_access_denied",
    )


def test_blocked_source_thread_keeps_renewing_longer_than_lease(monkeypatch):
    monkeypatch.setattr(monitoring, "HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr(monitoring, "LEASE_SECONDS", 0.1)
    renewed = Event()
    owner = get_ident()
    calls = []

    def renew():
        calls.append((time.monotonic(), get_ident()))
        if len(calls) >= 15:
            renewed.set()

    with monitor(renew) as heartbeat:
        assert renewed.wait(timeout=3)  # No main-thread polling during this wait.
        assert calls[-1][0] - calls[0][0] > monitoring.LEASE_SECONDS
        assert all(thread != owner for _, thread in calls[1:])
        assert heartbeat.check() is False
        heartbeat.finish()
        assert heartbeat._thread is not None and not heartbeat._thread.is_alive()
        count = len(calls)
    assert len(calls) == count


@pytest.mark.parametrize("failure", ["permission", "database", "domain"])
def test_background_failure_keeps_safe_reason_and_stops_renewing(monkeypatch, caplog, failure):
    monkeypatch.setattr(monitoring, "HEARTBEAT_INTERVAL", 0.01)
    failed = Event()
    calls = []

    def renew():
        calls.append(True)
        if len(calls) > 1:
            failed.set()
            if failure == "permission":
                raise PermissionDenied("synthetic private credential detail")
            if failure == "domain":
                raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")
            raise RuntimeError("synthetic private database detail")

    expected = {
        "permission": "code_checkout_access_denied",
        "database": "CODE_OPERATION_HEARTBEAT_FAILED",
        "domain": "CODE_CONFIGURATION_CHANGED",
    }[failure]
    with monitor(renew) as heartbeat:
        assert failed.wait(timeout=3)
        with pytest.raises(CodeKnowledgeError, match=f"^{expected}$"):
            heartbeat.finish()
    assert len(calls) == 2
    assert "synthetic-operation" in caplog.text and expected in caplog.text
    assert "private" not in caplog.text


def test_finish_joins_pending_renewal_before_final_transaction(monkeypatch):
    monkeypatch.setattr(monitoring, "HEARTBEAT_INTERVAL", 0.01)
    entered, release, finalizing = Event(), Event(), Event()
    calls = []

    def renew():
        calls.append(True)
        if len(calls) > 1:
            entered.set()
            assert release.wait(timeout=3)

    def execute():
        with monitor(renew) as heartbeat:
            assert entered.wait(timeout=3)
            heartbeat.finish()
            finalizing.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute)
        try:
            assert entered.wait(timeout=3)
            assert not finalizing.is_set()
        finally:
            release.set()
        future.result(timeout=3)
    assert finalizing.is_set() and len(calls) == 2


def test_no_success_after_local_freshness_expires(monkeypatch):
    with monitor(lambda: None) as heartbeat:
        heartbeat.close()
        monkeypatch.setattr(monitoring, "LEASE_SECONDS", 0)
        with pytest.raises(CodeKnowledgeError, match="^CODE_OPERATION_LEASE_LOST$"):
            heartbeat.check()


def test_thread_start_failure_still_allows_idempotent_close(monkeypatch):
    def fail(*args):
        raise RuntimeError("synthetic private thread detail")

    monkeypatch.setattr(monitoring.Thread, "start", fail)
    heartbeat = monitor(lambda: None)
    with pytest.raises(CodeKnowledgeError, match="^CODE_OPERATION_HEARTBEAT_FAILED$"):
        with heartbeat:
            pytest.fail("unmonitored work started")
    heartbeat.close()


def test_parallel_operation_cancellation_signals_only_its_own_child(tmp_path, monkeypatch):
    import subprocess
    import sys
    from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource

    monkeypatch.setattr(monitoring, "HEARTBEAT_INTERVAL", 0.01)
    executable = tmp_path / "synthetic-svn"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    executable.chmod(0o700)
    blocked = {key: Event() for key in ("first", "second")}
    stopping = {key: Event() for key in blocked}
    release = Event()
    processes = {}
    real_popen = subprocess.Popen

    def popen(command, **kwargs):
        process = real_popen(command, **kwargs)
        processes[command[-1]] = process
        return process

    def execute(key):
        with monitor(lambda: None, stopped=stopping[key].is_set) as heartbeat:
            source = SvnCodeSource(
                branch_url="https://svn.invalid/trunk",
                expected_uuid="synthetic",
                branch_path="/trunk",
                config_directory=tmp_path,
                executable=str(executable),
                cancelled=heartbeat.check,
            )

            def blocked_io():
                blocked[key].set()
                assert release.wait(timeout=5)
                return heartbeat.check()

            with pytest.raises(CodeKnowledgeError, match="^CODE_EXECUTOR_STOPPING$"):
                source.execute("update", [key], timeout=10, limit=1024, cancelled=blocked_io)

    monkeypatch.setattr(subprocess, "Popen", popen)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, key) for key in blocked]
        try:
            assert all(event.wait(timeout=3) for event in blocked.values())
            stopping["first"].set()
            assert processes["first"].wait(timeout=3) != 0
            assert processes["second"].poll() is None
        finally:
            stopping["second"].set()
            release.set()
        for future in futures:
            future.result(timeout=3)
