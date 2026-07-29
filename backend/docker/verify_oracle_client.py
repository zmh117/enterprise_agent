#!/usr/bin/env python3
"""Fail closed unless an Oracle Instant Client library is approved for runtime."""

from __future__ import annotations

import argparse
import platform
import re
import stat
import zipfile
from pathlib import Path


def normalize_architecture(value: str) -> str:
    return {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }.get(value.strip().lower(), value.strip().lower())


def inspect_library(
    library: Path,
    *,
    runtime_architecture: str,
) -> tuple[str, str]:
    resolved = library.resolve()
    if ".so.19" not in resolved.name:
        raise ValueError("Oracle Instant Client 19c is required")
    with resolved.open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise ValueError("Oracle client library is not ELF")
    if header[4] != 2:
        raise ValueError("Oracle client library must be 64-bit")
    byte_order = "little" if header[5] == 1 else "big" if header[5] == 2 else ""
    if not byte_order:
        raise ValueError("Oracle client ELF byte order is invalid")
    machine = int.from_bytes(header[18:20], byte_order)
    architecture = {62: "x86_64", 183: "aarch64"}.get(machine)
    if architecture is None:
        raise ValueError(f"Unsupported Oracle client ELF machine: {machine}")
    expected = normalize_architecture(runtime_architecture)
    if architecture != expected:
        raise ValueError(
            "Oracle client architecture does not match container architecture"
        )
    return "19c", architecture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path, nargs="?")
    parser.add_argument("--find-in-archive", type=Path)
    parser.add_argument(
        "--runtime-architecture",
        default=platform.machine(),
    )
    args = parser.parse_args()
    if args.find_in_archive is not None:
        try:
            with zipfile.ZipFile(args.find_in_archive) as archive:
                member = next(
                    (
                        info.filename
                        for info in archive.infolist()
                        if not stat.S_ISLNK(info.external_attr >> 16)
                        and re.search(
                            r"(^|/)libclntsh[.]so[.]19([.]|$)",
                            info.filename,
                        )
                    ),
                    "",
                )
        except (OSError, zipfile.BadZipFile):
            return 1
        if not member:
            return 1
        print(member)
        return 0
    if args.library is None:
        parser.error("library is required")
    try:
        version, architecture = inspect_library(
            args.library,
            runtime_architecture=args.runtime_architecture,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"approved Oracle Instant Client: {version} {architecture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
