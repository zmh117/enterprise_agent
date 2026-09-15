from __future__ import annotations

import importlib.util
import os
import platform
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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


def _detect_client(vendor: Path, verifier: Path) -> subprocess.CompletedProcess[str]:
    # Run the real discovery code only: never write /etc, install packages or
    # remove vendor files on the test host. Full installation needs a container.
    discovery, separator, _ = SETUP_SCRIPT.read_text().partition('mkdir -p "${INSTALL_DIR}"')
    assert separator
    return subprocess.run(
        ["bash", "-c", discovery + '\nprintf "%s" "${client_zip}"\n'],
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "ORACLE_VENDOR_DIR": str(vendor),
            "ORACLE_CLIENT_VERIFIER": str(verifier),
        },
        check=False,
        capture_output=True,
        text=True,
    )


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
    assert ignored.returncode == 3
    assert ignored.stdout == ""
    assert ignored.stderr == ""


@pytest.mark.parametrize("executable", [False, True])
def test_oracle_discovery_accepts_crlf_verifier_and_paths_with_spaces(
    tmp_path: Path,
    executable: bool,
) -> None:
    vendor = tmp_path / "vendor with spaces"
    vendor.mkdir()
    archive_path = vendor / "instantclient 19.12.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("instantclient_19_12/libclntsh.so.19.1", b"placeholder")
    verifier = tmp_path / "verify client.py"
    verifier.write_bytes(VERIFY_SCRIPT.read_text().replace("\n", "\r\n").encode())
    verifier.chmod(0o755 if executable else 0o644)

    result = _detect_client(vendor, verifier)

    assert result.returncode == 0, result.stderr
    assert result.stdout == str(archive_path)
    assert archive_path.exists()


@pytest.mark.parametrize("non_19c_archive", [False, True])
def test_oracle_discovery_can_skip_absent_or_unsupported_client(
    tmp_path: Path,
    non_19c_archive: bool,
) -> None:
    if non_19c_archive:
        with zipfile.ZipFile(tmp_path / "instantclient-23.zip", "w") as archive:
            archive.writestr("instantclient_23/libclntsh.so.23.1", b"placeholder")

    result = _detect_client(tmp_path, VERIFY_SCRIPT)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("failure_code", [1, 2, 126, 127])
def test_oracle_discovery_does_not_swallow_detector_failure(
    tmp_path: Path,
    failure_code: int,
) -> None:
    with zipfile.ZipFile(tmp_path / "client.zip", "w") as archive:
        archive.writestr("instantclient_19_12/libclntsh.so.19.1", b"placeholder")
    verifier = tmp_path / "failing_verifier.py"
    verifier.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        f"raise SystemExit(0 if '--help' in sys.argv else {failure_code})\n"
    )
    verifier.chmod(0o755)

    result = _detect_client(tmp_path, verifier)

    assert result.returncode == failure_code
    assert "Oracle client archive detection failed" in result.stderr


@pytest.mark.parametrize("broken_script", [False, True])
def test_oracle_discovery_requires_working_verifier_even_without_archives(
    tmp_path: Path,
    broken_script: bool,
) -> None:
    verifier = tmp_path / "invalid_verifier.py"
    if broken_script:
        verifier.write_text("this is invalid python\n")

    result = _detect_client(tmp_path, verifier)

    assert result.returncode != 0
    assert "Oracle client verifier cannot run" in result.stderr


@pytest.mark.parametrize("corrupt_archive", [False, True])
def test_oracle_archive_read_failure_is_not_no_match(
    tmp_path: Path,
    corrupt_archive: bool,
) -> None:
    archive_path = tmp_path / "bad.zip"
    if corrupt_archive:
        archive_path.write_bytes(b"not a zip file")
    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), "--find-in-archive", str(archive_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Oracle client archive cannot be read" in result.stderr
    if corrupt_archive:
        discovery = _detect_client(tmp_path, VERIFY_SCRIPT)
        assert discovery.returncode == 2
        assert "Oracle client archive detection failed" in discovery.stderr


@pytest.mark.parametrize("wrong_bits", [False, True])
def test_crlf_verifier_keeps_elf_architecture_and_64_bit_checks(
    tmp_path: Path,
    wrong_bits: bool,
) -> None:
    architecture, machine = _runtime_architecture()
    library = tmp_path / "libclntsh.so.19.1"
    library.write_bytes(
        _elf_header(
            machine if wrong_bits else (183 if machine == 62 else 62), bits=32 if wrong_bits else 64
        )
    )
    verifier = tmp_path / "verify.py"
    verifier.write_bytes(VERIFY_SCRIPT.read_text().replace("\n", "\r\n").encode())
    result = subprocess.run(
        [sys.executable, str(verifier), str(library), "--runtime-architecture", architecture],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert ("64-bit" if wrong_bits else "architecture") in result.stderr


def test_oracle_image_layout_is_fail_closed_and_shell_is_valid() -> None:
    dockerfile = DOCKERFILE.read_text()
    setup = SETUP_SCRIPT.read_text()
    readme = README.read_text()

    assert "verify_oracle_client.py" in dockerfile
    assert "setup_oracle_client.sh" in dockerfile
    assert "backend/docker/*.py text eol=lf" in (ROOT / ".gitattributes").read_text()
    normalize = r"sed -i 's/\r$//' /tmp/setup_oracle_client.sh /tmp/verify_oracle_client.py"
    assert normalize in dockerfile
    invocation = "ORACLE_VENDOR_DIR=/tmp/oracle-vendor bash /tmp/setup_oracle_client.sh"
    assert dockerfile.index(normalize) < dockerfile.index(invocation)
    assert '\n"${VERIFIER}"' not in setup
    assert setup.count('python "${VERIFIER}"') == 4
    assert "--load-client" in setup
    assert 'LD_LIBRARY_PATH="${INSTALL_DIR}' in setup
    assert "ldconfig || true" not in setup
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


@pytest.mark.parametrize(
    "scenario",
    [
        "t64",
        "legacy",
        "loadable",
        "missing",
        "existing",
        "dangling",
        "replay",
        "query_error",
        "ambiguous",
    ],
)
def test_libaio_compatibility_link_is_private_and_does_not_overwrite(
    tmp_path: Path,
    scenario: str,
) -> None:
    source = SETUP_SCRIPT.read_text()
    signature = "configure_libaio_compatibility() {"
    assert signature in source
    body, end, _ = source.split(signature, 1)[1].partition("\n}\n")
    assert end
    install = tmp_path / "oracle client"
    install.mkdir()
    target = tmp_path / "system libs" / "libaio.so.1t64"
    target.parent.mkdir()
    target.write_bytes(b"package owned fixture")
    link = install / "libaio.so.1"
    if scenario == "missing":
        target.unlink()
    elif scenario == "existing":
        link.write_bytes(b"preserve this file")
    elif scenario == "dangling":
        link.symlink_to(tmp_path / "absent library")
    elif scenario == "replay":
        link.symlink_to(target)
    # Isolate only this function; no apt, /etc or cleanup runs on the test host.
    script = (
        signature
        + body
        + "\n}\n"
        + """
set -euo pipefail
python() { return "${TEST_LOAD_STATUS}"; }
dpkg-query() {
  if [[ "${TEST_QUERY_STATUS}" != 0 ]]; then return "${TEST_QUERY_STATUS}"; fi
  printf '%s\n' "${TEST_LIBAIO_TARGET}"
}
configure_libaio_compatibility "${TEST_PACKAGE}" "${TEST_INSTALL}"
"""
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "TEST_INSTALL": str(install),
            "TEST_LIBAIO_TARGET": str(target)
            + ("\n" + str(target) if scenario == "ambiguous" else ""),
            "TEST_PACKAGE": "libaio1" if scenario == "legacy" else "libaio1t64",
            "TEST_LOAD_STATUS": "0" if scenario == "loadable" else "1",
            "TEST_QUERY_STATUS": "1" if scenario == "query_error" else "0",
        },
    )
    if scenario in {"missing", "query_error", "ambiguous"}:
        assert result.returncode != 0
        assert not link.exists()
    else:
        assert result.returncode == 0, result.stderr
        if scenario in {"legacy", "loadable"}:
            assert not link.exists()
        elif scenario == "existing":
            assert not link.is_symlink()
            assert link.read_bytes() == b"preserve this file"
        elif scenario == "dangling":
            assert link.readlink() == tmp_path / "absent library"
        else:
            assert link.is_symlink()
            assert link.resolve() == target
    if target.exists():
        assert target.read_bytes() == b"package owned fixture"


@pytest.mark.parametrize("outcome", ["success", "thin", "wrong_version", "load_error"])
def test_build_verifier_requires_real_thick_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
) -> None:
    spec = importlib.util.spec_from_file_location("oracle_build_verifier", VERIFY_SCRIPT)
    assert spec is not None and spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    _, machine = _runtime_architecture()
    library = tmp_path / "libclntsh.so.19.1"
    library.write_bytes(_elf_header(machine))
    init = Mock(side_effect=RuntimeError("missing libaio") if outcome == "load_error" else None)
    driver = SimpleNamespace(
        init_oracle_client=init,
        is_thin_mode=lambda: outcome == "thin",
        clientversion=lambda: (23 if outcome == "wrong_version" else 19, 12, 0, 0, 0),
    )
    monkeypatch.setitem(sys.modules, "oracledb", driver)
    monkeypatch.setattr(sys, "argv", [str(VERIFY_SCRIPT), str(library), "--load-client"])
    if outcome == "success":
        assert verifier.main() == 0
        assert "verified Oracle Thick client: 19.12.0.0.0" in capsys.readouterr().out
    else:
        with pytest.raises(SystemExit) as failure:
            verifier.main()
        assert failure.value.code == 2
        assert "Oracle Thick initialization failed" in capsys.readouterr().err
    init.assert_called_once_with()
