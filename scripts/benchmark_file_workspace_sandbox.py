#!/usr/bin/env python3
"""Measure the bounded disk working sets used to size Runtime Job Sandbox tmpfs.

This benchmark writes valid UTF-8 synthetic files. It never uses business data and
does not infer production concurrency; capacity here is per Runtime container.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


MIB = 1024 * 1024
TXT_FILE_LIMIT_BYTES = 15 * MIB
WORKSPACE_TEMPORARY_QUOTA_BYTES = 100 * MIB
SINGLE_FILE_SCRATCH_BYTES = 16 * MIB
FULL_WORKSPACE_STREAMING_SCRATCH_BYTES = 24 * MIB
RUNTIME_SANDBOX_READINESS_MINIMUM_BYTES = 64 * MIB
RUNTIME_SANDBOX_DEFAULT_CAPACITY_BYTES = 256 * MIB


@dataclass(frozen=True)
class BenchmarkResult:
    scenario: str
    logical_bytes: int
    allocated_bytes: int
    elapsed_seconds: float


def _write_utf8(path: Path, size_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk = ("task workspace synthetic text\n" * 32768).encode("utf-8")
    remaining = size_bytes
    with path.open("xb") as output:
        while remaining:
            current = chunk[: min(len(chunk), remaining)]
            output.write(current)
            remaining -= len(current)
        output.flush()
        os.fsync(output.fileno())


def _allocated_bytes(root: Path) -> int:
    return sum(
        entry.stat().st_blocks * 512
        for entry in root.rglob("*")
        if entry.is_file()
    )


def _run_scenario(root: Path, name: str, file_sizes: tuple[int, ...]) -> BenchmarkResult:
    scenario_root = root / name
    started = time.perf_counter()
    for index, size_bytes in enumerate(file_sizes, start=1):
        _write_utf8(scenario_root / f"synthetic-{index}.txt", size_bytes)
    elapsed = time.perf_counter() - started
    result = BenchmarkResult(
        scenario=name,
        logical_bytes=sum(file_sizes),
        allocated_bytes=_allocated_bytes(scenario_root),
        elapsed_seconds=round(elapsed, 4),
    )
    shutil.rmtree(scenario_root)
    return result


def run(root: Path) -> dict[str, object]:
    single_file = _run_scenario(
        root,
        "single-legal-file",
        (TXT_FILE_LIMIT_BYTES, TXT_FILE_LIMIT_BYTES, SINGLE_FILE_SCRATCH_BYTES),
    )
    maximum_workspace = _run_scenario(
        root,
        "maximum-workspace-working-set",
        (
            WORKSPACE_TEMPORARY_QUOTA_BYTES,
            WORKSPACE_TEMPORARY_QUOTA_BYTES,
            FULL_WORKSPACE_STREAMING_SCRATCH_BYTES,
        ),
    )
    if single_file.logical_bytes > RUNTIME_SANDBOX_READINESS_MINIMUM_BYTES:
        raise RuntimeError("readiness minimum cannot hold one legal input/output working set")
    if maximum_workspace.logical_bytes > RUNTIME_SANDBOX_DEFAULT_CAPACITY_BYTES:
        raise RuntimeError("default capacity cannot hold the maximum modeled working set")
    return {
        "limits": {
            "txt_file_limit_bytes": TXT_FILE_LIMIT_BYTES,
            "workspace_temporary_quota_bytes": WORKSPACE_TEMPORARY_QUOTA_BYTES,
            "readiness_minimum_bytes": RUNTIME_SANDBOX_READINESS_MINIMUM_BYTES,
            "default_capacity_bytes": RUNTIME_SANDBOX_DEFAULT_CAPACITY_BYTES,
            "default_safety_margin_bytes": (
                RUNTIME_SANDBOX_DEFAULT_CAPACITY_BYTES - maximum_workspace.logical_bytes
            ),
        },
        "scenarios": [asdict(single_file), asdict(maximum_workspace)],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.root is not None:
        args.root.mkdir(parents=True, exist_ok=True)
        result = run(args.root)
    else:
        with tempfile.TemporaryDirectory(prefix="task-workspace-sandbox-benchmark-") as value:
            result = run(Path(value))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
