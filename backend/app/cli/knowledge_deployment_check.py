"""Read-only controller compatibility check; never print raw Docker diagnostics."""

import json
import os
import subprocess

from app.modules.knowledge.infrastructure.deployment_paths import controller_environment


def main() -> int:
    try:
        project = os.environ["KNOWLEDGE_COMPOSE_PROJECT"]
        env = controller_environment(project)
        commands = [
            ["docker", "version", "--format", "{{.Server.Os}}"],
            [
                "docker",
                "compose",
                "--project-name",
                project,
                "--project-directory",
                "/deployment",
                "--env-file",
                "/deployment/.env",
                "-f",
                "/deployment/docker-compose.yml",
                "config",
                "--quiet",
            ],
        ]
        for index, command in enumerate(commands):
            result = subprocess.run(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=30,
            )
            if result.returncode or (index == 0 and result.stdout.strip() != b"linux"):
                raise ValueError
        print(json.dumps({"controller_paths": "passed", "compose_config": "passed"}))
        return 0
    except Exception:
        print(json.dumps({"error_code": "knowledge_controller_preflight_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
