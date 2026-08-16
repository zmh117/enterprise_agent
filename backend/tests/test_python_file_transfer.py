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


def _upload_control() -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": "Commit intent accepted"}],
        "_meta": {
            FILE_TRANSFER_META_KEY: {
                "protocol": FILE_TRANSFER_PROTOCOL,
                "action": "UPLOAD_COMMIT",
                "commit_id": "commit-1",
                "sandbox_entry_handle": "entry-1",
            }
        },
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
    context = FileTransferContext(
        job_id="job-1",
        workspace_path=tmp_path,
        principal_token="principal-token-not-for-json",
    )

    materialized = coordinator.process_mcp_control_result(_materialize_control(), context)
    assert (tmp_path / "inputs/evidence.txt").read_bytes() == CONTENT
    assert materialized == {
        "action": "MATERIALIZED",
        "sandbox_entry_handle": "entry-1",
        "relative_path": "inputs/evidence.txt",
        "size_bytes": len(CONTENT),
        "sha256": CONTENT_SHA256,
    }

    (tmp_path / "inputs/evidence.txt").write_text("edited result", encoding="utf-8")
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
    with pytest.raises(
        FileTransferBoundaryError,
        match="download (exceeded|did not match)",
    ):
        coordinator.process_mcp_control_result(
            _materialize_control(),
            FileTransferContext(
                job_id="job-1",
                workspace_path=tmp_path,
                principal_token="token",
            ),
        )
    assert not (tmp_path / "inputs/evidence.txt").exists()


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
