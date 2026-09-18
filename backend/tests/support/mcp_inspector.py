"""Pinned, non-interactive Inspector CLI and loopback server test support."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEPENDENCIES = ROOT / "tools/mcp-inspector"
SMOKE_FILE = "backend/tests/test_mcp_inspector_smoke.py"
RUNNER_FILE = "backend/tests/test_mcp_inspector_runner.py"
REQUIRED_SCENARIOS = frozenset(
    {
        "test_connect",
        "test_authorized_catalog",
        "test_success_and_audit",
        "test_repeated_calls",
        "test_invalid_arguments",
        "test_excluded_tool",
        "test_missing_execution_header",
        "test_forbidden_authorization",
        "test_connection_failure_is_not_denial",
        "test_inspector_total_timeout",
        "test_live_server_port_and_database_close_after_assertion",
    }
)


class InspectorFailure(RuntimeError):
    """Stable diagnostics; never include a subprocess environment or command."""


def isolated_environment(directory: Path) -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "HOME": str(directory),
        "TMPDIR": str(directory),
        "XDG_CONFIG_HOME": str(directory / "config"),
        "XDG_DATA_HOME": str(directory / "data"),
        "MCP_STORAGE_DIR": str(directory / "storage"),
        "MCP_INSPECTOR_OAUTH_STATE_PATH": str(directory / "oauth.json"),
        "MCP_CLIENT_CONFIG_PATH": str(directory / "client.json"),
        "MCP_CATALOG_PATH": str(directory / "catalog.json"),
        "BROWSER": "false",
        "NO_COLOR": "1",
    }


def run_process(
    argv: list[str], *, directory: Path, timeout: float = 30
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        argv,
        cwd=directory,
        env=isolated_environment(directory),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        raise InspectorFailure("Inspector 调用超时，已终止测试进程组") from None
    finally:
        # Also reap descendants on cancellation, errors and normal CLI exit.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)


@dataclass(frozen=True)
class CliResult:
    returncode: int
    result: dict | None
    error: dict | None
    stderr: str

    def success(self) -> dict:
        if self.returncode != 0 or self.result is None or self.result.get("isError"):
            raise InspectorFailure("Inspector 未返回预期成功结果")
        return self.result


@dataclass(frozen=True)
class Inspector:
    node: Path
    entry: Path
    version: str
    node_version: str

    @classmethod
    def installed(cls, *, dependencies: Path = DEPENDENCIES, node: str | None = None):
        executable = node or shutil.which("node")
        if not executable:
            raise InspectorFailure("缺少 Node，请按 docs/development/mcp-inspector.md 安装兼容版本")
        package = dependencies / "node_modules/@modelcontextprotocol/inspector"
        entry = package / "clients/cli/build/index.js"
        try:
            manifest = json.loads((dependencies / "package.json").read_text())
            wanted = manifest["devDependencies"]["@modelcontextprotocol/inspector"]
            node_requirement = manifest["engines"]["node"]
            installed = json.loads((package / "package.json").read_text())["version"]
        except (OSError, ValueError, KeyError):
            raise InspectorFailure(
                "缺少 Inspector 依赖，请先执行 npm ci --prefix tools/mcp-inspector"
            ) from None
        if installed != wanted or not entry.is_file():
            raise InspectorFailure("Inspector 安装版本不符或 CLI 缺失，请按锁文件重新安装")
        minimum = re.fullmatch(r">=([0-9]+)\.([0-9]+)\.([0-9]+)", str(node_requirement))
        if minimum is None:
            raise InspectorFailure(
                "Inspector Node 最低版本配置无效，请检查 package.json 的 engines.node"
            )
        with tempfile.TemporaryDirectory(prefix="enterprise-inspector-version-") as name:
            try:
                probe = run_process([executable, "--version"], directory=Path(name), timeout=5)
            except OSError:
                raise InspectorFailure("Node 无法执行，请检查已安装的测试运行时") from None
        node_version = probe.stdout.strip().removeprefix("v")
        actual = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", node_version)
        if (
            probe.returncode
            or actual is None
            or tuple(map(int, actual.groups())) < tuple(map(int, minimum.groups()))
        ):
            raise InspectorFailure(
                f"Node 版本不符：当前 {node_version or '未知'}，需要 {node_requirement}（正式版）。"
                "请先切换 Node 后重试，步骤见 docs/development/mcp-inspector.md"
            )
        return cls(Path(executable).resolve(), entry.resolve(), installed, node_version)

    def call(
        self,
        url: str,
        headers: dict[str, str],
        *,
        method: str | None = None,
        tool: str | None = None,
        arguments: dict | None = None,
        timeout: float = 30,
    ) -> CliResult:
        argv = [
            str(self.node),
            str(self.entry),
            "--server-url",
            url,
            "--transport",
            "http",
            "--format",
            "json",
            "--stored-auth-only",
            "--connect-timeout",
            "10000",
            "--protocol-era",
            "legacy",
        ]
        for key, value in headers.items():
            argv.extend(["--header", f"{key}: {value}"])
        if method:
            argv.extend(["--method", method])
        if tool:
            argv.extend(["--tool-name", tool])
        if arguments is not None:
            argv.extend(["--tool-args-json", json.dumps(arguments)])
        with tempfile.TemporaryDirectory(prefix="enterprise-inspector-call-") as name:
            output = run_process(argv, directory=Path(name), timeout=timeout)
        try:
            envelope = json.loads(output.stdout) if output.stdout.strip() else {}
            result = envelope.get("result")
            errors = []
            for line in output.stderr.splitlines():
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue  # Inspector may emit schema portability notices on stderr.
                if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                    errors.append(parsed["error"])
            if result is not None and not isinstance(result, dict):
                raise ValueError
        except (ValueError, AttributeError):
            raise InspectorFailure("Inspector stdout 不是预期 JSON 对象") from None
        return CliResult(output.returncode, result, errors[-1] if errors else None, output.stderr)


@contextmanager
def live_tool_mcp(service):
    import uvicorn

    from app.services.tool_mcp import create_app

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        app = create_app(service, allowed_hosts=(f"127.0.0.1:{port}",))
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                lifespan="on",
                loop="asyncio",
                http="h11",
                ws="none",
                access_log=False,
                log_config=None,
                log_level="critical",
                timeout_graceful_shutdown=2,
            )
        )
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [listener]},
            daemon=True,
            name="inspector-tool-mcp",
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise InspectorFailure("测试 MCP 服务未在期限内就绪")
                time.sleep(0.01)
            opener = build_opener(ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                assert json.load(response)["server_code"] == "tool-mcp"
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=2)
                raise InspectorFailure("测试 MCP 服务未按时停止")


class RequiredScenarios:
    """A green dedicated run requires every named scenario to actually pass."""

    def __init__(self):
        self.passed: set[str] = set()

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.passed:
            self.passed.add(report.nodeid)

    def missing(self) -> set[str]:
        return {f"{SMOKE_FILE}::{name}" for name in REQUIRED_SCENARIOS} - self.passed

    def pytest_sessionfinish(self, session, exitstatus):
        missing = self.missing()
        if missing:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            reporter = session.config.pluginmanager.get_plugin("terminalreporter")
            if reporter:
                reporter.write_line("Inspector 必需场景未实际通过：" + ", ".join(sorted(missing)))


def main() -> int:
    os.chdir(ROOT)
    os.environ["RUN_MCP_INSPECTOR_SMOKE"] = "1"
    try:
        client = Inspector.installed()
    except InspectorFailure as exc:
        print(str(exc))
        return 1
    import platform

    print(
        f"Inspector {client.version}; Node {client.node_version}; Python {platform.python_version()}"
    )
    gate = RequiredScenarios()
    status = pytest.main(["-q", "-rs", "--durations=10", SMOKE_FILE, RUNNER_FILE], plugins=[gate])
    # --help and other early exits can return zero without creating a pytest session.
    return int(status) or (1 if gate.missing() else 0)


if __name__ == "__main__":
    raise SystemExit(main())
