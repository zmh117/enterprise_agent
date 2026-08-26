from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
import resource
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from app.python_runtime.file_transfer import (
    FILE_TRANSFER_META_KEY,
    FILE_TRANSFER_PROTOCOL,
    FileTransferContext,
    FileTransferCoordinator,
    FileUploadReceipt,
)
from app.python_runtime.job_sandbox import JobSandbox, JobSandboxManager
from app.python_runtime.log_evidence_scanner import execute_log_evidence_scan
from app.python_runtime.sdk_event_normalizer import (
    safe_file_tool_request,
    safe_log_evidence_response,
)


MIB = 1024 * 1024
INPUT_COUNT = 20
INPUT_SIZE_BYTES = 10 * MIB
_SYNTHETIC_LITERAL = "现场故障"


class _CommitPort:
    def __init__(self) -> None:
        self.uploaded = b""

    def download(self, **_kwargs: Any) -> Iterable[bytes]:
        raise AssertionError("batch validation must not repeat materialization")

    def upload(
        self,
        *,
        commit_id: str,
        job_id: str,
        principal_token: str,
        content: Iterable[bytes],
    ) -> FileUploadReceipt:
        assert commit_id == "commit-log-report"
        assert job_id == "job-log-batch"
        assert principal_token == "synthetic-principal-not-serialized"
        self.uploaded = b"".join(content)
        digest = hashlib.sha256(self.uploaded).hexdigest()
        return FileUploadReceipt(
            file_id="file-log-report",
            version_id="version-log-report",
            size_bytes=len(self.uploaded),
            sha256=digest,
            status="COMMITTED",
            delivery_id="delivery-log-report",
            delivery_status="PENDING",
        )


def _write_materialized_log(sandbox: JobSandbox, index: int) -> tuple[str, int]:
    relative_path = f"inputs/project-{index:02d}.log"
    identity = (f"file-log-{index:02d}", f"version-log-{index:02d}")
    reservation = sandbox.reserve_input(
        identity=identity,
        expected_size_bytes=INPUT_SIZE_BYTES,
    )
    reservation = sandbox.bind_input_reservation(
        reservation,
        relative_path=relative_path,
    )
    formats = (
        "plain ERROR 现场故障 timeout\n    at worker.run(task.py:7)\nnormal line\n",
        '{"level":"error","message":"现场故障","code":"E_SYNTHETIC"}\nnormal\n',
        'Traceback (most recent call last):\n  File "worker.py", line 7\nValueError: 现场故障\n',
        "WARN no timestamp 现场故障\nCaused by: synthetic failure\nnormal\n",
    )
    marker = formats[index % len(formats)].encode("utf-8")
    padding = (f"project-{index:02d} normal diagnostic data " + "x" * 96 + "\n").encode()
    block = marker + padding * 480
    target = sandbox.path / relative_path
    digest = hashlib.sha256()
    written = 0
    with target.open("xb") as output:
        while written + len(block) <= INPUT_SIZE_BYTES:
            output.write(block)
            digest.update(block)
            written += len(block)
        remainder = b"x" * (INPUT_SIZE_BYTES - written)
        output.write(remainder)
        digest.update(remainder)
        written += len(remainder)
        output.flush()
    sandbox.commit_input_reservation(
        reservation,
        size_bytes=written,
        sha256=digest.hexdigest(),
    )
    return relative_path, written


def _commit_report(sandbox: JobSandbox, scan: dict[str, object]) -> dict[str, object]:
    report = (
        "# Synthetic large-log analysis report\n\n"
        f"- Exact scanned bytes: {scan['scanned_bytes']}\n"
        f"- Exact logical lines: {scan['logical_line_count']}\n"
        f"- Heuristic candidates: {scan['candidate_count']}\n"
        f"- Retained candidates: {scan['retained_count']}\n"
        f"- Evidence limit reached: {str(scan['evidence_limit_reached']).lower()}\n\n"
        "Limitations: byte coverage and hashes are exact; candidate selection is a versioned "
        "heuristic; root-cause statements remain model inference. Unknown timestamps, users, "
        "operations, and business meaning remain unknown.\n"
    )
    relative_path = "outputs/log-analysis-report.md"
    sandbox.authorize_tool("Write", {"file_path": relative_path, "content": report})
    (sandbox.path / relative_path).write_text(report, encoding="utf-8")
    port = _CommitPort()
    coordinator = FileTransferCoordinator(port)
    context = FileTransferContext(
        job_id="job-log-batch",
        workspace_path=sandbox.path,
        principal_token="synthetic-principal-not-serialized",
        sandbox=sandbox,
    )
    selected = coordinator.select_sandbox_output(
        relative_path=relative_path,
        context=context,
    )
    committed = coordinator.process_mcp_control_result(
        {
            "content": [{"type": "text", "text": "synthetic commit accepted"}],
            "_meta": {
                FILE_TRANSFER_META_KEY: {
                    "protocol": FILE_TRANSFER_PROTOCOL,
                    "action": "UPLOAD_COMMIT",
                    "commit_id": "commit-log-report",
                    "sandbox_entry_handle": selected["sandbox_entry_handle"],
                    "format_code": "MARKDOWN",
                }
            },
        },
        context,
    )
    return {
        "selected": selected["action"] == "SELECTED",
        "committed": committed["action"] == "COMMITTED",
        "size_bytes": len(port.uploaded),
        "sha256": hashlib.sha256(port.uploaded).hexdigest(),
        "delivery_status": committed["delivery_status"],
    }


def run(root: Path) -> dict[str, object]:
    sandbox = JobSandboxManager(root / "sandboxes").create("job-log-batch")
    try:
        materialized = [_write_materialized_log(sandbox, index) for index in range(INPUT_COUNT)]
        request = {
            "relative_paths": [item[0] for item in materialized],
            "literal_terms": [_SYNTHETIC_LITERAL],
            "context_lines": 1,
            "max_evidence_items": 200,
        }
        tracemalloc.start()
        started = time.monotonic()
        scan = execute_log_evidence_scan(request, sandbox=sandbox)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _current_memory, peak_traced_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        raw_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        peak_rss_bytes = raw_rss if sys.platform == "darwin" else raw_rss * 1024

        safe_request = safe_file_tool_request(
            "mcp__file_service__scan_log_evidence",
            request,
        )
        safe_response = safe_log_evidence_response({"runtime_file_bridge": scan})
        event_projection = json.dumps(
            {"request": safe_request, "response": safe_response},
            ensure_ascii=False,
            sort_keys=True,
        )
        report = _commit_report(sandbox, scan)
        evidence_pack_size = scan.get("size_bytes")
        if not isinstance(evidence_pack_size, int) or isinstance(evidence_pack_size, bool):
            raise AssertionError("scanner returned an invalid evidence package size")
        result = {
            "input_count": INPUT_COUNT,
            "input_bytes": sum(item[1] for item in materialized),
            "materialization_count": len(materialized),
            "scan_invocations": 1,
            "scanned_bytes": scan["scanned_bytes"],
            "logical_line_count": scan["logical_line_count"],
            "candidate_count": scan["candidate_count"],
            "retained_count": scan["retained_count"],
            "omitted_count": scan["omitted_count"],
            "coverage_complete": scan["coverage_complete"],
            "evidence_limit_reached": scan["evidence_limit_reached"],
            "evidence_pack_size_bytes": evidence_pack_size,
            "evidence_pack_sha256": scan["sha256"],
            "elapsed_ms": elapsed_ms,
            "peak_traced_memory_bytes": peak_traced_memory,
            "peak_rss_bytes": peak_rss_bytes,
            "event_contains_literal_term": _SYNTHETIC_LITERAL in event_projection,
            "event_contains_input_path": "project-00.log" in event_projection,
            "report": report,
        }
        assert result["input_bytes"] == INPUT_COUNT * INPUT_SIZE_BYTES
        assert result["scanned_bytes"] == result["input_bytes"]
        assert result["materialization_count"] == INPUT_COUNT
        assert result["scan_invocations"] == 1
        assert result["coverage_complete"] is True
        assert evidence_pack_size <= 4 * MIB
        assert result["event_contains_literal_term"] is False
        assert result["event_contains_input_path"] is False
        assert report["selected"] is True
        assert report["committed"] is True
        return result
    finally:
        sandbox.cleanup()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="enterprise-agent-log-evidence-") as directory:
        print(json.dumps(run(Path(directory)), ensure_ascii=False, sort_keys=True, indent=2))
