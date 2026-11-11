"""Map the controller's fixed mounts to Docker daemon paths, including Desktop/WSL.

Only mount metadata is inspected. Credential contents and container environments
must never enter this check or its diagnostics.
"""

import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
from typing import Any

from app.modules.knowledge.domain.operations import invalid


CONTROLLER_MOUNTS = {
    "/deployment": "KNOWLEDGE_DEPLOY_ROOT",
    "/deployment-secrets/app-config-master-key": "APP_CONFIG_MASTER_KEY_FILE",
    "/deployment-secrets/principal-jwks.json": "PRINCIPAL_JWKS_FILE",
    "/deployment-secrets/knowledge-bootstrap-token": "KNOWLEDGE_BOOTSTRAP_TOKEN_FILE",
    "/deployment-code/checkout": "CODE_SVN_CHECKOUT_VOLUME",
    "/deployment-code/state": "CODE_SVN_LOCAL_STATE_ROOT",
}
DIRECTORY_MOUNTS = {"/deployment", "/deployment-code/checkout", "/deployment-code/state"}


def docker_environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("COMPOSE_", "DOCKER_"))
    }
    env["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    env["DOCKER_CONFIG"] = "/tmp/docker-config"
    return env


def mount_environment(metadata: Any, project: str) -> dict[str, str]:
    if not isinstance(metadata, dict) or (
        metadata.get("project") != project or metadata.get("service") != "knowledge-ops-controller"
    ):
        raise invalid("knowledge_ops_mount_invalid")
    mounts = metadata.get("mounts")
    if not isinstance(mounts, list):
        raise invalid("knowledge_ops_mount_invalid")
    result: dict[str, str] = {}
    for target, variable in CONTROLLER_MOUNTS.items():
        matches = [
            row for row in mounts if isinstance(row, dict) and row.get("Destination") == target
        ]
        if len(matches) != 1:
            raise invalid("knowledge_ops_mount_invalid")
        row = matches[0]
        if target == "/deployment-code/checkout":
            name = row.get("Name")
            if (
                row.get("Type") != "volume"
                or row.get("Driver") != "local"
                or row.get("RW") is not False
                or not isinstance(name, str)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,254}", name)
            ):
                raise invalid("knowledge_ops_mount_invalid")
            result[variable] = name
            continue
        source = row.get("Source")
        if (
            row.get("Type") != "bind"
            or row.get("RW") is not False
            or not isinstance(source, str)
            or not source.startswith("/")
            or source.startswith("//")
            or ".." in PurePosixPath(source).parts
            or any(ord(char) < 32 for char in source)
        ):
            raise invalid("knowledge_ops_mount_invalid")
        result[variable] = source
    return result


def controller_environment(project: str) -> dict[str, str]:
    # Compose supplies the default container hostname. No arbitrary container lookup.
    hostname = socket.gethostname()
    if not re.fullmatch(r"[0-9a-f]{12,64}", hostname):
        raise invalid("knowledge_ops_mount_invalid")
    for target in CONTROLLER_MOUNTS:
        path = Path(target)
        if path.is_symlink() or not (
            path.is_dir() if target in DIRECTORY_MOUNTS else path.is_file()
        ):
            raise invalid("knowledge_ops_mount_invalid")
    if (
        not Path("/deployment/docker-compose.yml").is_file()
        or not Path("/deployment/.env").is_file()
    ):
        raise invalid("knowledge_ops_configuration_invalid")
    template = (
        '{"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
        '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
        '"mounts":{{json .Mounts}}}'
    )
    env = docker_environment()
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", template, hostname],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            env=env,
        )
        if result.returncode or len(result.stdout) > 128_000:
            raise ValueError
        paths = mount_environment(json.loads(result.stdout), project)
        # Never turn a volume's private Mountpoint into a host bind. Also reject
        # local driver options that disguise a Windows/NFS bind as a named volume.
        result = subprocess.run(
            [
                "docker",
                "volume",
                "inspect",
                "--format",
                '{"Driver":{{json .Driver}},"Options":{{json .Options}}}',
                paths["CODE_SVN_CHECKOUT_VOLUME"],
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            env=env,
        )
        if result.returncode or len(result.stdout) > 16_384:
            raise ValueError
        volume = json.loads(result.stdout)
        if (
            not isinstance(volume, dict)
            or volume.get("Driver") != "local"
            or volume.get("Options") not in (None, {})
        ):
            raise ValueError
    except (OSError, ValueError, subprocess.SubprocessError):
        raise invalid("knowledge_ops_mount_invalid") from None
    # Compose resolves build contexts in /deployment (client side), but bind sources
    # and file secrets must use daemon-side paths, not a Windows drive or WSL alias.
    return {**env, **paths}
