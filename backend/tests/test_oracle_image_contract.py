from __future__ import annotations

import platform
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.modules.mcp_tool_runtime.domain.errors import ResolutionError
from app.modules.mcp_tool_runtime.infrastructure.db.oracle_client import (
    inspect_oracle_client,
)


ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = ROOT / "backend/docker/verify_oracle_client.py"
SETUP_SCRIPT = ROOT / "backend/docker/setup_oracle_client.sh"
DOCKERFILE = ROOT / "backend/Dockerfile"
README = ROOT / "backend/vendor/oracle/README.md"


def _runtime_architecture() -> tuple[str, int]:
    normalized = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }.get(platform.machine().lower(), platform.machine().lower())
    return normalized, {"x86_64": 62, "aarch64": 183}[normalized]


def _elf_header(machine: int, *, bits: int = 64) -> bytes:
    header = bytearray(20)
    header[:4] = b"\x7fELF"
    header[4] = 2 if bits == 64 else 1
    header[5] = 1
    header[18:20] = machine.to_bytes(2, "little")
    return bytes(header)


def test_oracle_client_verifier_accepts_only_matching_64_bit_19c(
    tmp_path: Path,
) -> None:
    architecture, machine = _runtime_architecture()
    library = tmp_path / "libclntsh.so.19.1"
    library.write_bytes(_elf_header(machine))

    assert inspect_oracle_client(str(tmp_path)) == (
        "19c",
        architecture,
    )
    subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            str(library),
            "--runtime-architecture",
            architecture,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    wrong_dir = tmp_path / "wrong"
    wrong_dir.mkdir()
    wrong_version = wrong_dir / "libclntsh.so.23.1"
    wrong_version.write_bytes(_elf_header(machine))
    with pytest.raises(ResolutionError, match="19c"):
        inspect_oracle_client(str(wrong_dir))
    failed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            str(wrong_version),
            "--runtime-architecture",
            architecture,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0


def test_oracle_archive_detection_ignores_non_19c(
    tmp_path: Path,
) -> None:
    archive_19 = tmp_path / "instantclient-19.zip"
    with zipfile.ZipFile(archive_19, "w") as archive:
        archive.writestr(
            "instantclient_19_25/libclntsh.so.19.1",
            b"placeholder",
        )
    found = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            "--find-in-archive",
            str(archive_19),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert found.stdout.strip().endswith("libclntsh.so.19.1")

    archive_23 = tmp_path / "instantclient-23.zip"
    with zipfile.ZipFile(archive_23, "w") as archive:
        archive.writestr(
            "instantclient_23_26/libclntsh.so.23.1",
            b"placeholder",
        )
    ignored = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            "--find-in-archive",
            str(archive_23),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode != 0


def test_oracle_image_layout_is_fail_closed_and_shell_is_valid() -> None:
    dockerfile = DOCKERFILE.read_text()
    setup = SETUP_SCRIPT.read_text()
    readme = README.read_text()

    assert "verify_oracle_client.py" in dockerfile
    assert "setup_oracle_client.sh" in dockerfile
    assert "libclntsh.so.19" in setup
    assert "--find-in-archive" in setup
    assert "19c" in readme
    assert "必须保持 blocked" in readme
    subprocess.run(
        ["bash", "-n", str(SETUP_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
    )
