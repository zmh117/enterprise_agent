"""Oracle Instant Client (thick mode) process-level initialization."""

from __future__ import annotations

import logging
import os
import platform
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from ...domain.errors import ResolutionError
from ...domain.topology import OracleClientMode

_log = logging.getLogger("mcp_tool_runtime.oracle_client")


class ThickInitState(str, Enum):
    UNINITIALIZED = "uninitialized"
    THICK = "thick"
    THIN_ONLY = "thin_only"
    FAILED = "failed"


@dataclass
class ThickInitResult:
    state: ThickInitState
    lib_dir: str = ""
    client_version: str = ""
    architecture: str = ""
    error: str = ""


_lock = threading.RLock()
_result = ThickInitResult(state=ThickInitState.UNINITIALIZED)


def reset_oracle_client_state_for_tests() -> None:
    """Test helper: clear process-level thick init state."""

    global _result
    with _lock:
        _result = ThickInitResult(state=ThickInitState.UNINITIALIZED)


def thick_init_result() -> ThickInitResult:
    with _lock:
        return ThickInitResult(
            state=_result.state,
            lib_dir=_result.lib_dir,
            client_version=_result.client_version,
            architecture=_result.architecture,
            error=_result.error,
        )


def resolve_oracle_client_lib_dir() -> str:
    explicit = os.getenv("ORACLE_CLIENT_LIB_DIR", "").strip()
    candidates = [explicit] if explicit else []
    candidates.append("/opt/oracle/instantclient")
    for path in candidates:
        if path and _looks_like_instant_client_dir(path):
            return path
    return ""


def _looks_like_instant_client_dir(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        names = os.listdir(path)
    except OSError:
        return False
    return any(name.startswith("libclntsh.so") for name in names)


def inspect_oracle_client(
    lib_dir: str,
) -> tuple[str, str]:
    """Return the approved Instant Client version and ELF architecture.

    Oracle 11.2.0.4 support in this platform is deliberately pinned to the
    64-bit Instant Client 19c ABI. A missing, 32-bit, mismatched-architecture,
    or non-19c library fails before python-oracledb initialization.
    """

    candidates = sorted(Path(lib_dir).glob("libclntsh.so*"))
    if not candidates:
        raise ResolutionError("Oracle Instant Client libclntsh was not found")
    versioned = [candidate for candidate in candidates if ".so.19" in candidate.resolve().name]
    if not versioned:
        raise ResolutionError("Oracle Instant Client 19c is required")
    library = versioned[0].resolve()
    try:
        with library.open("rb") as stream:
            header = stream.read(20)
    except OSError as exc:
        raise ResolutionError("Oracle Instant Client library could not be inspected") from exc
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise ResolutionError("Oracle Instant Client library is not an ELF binary")
    if header[4] != 2:
        raise ResolutionError("Oracle Instant Client must be 64-bit")
    byte_order: Literal["little", "big"]
    if header[5] == 1:
        byte_order = "little"
    elif header[5] == 2:
        byte_order = "big"
    else:
        raise ResolutionError("Oracle Instant Client ELF byte order is invalid")
    machine = int.from_bytes(header[18:20], byte_order)
    architectures = {62: "x86_64", 183: "aarch64"}
    client_architecture = architectures.get(machine, f"elf_machine_{machine}")
    runtime_architecture = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }.get(platform.machine().lower(), platform.machine().lower())
    if client_architecture != runtime_architecture:
        raise ResolutionError("Oracle Instant Client architecture does not match the runtime")
    return "19c", client_architecture


def ensure_oracle_client_initialized(*, force_attempt: bool = False) -> ThickInitResult:
    """Initialize oracledb thick mode once per process when Instant Client is present.

    - Libraries present + init OK → THICK
    - No libraries → THIN_ONLY (local/dev without Instant Client)
    - Libraries present but init fails → FAILED
    """

    global _result
    with _lock:
        if _result.state is not ThickInitState.UNINITIALIZED and not force_attempt:
            return thick_init_result()

        lib_dir = resolve_oracle_client_lib_dir()
        if not lib_dir:
            _result = ThickInitResult(state=ThickInitState.THIN_ONLY)
            _log.info("Oracle Instant Client 19c not found; Oracle is unavailable")
            return ThickInitResult(state=_result.state)

        try:
            client_version, architecture = inspect_oracle_client(lib_dir)
        except ResolutionError as exc:
            _result = ThickInitResult(
                state=ThickInitState.FAILED,
                lib_dir=lib_dir,
                error=str(exc),
            )
            return thick_init_result()

        try:
            import oracledb
        except ModuleNotFoundError as exc:
            _result = ThickInitResult(
                state=ThickInitState.FAILED,
                lib_dir=lib_dir,
                error=f"Oracle driver is not installed: {exc}",
            )
            return thick_init_result()

        try:
            oracledb.init_oracle_client(lib_dir=lib_dir)
        except Exception as exc:  # pragma: no cover - depends on native libs
            # Already initialized in this process is OK.
            message = str(exc).lower()
            if "already been initialized" in message or "already initialized" in message:
                if oracledb.is_thin_mode():
                    _result = ThickInitResult(
                        state=ThickInitState.FAILED,
                        lib_dir=lib_dir,
                        error="python-oracledb remained in Thin mode",
                    )
                    return thick_init_result()
                _result = ThickInitResult(
                    state=ThickInitState.THICK,
                    lib_dir=lib_dir,
                    client_version=client_version,
                    architecture=architecture,
                )
                return thick_init_result()
            _result = ThickInitResult(
                state=ThickInitState.FAILED,
                lib_dir=lib_dir,
                error=f"{type(exc).__name__}: {exc}",
            )
            _log.error("Oracle Instant Client init failed: %s", _result.error)
            return thick_init_result()

        if oracledb.is_thin_mode():
            _result = ThickInitResult(
                state=ThickInitState.FAILED,
                lib_dir=lib_dir,
                error="python-oracledb remained in Thin mode",
            )
            return thick_init_result()
        _result = ThickInitResult(
            state=ThickInitState.THICK,
            lib_dir=lib_dir,
            client_version=client_version,
            architecture=architecture,
        )
        _log.info("Oracle Instant Client initialized from %s", lib_dir)
        return thick_init_result()


def assert_oracle_client_mode_ready(mode: OracleClientMode) -> None:
    """Enforce client mode policy before connecting.

    Oracle 11g resources are always Thick. Legacy auto/thin values fail closed.
    """

    if mode is not OracleClientMode.THICK:
        raise ResolutionError("Oracle 11g requires explicit Thick client mode")
    result = ensure_oracle_client_initialized()
    if result.state is ThickInitState.THICK:
        return
    if result.state is ThickInitState.THIN_ONLY:
        raise ResolutionError("Oracle 11g requires 64-bit Instant Client 19c Thick mode")
    raise ResolutionError(
        "Oracle Instant Client 19c Thick initialization failed"
        + (f": {result.error}" if result.error else "")
    )


def build_oracle_dsn(
    *,
    host: str,
    port: int,
    database: str,
    use_sid: bool = False,
    connect_descriptor: str = "",
) -> str:
    if connect_descriptor.strip():
        raise ResolutionError("Arbitrary Oracle connect descriptors are not allowed")
    if use_sid:
        return f"{host}:{port}/{database}"
    # Easy Connect service name form (default).
    return f"{host}:{port}/{database}"


def build_oracle_makedsn(
    oracledb: Any,
    *,
    host: str,
    port: int,
    database: str,
    use_sid: bool,
) -> str:
    if use_sid:
        return str(oracledb.makedsn(host, port, sid=database))
    return str(oracledb.makedsn(host, port, service_name=database))
