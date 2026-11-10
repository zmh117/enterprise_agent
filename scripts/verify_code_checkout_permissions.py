#!/usr/bin/env python3
"""Disposable Linux SVN/UID acceptance; no production mounts, secrets or network."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        # Fixture output is synthetic, but avoid accidentally logging image config.
        raise RuntimeError("isolated_permission_probe_failed")


def verify(image: str) -> None:
    name = "ea-code-permissions-" + uuid4().hex[:12]
    containers: list[str] = []
    run(["docker", "volume", "create", "--label", "enterprise-agent.synthetic=true", name])

    def probe(
        action: str, user: str, *, readonly: bool = False, suffix: str = "", revision: int = 0
    ) -> None:
        container = name + "-" + action + suffix
        containers.append(container)
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            user,
            "--group-add",
            "10010",
            "--tmpfs",
            "/tmp:rw,mode=1777,size=32m",
            "--mount",
            f"type=volume,source={name},target=/fixture" + (",readonly" if readonly else ""),
            "--mount",
            f"type=bind,source={ROOT / 'backend'},target=/verify/backend,readonly",
            "--mount",
            f"type=bind,source={ROOT / 'scripts'},target=/verify/scripts,readonly",
            "-e",
            "PYTHONPATH=/verify/backend:/verify",
            "--entrypoint",
            "/verify/backend/docker/normalize_secrets_entrypoint.sh",
            image,
            "python",
            "/verify/backend/tests/support/code_permissions_probe.py",
            action,
        ]
        if action == "outsider":
            index = command.index("--group-add")
            del command[index : index + 2]
        if action == "prepare":
            index = command.index(image)
            command[index:index] = [
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "FOWNER",
                "--cap-add",
                "DAC_OVERRIDE",
            ]
        if revision:
            command.append(str(revision))
        run(command)

    try:
        probe("prepare", "0:0")
        probe("checkout", "10003:10010")
        for revision in (2, 3):
            if revision == 3:
                probe("update", "10003:10010")
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        probe,
                        "read",
                        "10002:10002",
                        readonly=True,
                        suffix=f"-{revision}-{node}",
                        revision=revision,
                    )
                    for node in ("a", "b")
                ]
                for future in futures:
                    future.result()
        probe("outsider", "10011:10011", readonly=True)
    finally:
        for container in containers:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        run(["docker", "volume", "rm", name])
    print(
        json.dumps(
            {
                "status": "passed",
                "revisions": [2, 3],
                "readers": 2,
                "readonly_mounts": True,
                "private_credentials": True,
                "target_vm_acceptance": "not_checked",
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image", required=True, help="local knowledge-sync image with SVN installed"
    )
    arguments = parser.parse_args()
    verify(arguments.image)
