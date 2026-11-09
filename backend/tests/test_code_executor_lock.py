"""An inherited OS lock is stop proof; database expiry is not."""

from copy import deepcopy
import subprocess
import sys

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_executor_lock import (
    execution_lock,
    inherited_execution_fds,
)


def test_child_retains_stop_proof_after_parent_closes_its_descriptor(tmp_path):
    root = tmp_path.resolve()
    row = {"id": "operation", "owner_instance_id": "worker", "claim_version": 1}
    process = None
    try:
        with execution_lock(root, "svn", row["id"]) as proof:
            proof.bind(row)
            process = subprocess.Popen(
                [sys.executable, "-c", "import sys; print('ready',flush=True); sys.stdin.read()"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                pass_fds=inherited_execution_fds(),
            )
            assert process.stdout.readline() == b"ready\n"
        assert inherited_execution_fds() == ()
        with pytest.raises(CodeKnowledgeError, match="CODE_EXECUTOR_STILL_RUNNING"):
            with execution_lock(root, "svn", row["id"]):
                pass
        process.stdin.close()
        process.wait(timeout=5)
        with execution_lock(root, "svn", row["id"]) as proof:
            assert proof.proves_stopped(row)
            changed = deepcopy(row)
            changed["claim_version"] = 2
            assert not proof.proves_stopped(changed)
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()


def test_missing_or_tampered_owner_is_not_stop_proof(tmp_path):
    row = {"id": "operation", "owner_instance_id": "worker", "claim_version": 1}
    with execution_lock(tmp_path.resolve(), "svn", row["id"]) as proof:
        assert not proof.proves_stopped(row)
    directory = tmp_path / ".executor-locks"
    file = next(directory.iterdir())
    file.unlink()
    file.symlink_to(tmp_path / "outside")
    with pytest.raises(OSError):
        with execution_lock(tmp_path.resolve(), "svn", row["id"]):
            pass
