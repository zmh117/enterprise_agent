"""Exercise the dedicated gate and cleanup with deliberate, isolated failures."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import pytest

from backend.tests.support import mcp_inspector as support


@pytest.fixture
def inspector_dependencies(tmp_path):
    package = tmp_path / "node_modules/@modelcontextprotocol/inspector"
    (package / "clients/cli/build").mkdir(parents=True)
    (package / "clients/cli/build/index.js").write_text("")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "devDependencies": {
                    "@modelcontextprotocol/inspector": "2.7.0",
                },
                "engines": {"node": ">=22.19.0"},
            }
        )
    )
    (tmp_path / ".node-version").write_text("22.19.0")
    (package / "package.json").write_text(json.dumps({"version": "2.7.0"}))
    return tmp_path


@pytest.mark.parametrize(
    "fault", ["node_missing", "package_missing", "package_version", "node_version"]
)
def test_dependency_failure_closes_entrypoint(fault, inspector_dependencies, monkeypatch, capsys):
    package = inspector_dependencies / "node_modules/@modelcontextprotocol/inspector"
    if fault == "package_version":
        (package / "package.json").write_text(json.dumps({"version": "0.0.0"}))
    if fault == "package_missing":
        (package / "package.json").unlink()
    if fault == "node_missing":
        monkeypatch.setattr(support.shutil, "which", lambda _: None)
    installed = support.Inspector.installed
    # Python is executable but reports an incompatible version, without depending on local Node.
    monkeypatch.setattr(
        support.Inspector,
        "installed",
        lambda: installed(
            dependencies=inspector_dependencies,
            node=None if fault == "node_missing" else sys.executable,
        ),
    )
    monkeypatch.setenv("RUN_MCP_INSPECTOR_SMOKE", "0")
    assert support.main() == 1
    expected = {
        "node_missing": "缺少 Node",
        "package_missing": "缺少 Inspector 依赖",
        "package_version": "Inspector 安装版本不符",
        "node_version": "Node 版本不符",
    }
    assert expected[fault] in capsys.readouterr().out


@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        ("v22.18.99", False),
        ("v22.19.0", True),
        ("v22.19.1", True),
        ("v22.20.0", True),
        ("v22.100.0", True),
        ("v24.13.0", True),
        ("v22.19.0-rc.1", False),
        ("unexpected-version", False),
    ],
)
def test_node_minimum_version(version, accepted, inspector_dependencies, monkeypatch):
    # CI's exact pin must not become the local minimum when it is upgraded separately.
    (inspector_dependencies / ".node-version").write_text("24.13.0")
    monkeypatch.setattr(
        support,
        "run_process",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, version + "\n", ""),
    )
    if accepted:
        client = support.Inspector.installed(
            dependencies=inspector_dependencies, node=sys.executable
        )
        assert client.node_version == version.removeprefix("v")
    else:
        with pytest.raises(support.InspectorFailure, match=r"需要 >=22\.19\.0"):
            support.Inspector.installed(dependencies=inspector_dependencies, node=sys.executable)


@pytest.mark.parametrize(
    "fault", ["none", "zero", "all_skipped", "missing", "assertion", "teardown"]
)
def test_required_gate_checks_actual_pytest_results(fault, tmp_path):
    target = tmp_path / support.SMOKE_FILE
    target.parent.mkdir(parents=True)
    functions = []
    for index, name in enumerate(sorted(support.REQUIRED_SCENARIOS)):
        if fault == "zero" or (fault == "missing" and index == 0):
            continue
        body = "pytest.skip('synthetic skip')" if fault == "all_skipped" else "assert True"
        if fault == "assertion" and index == 0:
            body = "assert False, 'synthetic wrong expectation'"
        functions.append(f"def {name}():\n    {body}\n")
    source = "import pytest\n" + "\n".join(functions)
    if fault == "teardown":
        source += (
            "\n@pytest.fixture(autouse=True)\ndef broken_teardown():\n    yield\n    assert False\n"
        )
    target.write_text(source)
    script = (
        f"import sys; sys.path.insert(0, {str(support.ROOT)!r}); import pytest; "
        "from backend.tests.support.mcp_inspector import RequiredScenarios; "
        f"raise SystemExit(pytest.main(['-q', '-c', '/dev/null', '--rootdir=.', {support.SMOKE_FILE!r}], "
        "plugins=[RequiredScenarios()]))"
    )
    completed = support.run_process([sys.executable, "-c", script], directory=tmp_path)
    assert (completed.returncode == 0) is (fault == "none"), completed.stdout


@pytest.mark.parametrize("fault", ["timeout", "cancel"])
def test_process_cleanup_on_timeout_and_cancellation(fault, tmp_path, monkeypatch):
    pid_file = tmp_path / "pid"
    script = (
        "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(60)"
    )
    if fault == "cancel":
        communicate = subprocess.Popen.communicate
        cancelled = False

        def interrupt_once(process, *args, **kwargs):
            nonlocal cancelled
            if not cancelled:
                deadline = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                cancelled = True
                raise KeyboardInterrupt
            return communicate(process, *args, **kwargs)

        monkeypatch.setattr(subprocess.Popen, "communicate", interrupt_once)
    with pytest.raises(support.InspectorFailure if fault == "timeout" else KeyboardInterrupt):
        support.run_process([sys.executable, "-c", script], directory=tmp_path, timeout=0.5)
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_cli_state_is_removed_and_parent_environment_is_not_forwarded(tmp_path, monkeypatch):
    entry = tmp_path / "fake_cli.py"
    # A deliberately failing CLI records only whether our synthetic marker leaked.
    entry.write_text(
        "import os,pathlib,json,sys\n"
        "assert 'INSPECTOR_SYNTHETIC_PARENT_MARKER' not in os.environ\n"
        "assert 'NODE_OPTIONS' not in os.environ\n"
        "pathlib.Path(os.environ['MCP_INSPECTOR_OAUTH_STATE_PATH']).write_text('synthetic')\n"
        "print(json.dumps({'error': {'code':'synthetic'}}), file=sys.stderr)\n"
        "sys.exit(4)\n"
    )
    monkeypatch.setenv("INSPECTOR_SYNTHETIC_PARENT_MARKER", "not-a-secret")
    monkeypatch.setenv("NODE_OPTIONS", "synthetic-invalid-option")
    directories = []
    original = tempfile.TemporaryDirectory

    @contextmanager
    def tracked_directory(**kwargs):
        with original(dir=tmp_path, **kwargs) as name:
            directories.append(Path(name))
            yield name

    monkeypatch.setattr(support.tempfile, "TemporaryDirectory", tracked_directory)
    client = support.Inspector(Path(sys.executable), entry, "synthetic", "synthetic")
    result = client.call("http://127.0.0.1:1/mcp", {}, method="initialize")
    assert result.returncode == 4 and result.error == {"code": "synthetic"}
    with pytest.raises(support.InspectorFailure):
        result.success()
    assert directories and all(not path.exists() for path in directories)


def test_ci_requires_inspector_success_without_weakening_other_gates():
    import yaml

    workflow = yaml.safe_load((support.ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    inspector = jobs["mcp-inspector"]
    assert "if" not in inspector and not inspector.get("continue-on-error", False)
    assert all(not step.get("continue-on-error", False) for step in inspector["steps"])
    images = jobs["runtime-images"]
    required = {
        "backend-fast",
        "redis-pagination",
        "dingtalk-runtime",
        "python-runtime-contract",
        "mcp-inspector",
    }
    assert required | {"backend-full"} <= set(images["needs"])
    assert all(f"needs.{name}.result == 'success'" in images["if"] for name in required)


def test_entrypoint_rejects_pytest_early_success_without_session(monkeypatch):
    monkeypatch.setattr(
        support.Inspector,
        "installed",
        lambda: support.Inspector(
            Path(sys.executable),
            Path("synthetic-cli"),
            "synthetic",
            "synthetic",
        ),
    )
    monkeypatch.setattr(support.pytest, "main", lambda *args, **kwargs: 0)
    monkeypatch.setenv("RUN_MCP_INSPECTOR_SMOKE", "0")
    assert support.main() == 1
