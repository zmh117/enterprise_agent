from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import platform
import sys
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


DOCLING_IMAGE_INDEX_DIGEST = (
    "sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807"
)
MODEL_ARTIFACT_CODE = "docling-v1.30.0-cpu-model-bundle"
MODEL_ARTIFACT_REVISION = "v1.30.0"
MODEL_MANIFEST_ALGORITHM = "relative-path-size-content-sha256/v1"
MAX_MODEL_FILES = 10_000


@dataclass(frozen=True, slots=True)
class ModelArtifactPlatform:
    platform: str
    image_manifest_digest: str
    digest: str


MODEL_ARTIFACT_PLATFORMS: Mapping[str, ModelArtifactPlatform] = MappingProxyType(
    {
        "linux/amd64": ModelArtifactPlatform(
            platform="linux/amd64",
            image_manifest_digest=(
                "sha256:0ccbc00b5f8b443334a7c4f36a5c6ff89c684c6fbe18ff7c1bc41e00b8e01657"
            ),
            digest=(
                "sha256:bd9b6624ee97cd02b2506737e6f1646e25c68bf64a1cf4825a2ff69a5992c090"
            ),
        ),
        "linux/arm64": ModelArtifactPlatform(
            platform="linux/arm64",
            image_manifest_digest=(
                "sha256:b09477515c6234bb86c8a90c9db3af2b5d6991aeb6b64c3348283be264dba63c"
            ),
            digest=(
                "sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c"
            ),
        ),
    }
)


def _validate_digest(value: str, *, label: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{label} digest is invalid")


def normalize_runtime_platform(*, system: str, machine: str) -> str:
    normalized_system = system.strip().lower()
    normalized_machine = machine.strip().lower()
    architectures = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    architecture = architectures.get(normalized_machine)
    if normalized_system != "linux" or architecture is None:
        raise ValueError("Docling model artifact runtime platform is not supported")
    return f"linux/{architecture}"


def current_runtime_platform() -> str:
    return normalize_runtime_platform(system=platform.system(), machine=platform.machine())


def model_artifact_for_platform(platform_code: str) -> ModelArtifactPlatform:
    try:
        artifact = MODEL_ARTIFACT_PLATFORMS[platform_code]
    except KeyError as exc:
        raise ValueError("Docling model artifact runtime platform is not supported") from exc
    if artifact.platform != platform_code:
        raise ValueError("Docling model artifact platform catalog is invalid")
    _validate_digest(artifact.image_manifest_digest, label="Image manifest")
    _validate_digest(artifact.digest, label="Model artifact")
    return artifact


def current_model_artifact() -> ModelArtifactPlatform:
    return model_artifact_for_platform(current_runtime_platform())


def model_artifact_catalog_payload() -> dict[str, object]:
    _validate_digest(DOCLING_IMAGE_INDEX_DIGEST, label="Image index")
    artifacts = {
        platform_code: model_artifact_for_platform(platform_code)
        for platform_code in MODEL_ARTIFACT_PLATFORMS
    }
    return {
        "code": MODEL_ARTIFACT_CODE,
        "revision": MODEL_ARTIFACT_REVISION,
        "image_index_digest": DOCLING_IMAGE_INDEX_DIGEST,
        "manifest_algorithm": MODEL_MANIFEST_ALGORITHM,
        "platforms": {
            platform_code: {
                "image_manifest_digest": artifact.image_manifest_digest,
                "digest": artifact.digest,
            }
            for platform_code, artifact in artifacts.items()
        },
    }


def model_bundle_digest(root: Path) -> tuple[str, int]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or root.is_symlink():
        raise ValueError("Model artifact root is invalid")
    entries = sorted(resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix())
    if any(entry.is_symlink() for entry in entries):
        raise ValueError("Model artifact symlinks are forbidden")
    files = [entry for entry in entries if entry.is_file()]
    if not files or len(files) > MAX_MODEL_FILES:
        raise ValueError("Model artifact file count is invalid")
    manifest = hashlib.sha256()
    for path in files:
        relative_path = path.relative_to(resolved).as_posix()
        size = path.stat().st_size
        content = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                content.update(chunk)
        manifest.update(relative_path.encode("utf-8"))
        manifest.update(b"\0")
        manifest.update(str(size).encode("ascii"))
        manifest.update(b"\0")
        manifest.update(content.hexdigest().encode("ascii"))
        manifest.update(b"\n")
    return f"sha256:{manifest.hexdigest()}", len(files)


def verify_model_bundle(root: Path, *, expected_digest: str) -> int:
    _validate_digest(expected_digest, label="Expected model artifact")
    actual_digest, file_count = model_bundle_digest(root)
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise ValueError("Model artifact digest mismatch")
    return file_count


def main() -> int:
    try:
        root = Path(os.environ["DOCLING_MODEL_ARTIFACT_PATH"])
        artifact = current_model_artifact()
        file_count = verify_model_bundle(root, expected_digest=artifact.digest)
    except (KeyError, OSError, ValueError):
        print("Docling model artifact verification failed", file=sys.stderr)
        return 1
    print(
        f"Docling model artifact verified platform={artifact.platform} "
        f"algorithm={MODEL_MANIFEST_ALGORITHM} "
        f"file_count={file_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
