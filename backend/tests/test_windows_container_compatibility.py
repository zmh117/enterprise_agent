from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest
import yaml

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.deployment_paths import (
    CONTROLLER_MOUNTS,
    docker_environment,
    mount_environment,
)
from scripts import deployment_check

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "backend/docker/normalize_secrets_entrypoint.sh"
DOCKERFILE = ROOT / "backend/Dockerfile"
SECRET_FILE_VARIABLES = {
    "CODE_RUNTIME_BOOTSTRAP_TOKEN_FILE",
    "APP_CONFIG_MASTER_KEY_FILE",
    "DELIVERY_WORKER_BOOTSTRAP_TOKEN_FILE",
    "DINGTALK_RUNTIME_AUTH_TOKEN_FILE",
    "DOCLING_SERVE_API_KEY_FILE",
    "FILE_PROCESSING_WORKER_BOOTSTRAP_TOKEN_FILE",
    "FILE_STORAGE_BOOTSTRAP_ACCESS_KEY_FILE",
    "FILE_STORAGE_BOOTSTRAP_SECRET_KEY_FILE",
    "FILE_WORKER_BOOTSTRAP_TOKEN_FILE",
    "INITIAL_ADMIN_PASSWORD_FILE",
    "KNOWLEDGE_BOOTSTRAP_TOKEN_FILE",
    "MODEL_PROBE_AUTH_TOKEN_FILE",
    "PRINCIPAL_JWKS_FILE",
    "PRINCIPAL_JWT_PRIVATE_KEY_FILE",
    "RUNTIME_GRANT_PRIVATE_KEY_FILE",
    "RUNTIME_GRANT_PUBLIC_KEY_FILE",
}


def test_shell_scripts_are_lf_normalized_by_repository_policy() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    scripts = sorted(
        path
        for root in (ROOT / "backend", ROOT / "frontend", ROOT / "scripts")
        for path in root.rglob("*.sh")
    )

    assert "*.sh text eol=lf" in attributes.splitlines()
    assert scripts
    for script in scripts:
        assert b"\r" not in script.read_bytes(), script.relative_to(ROOT)


def test_python_base_images_inherit_secret_normalization_entrypoint() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    base_section = dockerfile.split("FROM python:3.12-slim AS python-deps", 1)[1].split(
        "FROM python-deps AS claude-runtime",
        1,
    )[0]

    assert (
        "COPY backend/docker/normalize_secrets_entrypoint.sh "
        "/usr/local/bin/normalize-secrets-entrypoint" in base_section
    )
    assert 'ENTRYPOINT ["/usr/local/bin/normalize-secrets-entrypoint"]' in base_section


def test_compose_secret_file_variables_and_read_only_tmpfs_are_covered() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    configured_secret_variables: set[str] = set()
    for service_name, service in compose["services"].items():
        environment = service.get("environment", {})
        configured_secret_variables.update(
            name
            for name, value in environment.items()
            if name.endswith("_FILE") and "/run/secrets/" in str(value)
        )
        build = service.get("build", {})
        if not (
            service.get("read_only") is True
            and isinstance(build, dict)
            and build.get("dockerfile") == "backend/Dockerfile"
        ):
            continue
        runtime_tmpdir = str(environment.get("TMPDIR", "/tmp"))
        mount_targets = {str(item).split(":", 1)[0] for item in service.get("tmpfs", [])}
        assert runtime_tmpdir in mount_targets, service_name

    assert configured_secret_variables <= SECRET_FILE_VARIABLES


def test_entrypoint_normalizes_only_whitelisted_file_variables(
    tmp_path: Path,
) -> None:
    source = tmp_path / "windows-mounted-secret"
    source.write_text("sensitive-test-fixture\n", encoding="utf-8")
    source.chmod(0o777)
    ignored = tmp_path / "ignored-secret"
    ignored.write_text("ignored-test-fixture\n", encoding="utf-8")
    ignored.chmod(0o777)
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_tmp.mkdir(mode=0o700)
    environment = {
        **os.environ,
        "TMPDIR": str(runtime_tmp),
        "HOME": str(tmp_path / "must-not-be-used"),
        "APP_CONFIG_MASTER_KEY_FILE": str(source),
        "UNDECLARED_SECRET_FILE": str(ignored),
    }

    completed = subprocess.run(
        [
            str(ENTRYPOINT),
            sys.executable,
            "-c",
            "import os; print(os.environ['APP_CONFIG_MASTER_KEY_FILE'])",
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    normalized = Path(completed.stdout.strip())
    assert normalized == runtime_tmp / "ea-secrets" / "APP_CONFIG_MASTER_KEY_FILE"
    assert normalized.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(normalized.stat().st_mode) == 0o400
    assert stat.S_IMODE(normalized.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(source.stat().st_mode) == 0o777
    assert not (runtime_tmp / "ea-secrets" / "UNDECLARED_SECRET_FILE").exists()


def test_entrypoint_rejects_symlink_source_without_disclosing_content(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.write_text("must-not-appear-in-output", encoding="utf-8")
    link = tmp_path / "source-link"
    link.symlink_to(source)
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_tmp.mkdir()
    environment = {
        **os.environ,
        "TMPDIR": str(runtime_tmp),
        "APP_CONFIG_MASTER_KEY_FILE": str(link),
    }

    completed = subprocess.run(
        [str(ENTRYPOINT), sys.executable, "-c", "raise SystemExit(0)"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "APP_CONFIG_MASTER_KEY_FILE" in completed.stderr
    assert "must-not-appear-in-output" not in completed.stderr


def test_entrypoint_rejects_relative_tmpdir_instead_of_falling_back_to_home(
    tmp_path: Path,
) -> None:
    environment = {
        **os.environ,
        "TMPDIR": "relative-runtime-tmp",
        "HOME": str(tmp_path),
    }

    completed = subprocess.run(
        [str(ENTRYPOINT), sys.executable, "-c", "raise SystemExit(0)"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert str(tmp_path) not in completed.stderr


def test_entrypoint_contract_is_shell_valid_and_has_fixed_whitelist() -> None:
    content = ENTRYPOINT.read_text(encoding="utf-8")

    subprocess.run(
        ["sh", "-n", str(ENTRYPOINT)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert SECRET_FILE_VARIABLES == {
        line.strip()
        for line in content.split("secret_file_variables='", 1)[1].split("'", 1)[0].splitlines()
        if line.strip()
    }
    assert "/dev/shm" not in content
    assert "HOME" not in content
    assert 'exec "$@"' in content


def _mount_metadata(prefix: str) -> dict:
    return {
        "project": "synthetic-project",
        "service": "knowledge-ops-controller",
        "mounts": [
            {"Destination": target, "Source": f"{prefix}/{index}", "RW": False, "Type": "bind"}
            for index, target in enumerate(CONTROLLER_MOUNTS)
        ],
    }


@pytest.mark.parametrize(
    "prefix",
    [
        "/home/deploy/项目 with spaces",
        "/run/desktop/mnt/host/wsl/docker-desktop-bind-mounts/Ubuntu",
        "/run/desktop/mnt/host/c/Users/deploy",
    ],
)
def test_controller_uses_actual_daemon_mount_sources(prefix: str) -> None:
    env = mount_environment(_mount_metadata(prefix), "synthetic-project")
    assert env == {
        value: f"{prefix}/{index}" for index, value in enumerate(CONTROLLER_MOUNTS.values())
    }


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "writable", "volume", "windows", "project", "service"]
)
def test_controller_rejects_unverified_mount_metadata(change: str) -> None:
    metadata = _mount_metadata("/synthetic")
    if change == "missing":
        metadata["mounts"].pop()
    elif change == "duplicate":
        metadata["mounts"].append(metadata["mounts"][0])
    elif change in {"project", "service"}:
        metadata[change] = "unrelated"
    elif change == "writable":
        metadata["mounts"][0]["RW"] = True
    elif change == "volume":
        metadata["mounts"][0]["Type"] = "volume"
    else:
        metadata["mounts"][0]["Source"] = "C:/invalid-daemon-path"
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_ops_mount_invalid"):
        mount_environment(metadata, "synthetic-project")


def test_controller_discards_host_compose_and_remote_docker_overrides(monkeypatch) -> None:
    for key in (
        "COMPOSE_FILE",
        "COMPOSE_ENV_FILES",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
    ):
        monkeypatch.setenv(key, "untrusted")
    env = docker_environment()
    assert env["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert env["DOCKER_CONFIG"] == "/tmp/docker-config"
    assert not any(key.startswith("COMPOSE_") for key in env)
    assert "DOCKER_CONTEXT" not in env and "DOCKER_TLS_VERIFY" not in env


def test_bootstrap_master_key_is_idempotent_and_private(tmp_path: Path) -> None:
    script = ROOT / "scripts/bootstrap_agent_runtime_secrets.sh"
    subprocess.run(["sh", str(script), str(tmp_path)], capture_output=True, check=True)
    snapshots = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert snapshots["app-config-master-key"].startswith(b"EA_MASTER_KEY_V1:")
    second = subprocess.run(["sh", str(script), str(tmp_path)], capture_output=True, check=True)
    assert snapshots == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert stat.S_IMODE((tmp_path / "app-config-master-key").stat().st_mode) == 0o400
    assert snapshots["app-config-master-key"].strip() not in second.stdout + second.stderr


def test_docker_acl_only_grants_each_secret_to_its_container_consumers(tmp_path: Path) -> None:
    import json

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    captured = tmp_path / "calls.jsonl"
    executable = bin_dir / "setfacl"
    executable.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"with open({str(captured)!r}, 'a') as output: output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    executable.chmod(0o700)
    secrets_dir = tmp_path / "secrets"
    subprocess.run(
        [
            "sh",
            str(ROOT / "scripts/bootstrap_agent_runtime_secrets.sh"),
            str(secrets_dir),
            "--docker-acl",
        ],
        env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        check=True,
    )
    grants = {}
    for line in captured.read_text().splitlines():
        mode, acl, *files = json.loads(line)
        assert mode == "--set"  # Do not revive unrelated existing ACLs by merging.
        assert "g::---" in acl and "o::---" in acl
        users = {
            int(entry.split(":")[1])
            for entry in acl.split(",")
            if entry.startswith("u:") and not entry.startswith("u::")
        }
        grants.update({Path(file).name: users for file in files})
    assert grants["app-config-master-key"] == {0, 10001, 10002, 10003, 10005, 10007}
    assert grants["principal-jwt-private.pem"] == {0}
    assert grants["knowledge-bootstrap-token"] == {0, 10008}
    assert grants["docling-api-key"] == {1001, 10006}
    assert grants["runtime-grant-public.pem"] == {10002}


def _volume_config() -> dict:
    return {
        "name": "synthetic-project",
        "volumes": {
            name: {"name": "synthetic-" + name, "external": True}
            for name in deployment_check.KNOWLEDGE_VOLUMES
        },
    }


def test_fresh_volume_initialization_is_repeatable_and_only_creates_missing(monkeypatch) -> None:
    existing: set[str] = set()
    commands = []

    def run(command):
        commands.append(command)
        output = ""
        if command[1:3] == ["volume", "create"]:
            existing.add(command[-1])
        elif command[1:3] == ["volume", "inspect"]:
            output = "synthetic-project"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(deployment_check, "run", run)
    monkeypatch.setattr(deployment_check, "volume_exists", lambda name: name in existing)
    deployment_check.initialize_volumes(_volume_config())
    deployment_check.initialize_volumes(_volume_config())
    assert len([c for c in commands if c[1:3] == ["volume", "create"]]) == 4
    assert all("rm" not in command and "prune" not in command for command in commands)


@pytest.mark.parametrize("existing", ["container", "unowned_volume", "platform_data"])
def test_fresh_initialization_refuses_existing_installation_before_writes(
    monkeypatch, existing
) -> None:
    config = _volume_config()
    config["volumes"]["postgres18-data"] = {"name": "synthetic-postgres"}
    commands = []

    def run(command):
        commands.append(command)
        output = "container-id" if existing == "container" else ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(deployment_check, "run", run)
    monkeypatch.setattr(
        deployment_check,
        "volume_exists",
        lambda name: name == "synthetic-postgres" if existing == "platform_data" else True,
    )
    with pytest.raises(deployment_check.CheckError, match="fresh_init_refused"):
        deployment_check.initialize_volumes(config)
    assert not any(c[1:3] == ["volume", "create"] for c in commands)


def test_acceptance_requires_both_resident_health_and_successful_initialization() -> None:
    config = {
        "services": {
            "migrator": {},
            "knowledge-ops-controller": {"healthcheck": {"test": ["CMD", "probe"]}},
        }
    }
    good = [
        {"Service": "migrator", "State": "exited", "ExitCode": 0},
        {"Service": "knowledge-ops-controller", "State": "running", "Health": "healthy"},
    ]
    assert deployment_check.service_failures(config, good) == []
    assert deployment_check.service_failures(config, good[:1]) == [
        "knowledge-ops-controller:missing_or_duplicate"
    ]
    good[0]["ExitCode"] = 1
    good[1]["Health"] = "unhealthy"
    assert len(deployment_check.service_failures(config, good)) == 2


def test_acceptance_does_not_require_maintenance_profile_jobs_to_be_running() -> None:
    config = {"services": {"knowledge-check": {"profiles": ["maintenance"]}}}
    assert deployment_check.service_failures(config, []) == []
