"""Oracle Instant Client (thick mode) process-level initialization."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ...domain.errors import ResolutionError
from ...domain.topology import OracleClientMode

_log = logging.getLogger("internal_api_platform.oracle_client")


class ThickInitState(str, Enum):
    UNINITIALIZED = "uninitialized"
    THICK = "thick"
    THIN_ONLY = "thin_only"
    FAILED = "failed"


@dataclass
class ThickInitResult:
    state: ThickInitState
    lib_dir: str = ""
    error: str = ""


_lock = threading.Lock()
_result = ThickInitResult(state=ThickInitState.UNINITIALIZED)


def reset_oracle_client_state_for_tests() -> None:
    """Test helper: clear process-level thick init state."""

    global _result
    with _lock:
        _result = ThickInitResult(state=ThickInitState.UNINITIALIZED)


def thick_init_result() -> ThickInitResult:
    with _lock:
        return ThickInitResult(state=_result.state, lib_dir=_result.lib_dir, error=_result.error)


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
    return any(
        name.startswith("libclntsh") or name.endswith(".so") or ".so." in name
        for name in names
    )


def ensure_oracle_client_initialized(*, force_attempt: bool = False) -> ThickInitResult:
    """Initialize oracledb thick mode once per process when Instant Client is present.

    - Libraries present + init OK → THICK
    - No libraries → THIN_ONLY (local/dev without Instant Client)
    - Libraries present but init fails → FAILED
    """

    global _result
    with _lock:
        if _result.state is not ThickInitState.UNINITIALIZED and not force_attempt:
            return ThickInitResult(state=_result.state, lib_dir=_result.lib_dir, error=_result.error)

        lib_dir = resolve_oracle_client_lib_dir()
        if not lib_dir:
            _result = ThickInitResult(state=ThickInitState.THIN_ONLY)
            _log.info("Oracle Instant Client not found; staying in thin mode")
            return ThickInitResult(state=_result.state)

        try:
            import oracledb
        except ModuleNotFoundError as exc:
            _result = ThickInitResult(
                state=ThickInitState.FAILED,
                lib_dir=lib_dir,
                error=f"Oracle driver is not installed: {exc}",
            )
            return ThickInitResult(state=_result.state, lib_dir=lib_dir, error=_result.error)

        try:
            oracledb.init_oracle_client(lib_dir=lib_dir)
        except Exception as exc:  # pragma: no cover - depends on native libs
            # Already initialized in this process is OK.
            message = str(exc).lower()
            if "already been initialized" in message or "already initialized" in message:
                _result = ThickInitResult(state=ThickInitState.THICK, lib_dir=lib_dir)
                return ThickInitResult(state=_result.state, lib_dir=lib_dir)
            _result = ThickInitResult(
                state=ThickInitState.FAILED,
                lib_dir=lib_dir,
                error=f"{type(exc).__name__}: {exc}",
            )
            _log.error("Oracle Instant Client init failed: %s", _result.error)
            return ThickInitResult(state=_result.state, lib_dir=lib_dir, error=_result.error)

        _result = ThickInitResult(state=ThickInitState.THICK, lib_dir=lib_dir)
        _log.info("Oracle Instant Client initialized from %s", lib_dir)
        return ThickInitResult(state=_result.state, lib_dir=lib_dir)


def assert_oracle_client_mode_ready(mode: OracleClientMode) -> None:
    """Enforce client mode policy before connecting.

    - thick: Instant Client must be successfully initialized (no silent thin fallback)
    - auto: prefer thick when available; otherwise thin
    - thin: do not require Instant Client
    """

    if mode is OracleClientMode.THIN:
        return

    result = ensure_oracle_client_initialized()
    if mode is OracleClientMode.THICK:
        if result.state is ThickInitState.THICK:
            return
        if result.state is ThickInitState.THIN_ONLY:
            raise ResolutionError(
                "Oracle thick mode required but Instant Client libraries were not found "
                "(set ORACLE_CLIENT_LIB_DIR or use the internal-api-platform image)"
            )
        raise ResolutionError(
            "Oracle thick mode required but Instant Client initialization failed"
            + (f": {result.error}" if result.error else "")
        )
    # auto: thick if available, else thin — never raise solely for missing libs
    if result.state is ThickInitState.FAILED:
        # Libraries were present but broken; surface the failure rather than guessing thin.
        raise ResolutionError(
            "Oracle Instant Client initialization failed"
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
        return connect_descriptor.strip()
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
        return oracledb.makedsn(host, port, sid=database)
    return oracledb.makedsn(host, port, service_name=database)
