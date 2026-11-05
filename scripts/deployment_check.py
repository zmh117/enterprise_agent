#!/usr/bin/env python3
"""Deployment checks for WSL2/Linux. Output contains statuses, never resolved config.

check: read-only preflight; init-volumes --fresh: explicit empty-install bootstrap;
accept: check default services and the real controller after Compose startup.
"""

import argparse
import json
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
ONESHOTS = {"migrator", "minio-init", "knowledge-model-prepare", "knowledge-reranker-prepare"}


class CheckError(Exception):
    pass


def run(command: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, cwd=ROOT)
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


def validate_config(config: dict) -> None:
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
        elif str(source) != config["secrets"][secret]["file"]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "init-volumes", "accept"))
    parser.add_argument(
        "--fresh", action="store_true", help="assert this is a new empty deployment"
    )
    args = parser.parse_args(argv)
    try:
        if platform.system() == "Windows":
            raise CheckError("use_wsl2_linux_terminal")
        if args.command == "init-volumes" and not args.fresh:
            raise CheckError("fresh_flag_required")
        if not (ROOT / ".env").is_file():
            raise CheckError("root_env_file_missing")
        for path in (ROOT / "backend/docker").glob("*.sh"):
            if b"\r" in path.read_bytes():
                raise CheckError("shell_crlf_detected")
        engine = run(
            ["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"]
        ).stdout.strip()
        if engine not in {"linux/amd64", "linux/arm64"}:
            raise CheckError("linux_engine_architecture_required")
        security = json.loads(
            run(["docker", "info", "--format", "{{json .SecurityOptions}}"]).stdout
        )
        if any("rootless" in str(option) or "userns" in str(option) for option in security or []):
            raise CheckError("custom_uid_mapping_requires_separate_acceptance")
        version = run(["docker", "compose", "version", "--short"]).stdout.strip()
        match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version)
        if not match or tuple(map(int, match.groups())) < (2, 24, 0):
            raise CheckError("compose_2_24_or_newer_required")
        config = json.loads(run(compose("config", "--format", "json")).stdout)
        validate_config(config)
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
                    "business_acceptance": "not_checked",
                },
                ensure_ascii=False,
            )
        )
        return 0
    except CheckError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}, ensure_ascii=False))
        return 1
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"status": "failed", "error_code": "deployment_configuration_invalid"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
