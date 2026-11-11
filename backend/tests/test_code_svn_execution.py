"""SVN process failures expose fixed classifications, never command or stderr text."""

import subprocess
import sys
import itertools
from types import SimpleNamespace

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource, SvnCommandFailure


def source_for(tmp_path, executable):
    return SvnCodeSource(
        branch_url="https://svn.invalid/trunk",
        expected_uuid="synthetic",
        branch_path="/trunk",
        config_directory=tmp_path,
        executable=str(executable),
    )


@pytest.mark.parametrize("operation", ["info", "propget", "list", "checkout", "update", "status"])
def test_unclassified_svn_failure_preserves_only_operation_exit_and_numeric_codes(
    tmp_path, operation
):
    executable = tmp_path / "failing-svn"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "print('synthetic source text')\n"
        "print('svn: E200030: private synthetic path and username', file=sys.stderr)\n"
        "print('svn: E000022: private synthetic connection detail', file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    executable.chmod(0o700)
    with pytest.raises(SvnCommandFailure, match="^code_svn_request_failed$") as failure:
        source_for(tmp_path, executable).execute(operation, [], timeout=10, limit=1024)
    assert failure.value.diagnostic == {
        "operation": operation,
        "exit_code": 1,
        "svn_error_codes": ["E000022", "E200030"],
    }
    assert "private" not in str(vars(failure.value))
    assert "synthetic source" not in str(vars(failure.value))


def test_nonzero_exit_without_svn_codes_does_not_invent_a_reason(tmp_path):
    executable = tmp_path / "failing-svn"
    executable.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(2)\n")
    executable.chmod(0o700)
    with pytest.raises(SvnCommandFailure) as failure:
        source_for(tmp_path, executable)._run("info", [])
    assert failure.value.diagnostic == {"operation": "info", "exit_code": 2, "svn_error_codes": []}


def test_svn_diagnostic_is_bounded_and_rejects_non_code_content():
    failure = SvnCommandFailure(
        "code_svn_request_failed",
        operation="arbitrary synthetic command",
        returncode=1000,
        error_codes={f"E{n:06}".encode() for n in range(20)}
        | {b"E000001 private detail", b"unknown", b"E1234567"},
    )
    assert failure.diagnostic == {
        "operation": "unknown",
        "exit_code": None,
        "svn_error_codes": [f"E{n:06}" for n in range(8)],
    }


@pytest.mark.parametrize("operation", ["info", "list", "propget", "checkout", "update"])
def test_command_timeout_is_specific_and_process_is_stopped(tmp_path, monkeypatch, operation):
    executable = tmp_path / "slow-svn"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    executable.chmod(0o700)
    real_popen, launched = subprocess.Popen, []

    def popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(CodeKnowledgeError) as failure:
        source_for(tmp_path, executable).execute(operation, [], timeout=0.1, limit=1024)
    assert failure.value.code == f"CODE_SVN_{operation.upper()}_TIMEOUT"
    assert len(launched) == 1 and launched[0].poll() is not None
    assert str(tmp_path) not in str(failure.value)


def test_timeout_after_output_eof_has_same_classification(tmp_path, monkeypatch):
    executable = tmp_path / "closed-output-svn"
    executable.write_text(
        f"#!{sys.executable}\nimport os, time\nos.close(1)\nos.close(2)\ntime.sleep(60)\n"
    )
    executable.chmod(0o700)
    real_wait, timed_out = subprocess.Popen.wait, []

    def wait(process, timeout=None):
        try:
            return real_wait(process, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out.append(True)
            raise

    monkeypatch.setattr(subprocess.Popen, "wait", wait)
    # Isolate the EOF/wait branch from interpreter startup time on a busy host.
    # Popen.wait still uses its real clock and must time out after the pipes close.
    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_svn.time",
        SimpleNamespace(monotonic=lambda: 0),
    )
    with pytest.raises(CodeKnowledgeError, match="^CODE_SVN_STATUS_TIMEOUT$"):
        source_for(tmp_path, executable).execute("status", [], timeout=0.1, limit=1024)
    assert timed_out


@pytest.mark.parametrize("missing", [True, False])
def test_missing_and_nonexecutable_command_are_distinguished(tmp_path, missing):
    executable = tmp_path / "unusable-svn"
    if not missing:
        executable.write_text("synthetic nonexecutable")
        executable.chmod(0o600)
    expected = "CODE_SVN_EXECUTABLE_NOT_FOUND" if missing else "CODE_SVN_EXECUTION_DENIED"
    with pytest.raises(CodeKnowledgeError, match=f"^{expected}$"):
        source_for(tmp_path, executable)._run("info", [])


def test_local_io_failure_does_not_leak_os_details_or_leave_child(tmp_path, monkeypatch):
    executable = tmp_path / "svn"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    executable.chmod(0o700)
    launched = []

    def interrupted(process, **kwargs):
        launched.append(process)
        raise OSError("private synthetic OS detail")

    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_svn._bounded_output", interrupted
    )
    with pytest.raises(CodeKnowledgeError) as failure:
        source_for(tmp_path, executable)._run("info", [])
    assert str(failure.value) == "CODE_SVN_LOCAL_IO_FAILED"
    assert launched[0].poll() is not None


def test_other_start_failure_is_not_reported_as_network_failure(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("private synthetic process resource detail")

    monkeypatch.setattr(subprocess, "Popen", unavailable)
    with pytest.raises(CodeKnowledgeError, match="^CODE_SVN_START_FAILED$"):
        source_for(tmp_path, "svn")._run("info", [])


@pytest.mark.parametrize("operation", ["inventory", "externals", "info"])
def test_bulk_checks_can_finish_after_a_simulated_minute(tmp_path, monkeypatch, operation):
    executable = tmp_path / "svn"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "print('<properties/>' if sys.argv[1] == 'propget' else '<lists><list/></lists>')\n"
    )
    executable.chmod(0o700)
    elapsed = itertools.chain([0], itertools.repeat(61))
    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_svn.time",
        SimpleNamespace(monotonic=lambda: next(elapsed)),
    )
    source = source_for(tmp_path, executable)
    if operation == "inventory":
        assert source.inventory("A", 2) == []
    elif operation == "externals":
        assert source.external_declarations(2, path="A")["declarations"] == []
    else:
        with pytest.raises(CodeKnowledgeError, match="^CODE_SVN_INFO_TIMEOUT$"):
            source._run("info", [])


def test_bulk_check_still_stops_when_operation_is_cancelled(tmp_path, monkeypatch):
    executable = tmp_path / "svn"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    executable.chmod(0o700)
    real_popen, launched = subprocess.Popen, []

    def popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    source = source_for(tmp_path, executable)
    # The enclosing operation deadline/cancellation becomes effective after launch.
    source.cancelled = lambda: bool(launched)
    with pytest.raises(CodeKnowledgeError, match="^code_collection_interrupted$"):
        source.inventory("A", 2)
    assert launched[0].poll() is not None
