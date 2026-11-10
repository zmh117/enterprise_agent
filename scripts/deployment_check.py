#!/usr/bin/env python3
"""Deployment checks for Docker Desktop/Linux. Output statuses, never resolved config.

check [--require-code]: read-only preflight; init-volumes --fresh: empty-install volumes;
init-code-directories: initialize only explicit empty checkout/state roots;
accept: check default services and the real controller after Compose startup.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_VOLUMES = (
    "knowledge-models",
    "knowledge-reranker-models",
    "knowledge-qdrant",
    "knowledge-operation-state",
)
BOOTSTRAP_LABEL = "io.enterprise-agent.fresh-project"
ONESHOTS = {
    "migrator",
    "minio-init",
    "knowledge-model-prepare",
    "knowledge-reranker-prepare",
    "code-storage-init",
}
CODE_EXECUTOR_UID = 10003
CODE_READER_GID = 10010


class CheckError(Exception):
    pass


def run(command: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace", timeout=60, cwd=ROOT
        )
    except (OSError, subprocess.SubprocessError):
        raise CheckError("command_unavailable_or_timeout") from None
    if result.returncode and not allow_failure:
        # stderr/config may contain credentials. Do not include them in exceptions.
        raise CheckError("docker_command_failed")
    return result


def compose(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "docker-compose.yml"),
        *args,
    ]


def code_directory_layout(checkout: Path, state: Path) -> dict[Path, tuple[int, int, int]]:
    for path in (checkout, state):
        if (
            not path.is_absolute()
            or len(path.parts) < 3
            or path.resolve() != path
            or any(part == ".." for part in path.parts)
            or any(ord(c) < 32 for c in str(path))
        ):
            raise CheckError("code_directory_path_invalid")
        if any(parent.exists() and not parent.is_dir() for parent in path.parents):
            raise CheckError("code_directory_path_invalid")
    if checkout == state or checkout in state.parents or state in checkout.parents:
        raise CheckError("code_directory_overlap")
    return {
        checkout: (CODE_EXECUTOR_UID, CODE_READER_GID, 0o750),
        # Public registration and CA directories are traversable by deployment
        # checks. Private keys/auth files keep their own owner-only permissions.
        state: (CODE_EXECUTOR_UID, CODE_EXECUTOR_UID, 0o755),
        state / "configuration": (CODE_EXECUTOR_UID, CODE_EXECUTOR_UID, 0o755),
        state / "client": (CODE_EXECUTOR_UID, CODE_EXECUTOR_UID, 0o755),
        state / "client/trusted-ca": (CODE_EXECUTOR_UID, CODE_EXECUTOR_UID, 0o755),
    }


def directory_matches(info: os.stat_result, desired: tuple[int, int, int]) -> bool:
    return (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == desired


def initialize_code_directories(checkout: Path, state: Path) -> None:
    layout = code_directory_layout(checkout, state)
    # Validate every target before changing any; never recurse into working copies.
    for path, desired in layout.items():
        if path.resolve() != path or path.is_symlink():
            raise CheckError("code_directory_path_invalid")
        if path.exists():
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise CheckError("code_directory_path_invalid")
            if not directory_matches(info, desired) and next(path.iterdir(), None) is not None:
                raise CheckError("code_directory_existing_data_requires_maintenance")
    if os.geteuid() != 0 and any(
        uid != os.geteuid() or gid not in {os.getegid(), *os.getgroups()}
        for uid, gid, _ in layout.values()
    ):
        raise CheckError("code_directory_initialization_requires_root")
    for path, desired in layout.items():
        path.mkdir(parents=True, exist_ok=True)
        if path.resolve() != path:
            raise CheckError("code_directory_path_invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if not directory_matches(os.fstat(descriptor), desired):
                os.fchown(descriptor, desired[0], desired[1])
                os.fchmod(descriptor, desired[2])
            if not directory_matches(os.fstat(descriptor), desired):
                raise CheckError("code_directory_permissions_invalid")
        finally:
            os.close(descriptor)


def _bind(service: dict, target: str, *, readonly: bool) -> Path:
    matches = [m for m in service.get("volumes", []) if m.get("target") == target]
    if len(matches) != 1:
        raise CheckError("code_mount_invalid")
    mount = matches[0]
    if (
        mount.get("type") != "bind"
        or bool(mount.get("read_only", False)) != readonly
        or mount.get("bind", {}).get("create_host_path") is not True
    ):
        raise CheckError("code_mount_invalid")
    path = Path(mount["source"])
    if not path.is_absolute() or path.resolve() != path or not path.is_dir():
        raise CheckError("code_directory_missing_or_invalid")
    return path


def validate_code_initialization(services: dict, checkout: Path, state: Path) -> None:
    initializer = services.get("code-storage-init", {})
    if (
        _bind(initializer, "/storage/checkout", readonly=False) != checkout
        or _bind(initializer, "/storage/state", readonly=False) != state
    ):
        raise CheckError("code_mount_source_mismatch")
    for name in (
        "api-server",
        "knowledge-sync",
        "knowledge-ops-controller",
        "python-agent-runtime-a",
        "python-agent-runtime-b",
    ):
        if (
            services[name].get("depends_on", {}).get("code-storage-init", {}).get("condition")
            != "service_completed_successfully"
        ):
            raise CheckError("code_directory_initialization_gate_missing")


def validate_code_config(config: dict, *, require_code: bool = False) -> bool:
    services = config["services"]
    sync = services["knowledge-sync"]
    enabled = sync.get("environment", {}).get("CODE_CHECKOUT_ENABLED") == "true"
    if require_code and not enabled:
        raise CheckError("code_checkout_not_enabled")
    if str(sync.get("user", "")) != f"{CODE_EXECUTOR_UID}:{CODE_READER_GID}":
        raise CheckError("code_executor_identity_invalid")
    checkout = _bind(sync, "/var/lib/code-svn/checkout", readonly=False)
    controller = services["knowledge-ops-controller"]
    if _bind(controller, "/deployment-code/checkout", readonly=True) != checkout:
        raise CheckError("code_mount_source_mismatch")
    state = _bind(controller, "/deployment-code/state", readonly=True)
    validate_code_initialization(services, checkout, state)
    for name in ("python-agent-runtime-a", "python-agent-runtime-b"):
        if _bind(services[name], "/var/lib/code-svn/checkout", readonly=True) != checkout:
            raise CheckError("code_mount_source_mismatch")
    for name in ("knowledge-sync", "python-agent-runtime-a", "python-agent-runtime-b"):
        if str(CODE_READER_GID) not in {str(g) for g in services[name].get("group_add", [])}:
            raise CheckError("code_reader_group_missing")
    for name, target, expected in (
        ("knowledge-sync", "/etc/code-svn", state / "configuration"),
        ("knowledge-sync", "/run/code-svn-auth", state / "client"),
        ("api-server", "/etc/code-svn", state / "configuration"),
    ):
        if _bind(services[name], target, readonly=True) != expected:
            raise CheckError("code_mount_source_mismatch")
    for path, desired in code_directory_layout(checkout, state).items():
        if path.resolve() != path or not path.is_dir():
            raise CheckError("code_directory_missing_or_invalid")
        # Desktop host ownership may be translated; Linux/WSL local filesystems
        # must implement this exact UID/GID contract. Target probes remain required.
        if platform.system() == "Linux" and not directory_matches(path.stat(), desired):
            raise CheckError("code_directory_permissions_invalid")
    return enabled


def validate_config(config: dict, *, require_code: bool = False) -> None:
    project = config.get("name", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        raise CheckError("compose_project_invalid")
    controller = config["services"]["knowledge-ops-controller"]
    mounts = {row.get("target"): row for row in controller["volumes"]}
    expected = {
        "/deployment": None,
        "/deployment-secrets/app-config-master-key": "app_config_master_key",
        "/deployment-secrets/principal-jwks.json": "principal_jwks",
        "/deployment-secrets/knowledge-bootstrap-token": "knowledge_bootstrap_token",
    }
    for target, secret in expected.items():
        mount = mounts.get(target, {})
        if mount.get("type") != "bind" or mount.get("read_only") is not True:
            raise CheckError("controller_mount_invalid")
        source = Path(mount["source"])
        if not source.is_absolute() or source.is_symlink():
            raise CheckError("host_path_invalid")
        if target == "/deployment":
            if source.resolve() != ROOT.resolve():
                raise CheckError("deployment_root_mismatch")
        elif source != Path(config["secrets"][secret]["file"]):
            raise CheckError("controller_secret_path_mismatch")
    for name, secret in config["secrets"].items():
        if "file" not in secret:
            continue
        path = Path(secret["file"])
        try:
            info = path.lstat()
        except OSError:
            raise CheckError("secret_file_missing:" + name) from None
        if not path.is_absolute() or not stat.S_ISREG(info.st_mode) or not info.st_size:
            raise CheckError("secret_file_invalid:" + name)
    for key in KNOWLEDGE_VOLUMES:
        volume = config["volumes"][key]
        if volume.get("external") is not True or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]+", volume["name"]
        ):
            raise CheckError("knowledge_volume_invalid")
    validate_code_config(config, require_code=require_code)


def volume_exists(name: str) -> bool:
    # A failed inspect could mean daemon failure; successful ls distinguishes absence.
    names = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.splitlines()
    return name in names


def check_volumes(config: dict) -> None:
    missing = [
        key for key in KNOWLEDGE_VOLUMES if not volume_exists(config["volumes"][key]["name"])
    ]
    if missing:
        raise CheckError("external_volume_missing:" + ",".join(missing))


def initialize_volumes(config: dict) -> None:
    project = config["name"]
    containers = run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=" + project,
        ]
    ).stdout.strip()
    if containers:
        raise CheckError("fresh_init_refused_existing_containers")
    # Inspect every destination BEFORE creating anything. An existing platform data
    # volume or unowned knowledge volume means this is not a proven fresh install.
    for key, volume in config["volumes"].items():
        name = volume["name"]
        if not volume_exists(name):
            continue
        if key not in KNOWLEDGE_VOLUMES:
            raise CheckError("fresh_init_refused_existing_data")
        label = run(
            [
                "docker",
                "volume",
                "inspect",
                "--format",
                '{{index .Labels "' + BOOTSTRAP_LABEL + '"}}',
                name,
            ]
        ).stdout.strip()
        if label != project:
            raise CheckError("fresh_init_refused_unowned_volume")
    for key in KNOWLEDGE_VOLUMES:
        name = config["volumes"][key]["name"]
        if not volume_exists(name):
            run(["docker", "volume", "create", "--label", BOOTSTRAP_LABEL + "=" + project, name])
    check_volumes(config)


def service_failures(config: dict, rows: list[dict]) -> list[str]:
    failures = []
    for name, service in config["services"].items():
        if service.get("profiles"):
            continue  # Maintenance tools are not default resident services.
        matched = [row for row in rows if row.get("Service") == name]
        if len(matched) != 1:
            failures.append(name + ":missing_or_duplicate")
            continue
        row = matched[0]
        if name in ONESHOTS:
            ready = row.get("State") == "exited" and row.get("ExitCode") == 0
        else:
            ready = row.get("State") == "running" and (
                row.get("Health") == "healthy"
                if config["services"][name].get("healthcheck")
                else True
            )
        if not ready:
            failures.append(name + ":not_ready")
    return failures


def docker_versions() -> tuple[str, str]:
    engine = run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"])
    architecture = engine.stdout.strip()
    if architecture not in {"linux/amd64", "linux/arm64"}:
        raise CheckError("linux_engine_architecture_required")
    security = json.loads(run(["docker", "info", "--format", "{{json .SecurityOptions}}"]).stdout)
    if any("rootless" in str(option) or "userns" in str(option) for option in security or []):
        raise CheckError("custom_uid_mapping_requires_separate_acceptance")
    version = run(["docker", "compose", "version", "--short"]).stdout.strip()
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (2, 24, 0):
        raise CheckError("compose_2_24_or_newer_required")
    return architecture, version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("check", "init-volumes", "init-code-directories", "accept")
    )
    parser.add_argument("--checkout-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument(
        "--require-code", action="store_true", help="require an enabled SVN executor"
    )
    parser.add_argument(
        "--fresh", action="store_true", help="assert this is a new empty deployment"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "init-code-directories":
            if platform.system() == "Windows":
                raise CheckError("use_compose_code_storage_init")
            if args.checkout_root is None or args.state_root is None:
                raise CheckError("code_directory_arguments_required")
            initialize_code_directories(args.checkout_root, args.state_root)
            print(json.dumps({"command": args.command, "status": "passed"}))
            return 0
        if args.checkout_root is not None or args.state_root is not None:
            raise CheckError("code_directory_arguments_only_for_initialization")
        if args.command == "init-volumes" and not args.fresh:
            raise CheckError("fresh_flag_required")
        if not (ROOT / ".env").is_file():
            raise CheckError("root_env_file_missing")
        for path in (ROOT / "backend/docker").glob("*.sh"):
            if b"\r" in path.read_bytes():
                raise CheckError("shell_crlf_detected")
        engine, version = docker_versions()
        config = json.loads(run(compose("config", "--format", "json")).stdout)
        validate_config(config, require_code=args.require_code)
        if args.command == "init-volumes":
            initialize_volumes(config)
        else:
            check_volumes(config)
        if args.command == "accept":
            raw = run(compose("ps", "--all", "--format", "json")).stdout.strip()
            rows = (
                json.loads(raw)
                if raw.startswith("[")
                else [json.loads(line) for line in raw.splitlines()]
            )
            failures = service_failures(config, rows)
            if failures:
                raise CheckError("services_not_ready:" + ",".join(failures))
            run(
                compose(
                    "exec",
                    "-T",
                    "knowledge-ops-controller",
                    "python",
                    "-m",
                    "app.cli.knowledge_deployment_check",
                )
            )
        print(
            json.dumps(
                {
                    "command": args.command,
                    "status": "passed",
                    "engine": engine,
                    "compose": version,
                    "host": platform.system(),
                    "code_checkout_enabled": config["services"]["knowledge-sync"][
                        "environment"
                    ].get("CODE_CHECKOUT_ENABLED")
                    == "true",
                    "code_ownership_check": "passed"
                    if platform.system() == "Linux"
                    else "target_probe_required",
                    "business_acceptance": "not_checked",
                },
                ensure_ascii=False,
            )
        )
        return 0
    except PermissionError:
        print(json.dumps({"status": "failed", "error_code": "deployment_permission_denied"}))
        return 1
    except CheckError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}, ensure_ascii=False))
        return 1
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"status": "failed", "error_code": "deployment_configuration_invalid"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
