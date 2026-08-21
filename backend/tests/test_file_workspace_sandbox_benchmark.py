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
        "input_file_limit": 40,
        "work_output_file_limit": 16,
        "tmp_file_limit": 8,
        "total_file_limit": 64,
        "readiness_minimum_bytes": 224 * MIB,
        "default_capacity_bytes": 224 * MIB,
    }
    assert [scenario["logical_bytes"] for scenario in scenarios] == [
        31 * MIB,
        224 * MIB,
    ]
    assert [scenario["file_count"] for scenario in scenarios] == [3, 64]
    assert all(scenario["allocated_bytes"] >= scenario["logical_bytes"] for scenario in scenarios)
    assert RUNTIME_SANDBOX_READINESS_MINIMUM_BYTES == RUNTIME_SANDBOX_DEFAULT_CAPACITY_BYTES
