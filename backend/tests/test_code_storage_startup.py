"""Cross-platform Compose rendering and opt-in real storage startup regression."""

import copy
import json
import os
from pathlib import Path
import stat
import shutil
import subprocess
from uuid import uuid4

import pytest
import yaml

from backend.docker import initialize_code_storage as storage


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
CONSUMERS = (
    "api-server",
    "knowledge-sync",
    "knowledge-ops-controller",
    "python-agent-runtime-a",
    "python-agent-runtime-b",
)


def test_storage_init_is_a_bounded_gate_and_only_code_directories_autocreate():
    config = yaml.safe_load(COMPOSE.read_text())
    services = config["services"]
    initializer = services["code-storage-init"]
    assert initializer["network_mode"] == "none"
    assert not initializer.get("secrets") and not initializer.get("ports")
    assert initializer["read_only"] and initializer["restart"] == "no"
    assert initializer["build"]["target"] == "code-storage-init"
    assert len(initializer["volumes"]) == 2
    for name in CONSUMERS:
        assert services[name]["depends_on"]["code-storage-init"]["condition"] == (
            "service_completed_successfully"
        )
        for mount in services[name].get("volumes", []):
            if not isinstance(mount, dict) or mount["type"] != "bind":
                continue
            is_code = mount["source"].startswith("${CODE_SVN_")
            assert mount["bind"]["create_host_path"] is is_code
            if name != "knowledge-sync" or mount["target"] != "/var/lib/code-svn/checkout":
                assert mount["read_only"]


def test_checkout_volume_is_shared_without_host_binds_or_image_copy():
    config = yaml.safe_load(COMPOSE.read_text())
    assert config["volumes"]["code-svn-checkout"]["driver"] == "local"
    for name, target, readonly in (
        ("code-storage-init", "/storage/checkout", False),
        ("knowledge-sync", "/var/lib/code-svn/checkout", False),
        ("python-agent-runtime-a", "/var/lib/code-svn/checkout", True),
        ("python-agent-runtime-b", "/var/lib/code-svn/checkout", True),
        ("knowledge-ops-controller", "/deployment-code/checkout", True),
    ):
        mount = next(
            m
            for m in config["services"][name]["volumes"]
            if isinstance(m, dict) and m.get("target") == target
        )
        assert mount["type"] == "volume" and mount["source"] == "code-svn-checkout"
        assert mount["volume"] == {"nocopy": True}
        assert bool(mount.get("read_only")) == readonly
        assert "bind" not in mount
    assert "CODE_SVN_CHECKOUT_HOST_ROOT" not in COMPOSE.read_text()


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"HOME": "/home/deploy"}, "/home/deploy/.config/enterprise-agent"),
        ({"HOME": "/Users/deploy"}, "/Users/deploy/.config/enterprise-agent"),
        ({"USERPROFILE": "C:/Users/部署 用户"}, "C:/Users/部署 用户/.config/enterprise-agent"),
        ({"PLATFORM_SECRETS_DIR": "D:/agent secrets"}, "D:/agent secrets"),
    ],
)
def test_secret_paths_render_without_home_warning(tmp_path, values, expected):
    # Compose interpolation, not a simulated Windows filesystem/daemon acceptance.
    env_file = tmp_path / ".env"
    env_file.write_text("")
    environment = {"PATH": os.environ["PATH"], **values}
    cli = shutil.which("docker-compose")
    if not cli:
        pytest.skip("Standalone Compose executable required to isolate HOME lookup")
    command = [
        cli,
        "--env-file",
        str(env_file),
        "--project-directory",
        str(tmp_path),
        "-p",
        "storage-path-contract",
        "-f",
        str(COMPOSE),
        "config",
        "--format",
        "json",
    ]
    for overrides in ({}, {"APP_CONFIG_MASTER_KEY_FILE": "/existing/original-key"}):
        result = subprocess.run(
            command,
            env={**environment, **overrides},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert '"HOME" variable is not set' not in result.stderr
        config = json.loads(result.stdout)
        # A Linux Compose client prefixes Windows paths; interpolation is the assertion here.
        code_token = config["secrets"]["code_runtime_bootstrap_token"]["file"]
        assert code_token.endswith(expected + "/code-runtime-bootstrap-token")
        master = config["secrets"]["app_config_master_key"]["file"]
        if overrides:
            assert master == "/existing/original-key"
        else:
            assert master.endswith(expected + "/app-config-master-key")
        controller = config["services"]["knowledge-ops-controller"]
        assert (
            next(
                m["source"]
                for m in controller["volumes"]
                if m["target"] == ("/deployment-secrets/app-config-master-key")
            )
            == master
        )


@pytest.mark.parametrize("state", ["/data/code/../x", "", "/etc", "D:/"])
def test_initializer_rejects_unsafe_state_root(state):
    with pytest.raises(storage.InitializationError):
        storage.validate_state_root(state)


def test_initializer_accepts_default_and_native_windows_paths():
    storage.validate_state_root("./.local/code-svn/state")
    storage.validate_state_root(r"D:\企业项目\state")


def test_initializer_refuses_symlink_before_changing_directory_metadata(tmp_path):
    checkout, state, outside = (tmp_path / name for name in ("code", "state", "outside"))
    for directory in (checkout, state, outside):
        directory.mkdir(mode=0o700)
    (state / "configuration").symlink_to(outside, target_is_directory=True)
    before = checkout.stat()
    with pytest.raises(OSError):
        storage.initialize(checkout, state)
    assert checkout.stat().st_mode == before.st_mode
    assert not list(outside.iterdir())


def test_missing_all_secret_directory_sources_fails_explicitly(tmp_path):
    cli = shutil.which("docker-compose")
    if not cli:
        pytest.skip("Standalone Compose executable required to isolate HOME lookup")
    result = subprocess.run(
        [
            cli,
            "--env-file",
            os.devnull,
            "--project-directory",
            str(tmp_path),
            "-p",
            "storage-path-contract",
            "-f",
            str(COMPOSE),
            "config",
            "--quiet",
        ],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "Set PLATFORM_SECRETS_DIR or HOME or USERPROFILE" in result.stderr


@pytest.mark.parametrize("probe_failure", [False, True])
def test_translated_metadata_requires_actual_access_probe(tmp_path, monkeypatch, probe_failure):
    checkout, state = tmp_path / "code", tmp_path / "state"
    checkout.mkdir()
    state.mkdir()
    # Emulate a Desktop mapping that leaves POSIX owner unchanged.
    monkeypatch.setattr(storage.os, "fchown", lambda *args: None)
    observed = []

    def probe(*args):
        observed.append(args)
        if probe_failure:
            raise storage.InitializationError("code_directory_access_probe_failed")

    monkeypatch.setattr(storage, "probe_access", probe)
    if probe_failure:
        with pytest.raises(storage.InitializationError, match="access_probe_failed"):
            storage.initialize(checkout, state)
    else:
        assert storage.initialize(checkout, state) == "translated_access_verified"
    assert observed == [(checkout, state)]


@pytest.mark.skipif(
    os.environ.get("RUN_CODE_STORAGE_CONTAINER_TESTS") != "1",
    reason="requires the locally built code-storage-init:compat-check image and Docker",
)
@pytest.mark.parametrize("invalid", [False, True])
def test_real_compose_missing_directories_restart_and_failure_gate(tmp_path, invalid):
    project = "ea-storage-test-" + uuid4().hex[:10]
    checkout, state = tmp_path / "源码 checkout", tmp_path / "状态 state"
    initializer = copy.deepcopy(
        yaml.safe_load(COMPOSE.read_text())["services"]["code-storage-init"]
    )
    initializer.pop("build")
    initializer["image"] = "enterprise-agent/code-storage-init:compat-check"
    initializer["environment"] = {
        "CODE_INIT_STATE_HOST_PATH": str(state),
    }
    for mount, source in zip(initializer["volumes"], (checkout, state), strict=True):
        mount.update(type="bind", source=str(source), bind={"create_host_path": True})
        mount.pop("volume", None)
    reader = {
        "image": initializer["image"],
        "entrypoint": ["python", "-c"],
        "command": [
            "import os; from pathlib import Path; assert Path('/input').is_dir(); "
            "assert os.statvfs('/input').f_flag & os.ST_RDONLY"
        ],
        "user": "10002:10002",
        "group_add": ["10010"],
        "network_mode": "none",
        "read_only": True,
        "cap_drop": ["ALL"],
        "depends_on": {"code-storage-init": {"condition": "service_completed_successfully"}},
        "volumes": [
            {
                "type": "bind",
                "source": str(checkout),
                "target": "/input",
                "read_only": True,
                "bind": {"create_host_path": True},
            }
        ],
    }
    if invalid:
        state.mkdir()
        # Invalid node, caught before permissions/probes. No real data involved.
        (state / "configuration").write_text("synthetic invalid node")
    file = tmp_path / "compose.json"
    file.write_text(json.dumps({"services": {"code-storage-init": initializer, "reader": reader}}))
    command = ["docker", "compose", "--env-file", os.devnull, "-p", project, "-f", str(file)]

    def compose(*args):
        return subprocess.run(command + list(args), capture_output=True, text=True, timeout=60)

    try:
        result = compose("up", "-d")
        if invalid:
            assert result.returncode != 0
            rows = compose("ps", "--all", "--format", "json").stdout
            for row in rows.splitlines():
                item = json.loads(row)
                if item["Service"] == "reader":
                    assert item["State"] == "created"
            assert (state / "configuration").read_text() == "synthetic invalid node"
            return
        assert result.returncode == 0, result.stderr
        assert compose("wait", "reader").returncode == 0
        for child in ("configuration", "client", "client/trusted-ca"):
            assert (state / child).is_dir()
        assert '"status": "ready"' in compose("logs", "code-storage-init").stdout
        # Add existing synthetic content and prove subsequent initialization preserves it.
        sentinel = checkout / "existing.txt"
        sentinel.write_bytes(b"synthetic existing source")
        sentinel.chmod(0o600)
        before = sentinel.stat()
        result = compose("up", "-d", "--force-recreate")
        assert result.returncode == 0, result.stderr
        assert compose("wait", "reader").returncode == 0
        assert sentinel.read_bytes() == b"synthetic existing source"
        after = sentinel.stat()
        assert (stat.S_IMODE(after.st_mode), after.st_mtime_ns, after.st_ino) == (
            stat.S_IMODE(before.st_mode),
            before.st_mtime_ns,
            before.st_ino,
        )
        assert not list(checkout.glob(".ea-storage-check-*"))
    finally:
        assert compose("down", "--timeout", "5").returncode == 0


@pytest.mark.skipif(
    os.environ.get("RUN_CODE_STORAGE_CONTAINER_TESTS") != "1",
    reason="requires the locally built code-storage-init:compat-check image and Docker",
)
def test_real_compose_named_volume_initializer_readers_and_recreation(tmp_path):
    project = "ea-volume-test-" + uuid4().hex[:10]
    state = tmp_path / "状态 state"
    initializer = copy.deepcopy(
        yaml.safe_load(COMPOSE.read_text())["services"]["code-storage-init"]
    )
    initializer.pop("build")
    initializer["image"] = "enterprise-agent/code-storage-init:compat-check"
    initializer["environment"] = {"CODE_INIT_STATE_HOST_PATH": str(state)}
    initializer["volumes"][1]["source"] = str(state)
    services = {"code-storage-init": initializer}
    writer = {
        "image": initializer["image"],
        "entrypoint": ["python", "-c"],
        "command": [
            "import os; from pathlib import Path; os.umask(0o027); "
            "p=Path('/input/保留 source.txt'); "
            "p.write_text('synthetic preserved content') if not p.exists() else "
            "None; assert p.read_text() == 'synthetic preserved content'"
        ],
        "user": "10003:10010",
        "group_add": ["10010"],
        "network_mode": "none",
        "read_only": True,
        "cap_drop": ["ALL"],
        "depends_on": {"code-storage-init": {"condition": "service_completed_successfully"}},
        "volumes": [
            {
                "type": "volume",
                "source": "code-svn-checkout",
                "target": "/input",
                "volume": {"nocopy": True},
            }
        ],
    }
    services["writer"] = writer
    for name in ("reader-a", "reader-b"):
        reader = copy.deepcopy(writer)
        reader["user"] = "10002:10002"
        reader["volumes"][0]["read_only"] = True
        reader["depends_on"] = {"writer": {"condition": "service_completed_successfully"}}
        reader["command"] = [
            "import os; from pathlib import Path; "
            "assert os.statvfs('/input').f_flag & os.ST_RDONLY; "
            "assert Path('/input/保留 source.txt').read_text() == 'synthetic preserved content'"
        ]
        services[name] = reader
    file = tmp_path / "compose.json"
    file.write_text(
        json.dumps({"services": services, "volumes": {"code-svn-checkout": {"driver": "local"}}})
    )
    command = ["docker", "compose", "--env-file", os.devnull, "-p", project, "-f", str(file)]

    def compose(*args):
        return subprocess.run(command + list(args), capture_output=True, text=True, timeout=60)

    try:
        for iteration in range(2):
            result = compose("up", "-d")
            assert result.returncode == 0, result.stderr
            assert compose("wait", "reader-a", "reader-b").returncode == 0
            rows = [
                json.loads(line)
                for line in compose("ps", "-a", "--format", "json").stdout.splitlines()
            ]
            assert len(rows) == 4 and all(row["ExitCode"] == 0 for row in rows)
            if iteration == 0:
                # Remove containers, preserve the volume; next startup must retain source content.
                assert compose("down", "--timeout", "5").returncode == 0
                writer["command"] = [
                    "from pathlib import Path; assert Path('/input/保留 source.txt').read_text() == 'synthetic preserved content'"
                ]
                file.write_text(
                    json.dumps(
                        {
                            "services": services,
                            "volumes": {"code-svn-checkout": {"driver": "local"}},
                        }
                    )
                )
    finally:
        # Disposable project only; no production mounts or volumes are touched.
        assert compose("down", "--volumes", "--timeout", "5").returncode == 0
