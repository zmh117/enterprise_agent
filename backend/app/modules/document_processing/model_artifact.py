from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import sys


MODEL_MANIFEST_ALGORITHM = "relative-path-size-content-sha256/v1"
MAX_MODEL_FILES = 10_000


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
    if (
        len(expected_digest) != 71
        or not expected_digest.startswith("sha256:")
        or any(
            character not in "0123456789abcdef"
            for character in expected_digest.removeprefix("sha256:")
        )
    ):
        raise ValueError("Expected model artifact digest is invalid")
    actual_digest, file_count = model_bundle_digest(root)
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise ValueError("Model artifact digest mismatch")
    return file_count


def main() -> int:
    try:
        root = Path(os.environ["DOCLING_MODEL_ARTIFACT_PATH"])
        expected = os.environ["DOCLING_MODEL_ARTIFACT_DIGEST"]
        file_count = verify_model_bundle(root, expected_digest=expected)
    except (KeyError, OSError, ValueError):
        print("Docling model artifact verification failed", file=sys.stderr)
        return 1
    print(
        f"Docling model artifact verified algorithm={MODEL_MANIFEST_ALGORITHM} "
        f"file_count={file_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
