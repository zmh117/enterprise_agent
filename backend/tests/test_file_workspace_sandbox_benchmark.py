from __future__ import annotations

from pathlib import Path

from scripts.benchmark_file_workspace_sandbox import (
    MIB,
    RUNTIME_SANDBOX_DEFAULT_CAPACITY_BYTES,
    RUNTIME_SANDBOX_READINESS_MINIMUM_BYTES,
    run,
)


def test_sandbox_benchmark_freezes_default_margin_and_readiness_minimum(
    tmp_path: Path,
) -> None:
    result = run(tmp_path)
    limits = result["limits"]
    scenarios = result["scenarios"]

    assert limits == {
        "txt_file_limit_bytes": 15 * MIB,
        "workspace_temporary_quota_bytes": 100 * MIB,
        "readiness_minimum_bytes": 64 * MIB,
        "default_capacity_bytes": 256 * MIB,
        "default_safety_margin_bytes": 32 * MIB,
    }
    assert [scenario["logical_bytes"] for scenario in scenarios] == [
        46 * MIB,
        224 * MIB,
    ]
    assert all(scenario["allocated_bytes"] >= scenario["logical_bytes"] for scenario in scenarios)
    assert RUNTIME_SANDBOX_READINESS_MINIMUM_BYTES < RUNTIME_SANDBOX_DEFAULT_CAPACITY_BYTES
