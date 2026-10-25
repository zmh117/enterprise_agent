"""Bounded, metadata-only Docker sampling for an owned real acceptance fixture."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import time


def output(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def sample(root: Path) -> None:
    state = json.loads((root / "state.json").read_text())
    if state.get("owner") != "runtime-pool-acceptance/v1" or not state.get("real_provider"):
        raise ValueError("Only an owned real acceptance fixture may be sampled")
    hardware = {
        "host": {
            "machine": platform.machine(),
            "system": platform.system(),
            "cpu_count": os.cpu_count(),
            "memory_bytes": None,
        },
        "docker": json.loads(
            output(
                "docker",
                "info",
                "--format",
                '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"server_version":{{json .ServerVersion}},"architecture":{{json .Architecture}}}',
            )
        ),
    }
    (root / "evidence/hardware.json").write_text(json.dumps(hardware, indent=2))
    metrics = root / "metrics"
    metrics.mkdir(exist_ok=True)
    started = time.monotonic()
    with (metrics / "resources.jsonl").open("a") as stream:
        while not (root / "stop-sampler").exists() and time.monotonic() - started < 1200:
            ids = output(
                "docker",
                "ps",
                "--filter",
                "label=com.docker.compose.project=" + state["project"],
                "--format",
                "{{.ID}}",
            ).splitlines()
            if not ids:
                break
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                stream.write(
                    json.dumps(
                        {
                            "time": time.time(),
                            "containers": [json.loads(line) for line in result.stdout.splitlines()],
                        }
                    )
                    + "\n"
                )
                stream.flush()
            time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    sample(parser.parse_args().root)


if __name__ == "__main__":
    main()
