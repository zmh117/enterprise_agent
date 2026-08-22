from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

import pytest

from app.python_runtime.file_transfer import (
    FILE_TRANSFER_META_KEY,
    FILE_TRANSFER_PROTOCOL,
    FileTransferBoundaryError,
    FileTransferContext,
    FileTransferCoordinator,
    FileUploadReceipt,
    parse_file_transfer_control,
)
from app.python_runtime.job_sandbox import JobSandboxManager


CONTENT = b"private file body that must stay out of MCP JSON"
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()


def _materialize_control(relative_path: str = "inputs/evidence.txt") -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": "File version is ready"}],
        "_meta": {
            FILE_TRANSFER_META_KEY: {
                "protocol": FILE_TRANSFER_PROTOCOL,
                "action": "MATERIALIZE",
                "transfer_id": "transfer-1",
                "sandbox_entry_handle": "entry-1",
                "relative_path": relative_path,
                "expected_size_bytes": len(CONTENT),
                "expected_sha256": CONTENT_SHA256,
            }
        },
    }


def _upload_control(format_code: str | None = None) -> dict[str, object]:
    descriptor: dict[str, object] = {
        "protocol": FILE_TRANSFER_PROTOCOL,
        "action": "UPLOAD_COMMIT",
        "commit_id": "commit-1",
        "sandbox_entry_handle": "entry-1",
    }
    if format_code is not None:
        descriptor["format_code"] = format_code
    return {
        "content": [{"type": "text", "text": "Commit intent accepted"}],
        "_meta": {FILE_TRANSFER_META_KEY: descriptor},
    }


class _Port:
    def __init__(self) -> None:
        self.uploaded = b""

    def download(
        self,
        *,
        transfer_id: str,
        job_id: str,
        principal_token: str,
    ) -> Iterable[bytes]:
        assert transfer_id == "transfer-1"
        assert job_id == "job-1"
        assert principal_token == "principal-token-not-for-json"
        yield CONTENT[:12]
        yield CONTENT[12:]

    def upload(
        self,
        *,
        commit_id: str,
        job_id: str,
        principal_token: str,
        content: Iterable[bytes],
    ) -> FileUploadReceipt:
        assert commit_id == "commit-1"
        assert job_id == "job-1"
        assert principal_token == "principal-token-not-for-json"
        self.uploaded = b"".join(content)
        return FileUploadReceipt(
            file_id="file-2",
            version_id="version-2",
            size_bytes=len(self.uploaded),
            sha256=hashlib.sha256(self.uploaded).hexdigest(),
            status="COMMITTED",
            delivery_id="delivery-2",
            delivery_status="PENDING",
        )


def test_python_file_transfer_matches_typescript_control_and_safe_result(
    tmp_path: Path,
) -> None:
    port = _Port()
    coordinator = FileTransferCoordinator(port)
    sandbox = JobSandboxManager(tmp_path / "sandboxes").create("job-1")
    context = FileTransferContext(
        job_id="job-1",
        workspace_path=sandbox.path,
        principal_token="principal-token-not-for-json",
        sandbox=sandbox,
    )

    materialized = coordinator.process_mcp_control_result(
        _materialize_control(),
        context,
        materialization_identity=("file-1", "version-1"),
    )
    assert (sandbox.path / "inputs/evidence.txt").read_bytes() == CONTENT
    assert materialized == {
        "action": "MATERIALIZED",
        "sandbox_entry_handle": "entry-1",
        "relative_path": "inputs/evidence.txt",
        "format_code": "TXT",
        "size_bytes": len(CONTENT),
        "sha256": CONTENT_SHA256,
    }

    (sandbox.path / "inputs/evidence.txt").write_text("edited result", encoding="utf-8")
    committed = coordinator.process_mcp_control_result(_upload_control(), context)
    assert port.uploaded == b"edited result"
    assert committed["action"] == "COMMITTED"
    assert committed["file_id"] == "file-2"
    assert committed["version_id"] == "version-2"
    assert committed["delivery_id"] == "delivery-2"
    assert committed["delivery_status"] == "PENDING"

    serialized = json.dumps(
        {
            "materialize": _materialize_control(),
            "upload": _upload_control(),
            "materialized": materialized,
            "committed": committed,
        }
    )
    assert CONTENT.decode() not in serialized
    assert "edited result" not in serialized
    assert "principal-token-not-for-json" not in serialized


def test_python_file_transfer_rejects_paths_urls_object_keys_and_unknown_fields() -> None:
    invalid = [_materialize_control("../escape.txt"), _materialize_control("/absolute.txt")]
    for forbidden_field, value in (
        ("url", "https://untrusted.example/file"),
        ("object_key", "tenant/private/object"),
    ):
        control = _materialize_control()
        metadata = control["_meta"]
        assert isinstance(metadata, dict)
        descriptor = metadata[FILE_TRANSFER_META_KEY]
        assert isinstance(descriptor, dict)
        descriptor[forbidden_field] = value
        invalid.append(control)

    for control in invalid:
        with pytest.raises(FileTransferBoundaryError):
            parse_file_transfer_control(control)


def test_python_file_transfer_removes_partial_content_on_integrity_failure(
    tmp_path: Path,
) -> None:
    class WrongPort(_Port):
        def download(
            self,
            *,
            transfer_id: str,
            job_id: str,
            principal_token: str,
        ) -> Iterable[bytes]:
            del transfer_id, job_id, principal_token
            yield b"wrong"

    coordinator = FileTransferCoordinator(WrongPort())
    sandbox = JobSandboxManager(tmp_path / "sandboxes").create("job-1")
    with pytest.raises(
        FileTransferBoundaryError,
        match="download (exceeded|did not match)",
    ):
        coordinator.process_mcp_control_result(
            _materialize_control(),
            FileTransferContext(
                job_id="job-1",
                workspace_path=sandbox.path,
                principal_token="token",
                sandbox=sandbox,
            ),
            materialization_identity=("file-1", "version-1"),
        )
    assert not (sandbox.path / "inputs/evidence.txt").exists()
    recovered = FileTransferCoordinator(_Port()).process_mcp_control_result(
        _materialize_control(),
        FileTransferContext(
            job_id="job-1",
            workspace_path=sandbox.path,
            principal_token="principal-token-not-for-json",
            sandbox=sandbox,
        ),
        materialization_identity=("file-1", "version-1"),
    )
    assert recovered["sha256"] == CONTENT_SHA256


def test_python_file_transfer_rejects_capacity_before_download_or_target_creation(
    tmp_path: Path,
) -> None:
    class CountingPort(_Port):
        def __init__(self) -> None:
            super().__init__()
            self.download_calls = 0

        def download(self, **kwargs: object) -> Iterable[bytes]:
            self.download_calls += 1
            return super().download(**kwargs)  # type: ignore[arg-type]

    port = CountingPort()
    sandbox = JobSandboxManager(tmp_path / "sandboxes").create("job-1")
    for index in range(14):
        sandbox.reserve_input(
            identity=(f"reserved-file-{index}", f"reserved-version-{index}"),
            expected_size_bytes=15 * 1024 * 1024,
        )
    sandbox.reserve_work_output(
        relative_path="outputs/reserved.txt",
        expected_size_bytes=14 * 1024 * 1024,
    )

    with pytest.raises(FileTransferBoundaryError) as rejected:
        FileTransferCoordinator(port).process_mcp_control_result(
            _materialize_control(),
            FileTransferContext(
                job_id="job-1",
                workspace_path=sandbox.path,
                principal_token="principal-token-not-for-json",
                sandbox=sandbox,
            ),
            materialization_identity=("file-1", "version-1"),
        )

    assert rejected.value.code == "sandbox_capacity_exceeded"
    assert port.download_calls == 0
    assert not (sandbox.path / "inputs/evidence.txt").exists()


@pytest.mark.parametrize("failure_mode", ["download", "sha256"])
def test_python_file_transfer_releases_reservation_after_download_or_hash_failure(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    class FailedPort(_Port):
        def download(self, **_kwargs: object) -> Iterable[bytes]:
            if failure_mode == "download":
                raise OSError("synthetic download failure")
            return [b"x" * len(CONTENT)]

    sandbox = JobSandboxManager(tmp_path / "sandboxes").create("job-1")
    context = FileTransferContext(
        job_id="job-1",
        workspace_path=sandbox.path,
        principal_token="principal-token-not-for-json",
        sandbox=sandbox,
    )
    with pytest.raises((OSError, FileTransferBoundaryError)):
        FileTransferCoordinator(FailedPort()).process_mcp_control_result(
            _materialize_control(),
            context,
            materialization_identity=("file-1", "version-1"),
        )
    assert not (sandbox.path / "inputs/evidence.txt").exists()

    recovered = FileTransferCoordinator(_Port()).process_mcp_control_result(
        _materialize_control(),
        context,
        materialization_identity=("file-1", "version-1"),
    )
    assert recovered["sha256"] == CONTENT_SHA256


def test_python_file_transfer_uploads_only_an_explicit_registered_entry(
    tmp_path: Path,
) -> None:
    port = _Port()
    coordinator = FileTransferCoordinator(port)
    context = FileTransferContext(
        job_id="job-1",
        workspace_path=tmp_path,
        principal_token="principal-token-not-for-json",
    )
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs/selected.txt").write_text("selected", encoding="utf-8")
    (tmp_path / "outputs/not-selected.txt").write_text("private draft", encoding="utf-8")

    coordinator.register_sandbox_entry(
        sandbox_entry_handle="entry-1",
        relative_path="outputs/selected.txt",
        context=context,
    )
    result = coordinator.process_mcp_control_result(_upload_control(), context)

    assert result["action"] == "COMMITTED"
    assert port.uploaded == b"selected"
    assert b"private draft" not in port.uploaded


def test_python_file_transfer_rejects_registered_symlink(tmp_path: Path) -> None:
    port = _Port()
    coordinator = FileTransferCoordinator(port)
    context = FileTransferContext(
        job_id="job-1",
        workspace_path=tmp_path,
        principal_token="token",
    )
    (tmp_path / "outputs").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (tmp_path / "outputs/link.txt").symlink_to(outside)

    with pytest.raises(FileTransferBoundaryError) as captured:
        coordinator.register_sandbox_entry(
            sandbox_entry_handle="entry-1",
            relative_path="outputs/link.txt",
            context=context,
        )
    assert captured.value.code == "file_transfer_symlink_denied"


def test_python_file_transfer_selects_only_explicit_utf8_output(tmp_path: Path) -> None:
    port = _Port()
    coordinator = FileTransferCoordinator(port)
    context = FileTransferContext(
        job_id="job-select-1",
        workspace_path=tmp_path,
        principal_token="principal",
    )
    (tmp_path / "outputs").mkdir()
    (tmp_path / "inputs").mkdir()
    (tmp_path / "outputs/result.txt").write_text("valid UTF-8", encoding="utf-8")

    selected = coordinator.select_sandbox_output(
        relative_path="outputs/result.txt",
        context=context,
    )

    assert selected["action"] == "SELECTED"
    assert selected["relative_path"] == "outputs/result.txt"
    assert str(selected["sandbox_entry_handle"]).startswith("sandbox-entry:")

    (tmp_path / "outputs/invalid.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(FileTransferBoundaryError) as invalid_encoding:
        coordinator.select_sandbox_output(
            relative_path="outputs/invalid.txt",
            context=context,
        )
    assert invalid_encoding.value.code == "file_transfer_encoding_invalid"

    (tmp_path / "inputs/not-output.txt").write_text("valid", encoding="utf-8")
    with pytest.raises(FileTransferBoundaryError) as wrong_directory:
        coordinator.select_sandbox_output(
            relative_path="inputs/not-output.txt",
            context=context,
        )
    assert wrong_directory.value.code == "file_transfer_path_invalid"


def test_python_text_v2_selects_markdown_and_keeps_log_read_only(tmp_path: Path) -> None:
    coordinator = FileTransferCoordinator(_Port())
    context = FileTransferContext(
        job_id="job-text-v2",
        workspace_path=tmp_path,
        principal_token="principal",
    )
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs/report.md").write_text("# report\n", encoding="utf-8")
    (tmp_path / "outputs/service.log").write_text("readonly\n", encoding="utf-8")

    selected = coordinator.select_sandbox_output(
        relative_path="outputs/report.md",
        context=context,
    )
    assert selected["format_code"] == "MARKDOWN"
    with pytest.raises(FileTransferBoundaryError) as readonly:
        coordinator.select_sandbox_output(
            relative_path="outputs/service.log",
            context=context,
        )
    assert readonly.value.code == "file_format_read_only"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"\xef\xbb\xbf# report", "file_output_bom_forbidden"),
        (b"a\x00b", "file_transfer_type_invalid"),
        (b"\xff\xfe", "file_transfer_encoding_invalid"),
    ],
)
def test_python_upload_revalidates_markdown_before_streaming(
    tmp_path: Path,
    content: bytes,
    code: str,
) -> None:
    port = _Port()
    coordinator = FileTransferCoordinator(port)
    context = FileTransferContext(
        job_id="job-text-v2",
        workspace_path=tmp_path,
        principal_token="principal-token-not-for-json",
    )
    (tmp_path / "outputs").mkdir()
    target = tmp_path / "outputs/report.md"
    target.write_text("valid", encoding="utf-8")
    coordinator.register_sandbox_entry(
        sandbox_entry_handle="entry-1",
        relative_path="outputs/report.md",
        context=context,
    )
    target.write_bytes(content)

    with pytest.raises(FileTransferBoundaryError) as rejected:
        coordinator.process_mcp_control_result(
            _upload_control("MARKDOWN"),
            context,
        )
    assert rejected.value.code == code
    assert port.uploaded == b""
