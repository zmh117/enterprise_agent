from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.python_runtime.job_sandbox import (
    SANDBOX_MARKER,
    JobSandboxError,
    JobSandboxLimits,
    JobSandboxManager,
)


def _manager(tmp_path: Path, **limits: int) -> JobSandboxManager:
    return JobSandboxManager(
        tmp_path / "sandboxes",
        limits=JobSandboxLimits(**limits) if limits else None,
    )


def test_python_job_sandbox_maps_job_and_cleans_every_terminal_path(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    sandbox = manager.create("job-1")

    assert set(path.name for path in sandbox.path.iterdir()) == {
        SANDBOX_MARKER,
        "inputs",
        "work",
        "outputs",
        "tmp",
    }
    marker = json.loads((sandbox.path / SANDBOX_MARKER).read_text(encoding="utf-8"))
    assert marker == {"job_id": "job-1", "schema_version": 1}
    assert sandbox.authorize_tool(
        "Write", {"file_path": "work/draft.txt", "content": "draft"}
    ) == {"file_path": "work/draft.txt", "content": "draft"}
    (sandbox.path / "work/draft.txt").write_text("draft", encoding="utf-8")
    assert sandbox.authorize_tool(
        "Edit",
        {
            "file_path": "work/draft.txt",
            "old_string": "draft",
            "new_string": "final",
        },
    )["file_path"] == "work/draft.txt"
    assert sandbox.authorize_tool("Read", {"file_path": "work/draft.txt"})[
        "file_path"
    ] == "work/draft.txt"
    assert sandbox.authorize_tool("Grep", {"pattern": "draft", "path": "."})[
        "path"
    ] == "."
    assert sandbox.authorize_tool(
        "Glob", {"pattern": "**/*.txt", "path": "."}
    ) == {"pattern": "**/*.txt", "path": "."}
    assert sandbox.authorize_tool(
        "Write",
        {
            "file_path": str(sandbox.path / "outputs/sdk-normalized.txt"),
            "content": "normalized",
        },
    ) == {"file_path": "outputs/sdk-normalized.txt", "content": "normalized"}
    assert sandbox.authorize_tool(
        "Edit",
        {
            "file_path": str(sandbox.path / "work/sdk-normalized.txt"),
            "old_string": "before",
            "new_string": "after",
        },
    ) == {
        "file_path": "work/sdk-normalized.txt",
        "old_string": "before",
        "new_string": "after",
    }
    assert sandbox.authorize_tool(
        "Glob",
        {"pattern": "**/*.txt", "path": str(sandbox.path)},
    ) == {"pattern": "**/*.txt", "path": "."}

    sandbox.cleanup()
    assert not sandbox.path.exists()


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "code"),
    [
        ("Bash", {"command": "pwd"}, "sandbox_tool_denied"),
        ("Read", {"file_path": "/etc/passwd"}, "sandbox_path_invalid"),
        (
            "Write",
            {"file_path": "/tmp/other-sandbox/output.txt", "content": "x"},
            "sandbox_path_invalid",
        ),
        ("Read", {"file_path": "../escape.txt"}, "sandbox_path_invalid"),
        ("Read", {"file_path": "inputs/file.pdf"}, "sandbox_file_type_denied"),
        (
            "Glob",
            {"pattern": "../*.txt", "path": "."},
            "sandbox_tool_input_invalid",
        ),
        (
            "Glob",
            {"pattern": "**/*", "path": "."},
            "sandbox_tool_input_invalid",
        ),
        (
            "Glob",
            {"pattern": "**/*.txt", "path": "/tmp"},
            "sandbox_path_invalid",
        ),
        (
            "Write",
            {"file_path": "work/file.txt", "content": "x", "mode": "append"},
            "sandbox_tool_input_invalid",
        ),
    ],
)
def test_python_job_sandbox_rejects_ungoverned_tools_and_paths(
    tmp_path: Path,
    tool_name: str,
    tool_input: dict[str, object],
    code: str,
) -> None:
    sandbox = _manager(tmp_path).create("job-1")
    try:
        with pytest.raises(JobSandboxError) as captured:
            sandbox.authorize_tool(tool_name, tool_input)
        assert captured.value.code == code
    finally:
        sandbox.cleanup()


def test_python_job_sandbox_rejects_symlinks_special_files_and_limits(
    tmp_path: Path,
) -> None:
    sandbox = _manager(
        tmp_path,
        capacity_bytes=8,
        max_files=1,
        max_file_bytes=8,
    ).create("job-1")
    try:
        outside = tmp_path / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        (sandbox.path / "inputs/link.txt").symlink_to(outside)
        with pytest.raises(JobSandboxError) as captured:
            sandbox.authorize_tool("Read", {"file_path": "inputs/link.txt"})
        assert captured.value.code == "sandbox_symlink_denied"
        (sandbox.path / "inputs/link.txt").unlink()

        fifo = sandbox.path / "inputs/device.txt"
        os.mkfifo(fifo)
        with pytest.raises(JobSandboxError) as captured:
            sandbox.authorize_tool("Read", {"file_path": "inputs/device.txt"})
        assert captured.value.code == "sandbox_special_file_denied"
        fifo.unlink()

        (sandbox.path / "work/one.txt").write_text("12345678", encoding="utf-8")
        with pytest.raises(JobSandboxError) as captured:
            sandbox.authorize_tool(
                "Write", {"file_path": "work/two.txt", "content": "x"}
            )
        assert captured.value.code == "sandbox_file_count_exceeded"
        with pytest.raises(JobSandboxError) as captured:
            sandbox.authorize_tool(
                "Write", {"file_path": "work/one.txt", "content": "123456789"}
            )
        assert captured.value.code == "sandbox_file_limit_exceeded"
    finally:
        sandbox.cleanup()


def test_python_job_sandbox_residual_cleanup_is_marker_and_job_state_bound(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    running = manager.create("job-running")
    terminal = manager.create("job-terminal")
    unmarked = manager.root / "job-unmarked"
    unmarked.mkdir()
    malformed = manager.root / "job-malformed"
    malformed.mkdir()
    (malformed / SANDBOX_MARKER).write_text("{}", encoding="utf-8")

    cleaned = manager.cleanup_residuals(lambda job_id: job_id == "job-running")

    assert cleaned == ["job-terminal"]
    assert running.path.exists()
    assert not terminal.path.exists()
    assert unmarked.exists()
    assert malformed.exists()
    running.cleanup()
