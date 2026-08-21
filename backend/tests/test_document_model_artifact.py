from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.document_processing.model_artifact import (
    model_bundle_digest,
    verify_model_bundle,
)


def test_model_bundle_digest_is_deterministic_and_content_bound(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "model.bin").write_bytes(b"model-a")
    (tmp_path / "nested" / "config.json").write_bytes(b'{"v":1}')

    digest, count = model_bundle_digest(tmp_path)

    assert count == 2
    assert verify_model_bundle(tmp_path, expected_digest=digest) == 2
    (tmp_path / "model.bin").write_bytes(b"model-b")
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_model_bundle(tmp_path, expected_digest=digest)


def test_model_bundle_rejects_empty_directory_and_symlink(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="file count"):
        model_bundle_digest(tmp_path)
    target = tmp_path / "model.bin"
    target.write_bytes(b"model")
    (tmp_path / "linked.bin").symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        model_bundle_digest(tmp_path)
