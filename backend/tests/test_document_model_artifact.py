from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.document_processing import model_artifact
from app.modules.document_processing.model_artifact import (
    DOCLING_IMAGE_INDEX_DIGEST,
    MODEL_ARTIFACT_PLATFORMS,
    current_runtime_platform,
    model_artifact_catalog_payload,
    model_artifact_for_platform,
    model_bundle_digest,
    normalize_runtime_platform,
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


def test_model_artifact_catalog_fixes_both_linux_platforms() -> None:
    assert DOCLING_IMAGE_INDEX_DIGEST == (
        "sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807"
    )
    assert model_artifact_catalog_payload()["platforms"] == {
        "linux/amd64": {
            "image_manifest_digest": (
                "sha256:0ccbc00b5f8b443334a7c4f36a5c6ff89c684c6fbe18ff7c1bc41e00b8e01657"
            ),
            "digest": (
                "sha256:bd9b6624ee97cd02b2506737e6f1646e25c68bf64a1cf4825a2ff69a5992c090"
            ),
        },
        "linux/arm64": {
            "image_manifest_digest": (
                "sha256:b09477515c6234bb86c8a90c9db3af2b5d6991aeb6b64c3348283be264dba63c"
            ),
            "digest": (
                "sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c"
            ),
        },
    }
    assert set(MODEL_ARTIFACT_PLATFORMS) == {"linux/amd64", "linux/arm64"}


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", "linux/amd64"),
        ("linux", "amd64", "linux/amd64"),
        ("Linux", "aarch64", "linux/arm64"),
        ("linux", "arm64", "linux/arm64"),
    ],
)
def test_runtime_platform_aliases_are_normalized(
    system: str,
    machine: str,
    expected: str,
) -> None:
    assert normalize_runtime_platform(system=system, machine=machine) == expected


@pytest.mark.parametrize(
    ("system", "machine"),
    [("Darwin", "arm64"), ("Linux", "riscv64"), ("", "")],
)
def test_unknown_runtime_platform_fails_closed(system: str, machine: str) -> None:
    with pytest.raises(ValueError, match="not supported"):
        normalize_runtime_platform(system=system, machine=machine)


def test_missing_platform_catalog_entry_fails_closed() -> None:
    with pytest.raises(ValueError, match="not supported"):
        model_artifact_for_platform("linux/riscv64")


def test_current_platform_and_catalog_selection_are_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_artifact.platform, "system", lambda: "Linux")
    monkeypatch.setattr(model_artifact.platform, "machine", lambda: "x86_64")

    assert current_runtime_platform() == "linux/amd64"
    selected = model_artifact_for_platform(current_runtime_platform())
    assert selected.platform == "linux/amd64"
    assert selected.digest.endswith("5992c090")
    assert selected.image_manifest_digest.endswith("b8e01657")


def test_verifier_main_ignores_legacy_digest_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "model.bin").write_bytes(b"model")
    digest, _ = model_bundle_digest(tmp_path)
    selected = model_artifact.ModelArtifactPlatform(
        platform="linux/amd64",
        image_manifest_digest="sha256:" + "1" * 64,
        digest=digest,
    )
    monkeypatch.setattr(model_artifact, "current_model_artifact", lambda: selected)
    monkeypatch.setenv("DOCLING_MODEL_ARTIFACT_PATH", str(tmp_path))
    monkeypatch.setenv("DOCLING_MODEL_ARTIFACT_DIGEST", "sha256:" + "0" * 64)

    assert model_artifact.main() == 0
