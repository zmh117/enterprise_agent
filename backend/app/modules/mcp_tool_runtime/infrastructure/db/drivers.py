from __future__ import annotations

import json
from typing import Any

from app.shared.database import assert_external_io_allowed

from ...domain.addressing import ResourceBinding
from ...domain.errors import PolicyViolation, ResolutionError, UpstreamUnavailable
from ...domain.topology import OracleClientMode
from .executor import ExecutedRows
from .oracle_client import (
    assert_oracle_client_mode_ready,
    build_oracle_dsn,
    build_oracle_makedsn,
)


def _require_db(binding: ResourceBinding) -> Any:
    if binding.database is None:
        raise ResolutionError("Base has no database connection configured")
    return binding.database


def _rows_from_cursor(
    cursor: Any,
    max_rows: int,
    *,
    max_response_bytes: int,
) -> ExecutedRows:
    fetched = cursor.fetchmany(max_rows + 1)
    columns = [desc[0] for desc in (cursor.description or [])]
    truncated = len(fetched) > max_rows
    rows: list[dict[str, Any]] = []
    response_bytes = 0
    for raw_row in fetched[:max_rows]:
        row = dict(zip(columns, raw_row))
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
        if response_bytes + len(encoded) > max_response_bytes:
            truncated = True
            break
        rows.append(row)
        response_bytes += len(encoded)
    return ExecutedRows(
        columns=columns,
        rows=rows,
        truncated=truncated,
        response_bytes=response_bytes,
    )


class MysqlExecutor:
    def __init__(self, *, max_response_bytes: int = 1024 * 1024) -> None:
        self.max_response_bytes = max_response_bytes

    def execute(
        self, binding: ResourceBinding, sql: str, *, timeout_seconds: int, max_rows: int
    ) -> ExecutedRows:
        assert_external_io_allowed("tool_database.mysql")
        db = _require_db(binding)
        try:
            import pymysql
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise UpstreamUnavailable("MySQL driver is not installed") from exc
        try:
            conn = pymysql.connect(
                host=db.host,
                port=db.port,
                user=db.user,
                password=db.password,
                database=db.database or None,
                connect_timeout=timeout_seconds,
                read_timeout=timeout_seconds,
                cursorclass=pymysql.cursors.Cursor,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable(f"MySQL connection failed: {type(exc).__name__}") from exc
        try:
            with conn.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {timeout_seconds * 1000}")
                cursor.execute(sql)
                return _rows_from_cursor(
                    cursor,
                    max_rows,
                    max_response_bytes=self.max_response_bytes,
                )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise PolicyViolation(f"MySQL query failed: {type(exc).__name__}") from exc
        finally:
            conn.close()


class SqlServerExecutor:
    def __init__(self, *, max_response_bytes: int = 1024 * 1024) -> None:
        self.max_response_bytes = max_response_bytes

    def execute(
        self, binding: ResourceBinding, sql: str, *, timeout_seconds: int, max_rows: int
    ) -> ExecutedRows:
        assert_external_io_allowed("tool_database.sqlserver")
        db = _require_db(binding)
        try:
            import pymssql
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise UpstreamUnavailable("SQL Server driver is not installed") from exc
        try:
            conn = pymssql.connect(
                server=db.host,
                port=str(db.port),
                user=db.user,
                password=db.password,
                database=db.database or None,
                login_timeout=timeout_seconds,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable(
                f"SQL Server connection failed: {type(exc).__name__}"
            ) from exc
        try:
            cursor = conn.cursor()
            cursor.execute(f"SET LOCK_TIMEOUT {timeout_seconds * 1000}")
            cursor.execute(sql)
            return _rows_from_cursor(
                cursor,
                max_rows,
                max_response_bytes=self.max_response_bytes,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise PolicyViolation(f"SQL Server query failed: {type(exc).__name__}") from exc
        finally:
            conn.close()


class OracleExecutor:
    def __init__(self, *, max_response_bytes: int = 1024 * 1024) -> None:
        self.max_response_bytes = max_response_bytes

    def execute(
        self, binding: ResourceBinding, sql: str, *, timeout_seconds: int, max_rows: int
    ) -> ExecutedRows:
        assert_external_io_allowed("tool_database.oracle")
        db = _require_db(binding)
        try:
            assert_oracle_client_mode_ready(OracleClientMode.THICK)
        except ResolutionError:
            raise
        try:
            import oracledb
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise UpstreamUnavailable("Oracle driver is not installed") from exc

        connect_descriptor = str(getattr(db, "connect_descriptor", "") or "")
        if connect_descriptor.strip():
            raise ResolutionError("Arbitrary Oracle connect descriptors are not allowed")
        use_sid = bool(getattr(db, "use_sid", False))
        if connect_descriptor.strip():
            dsn = build_oracle_dsn(
                host=db.host,
                port=db.port,
                database=db.database,
                use_sid=use_sid,
                connect_descriptor=connect_descriptor,
            )
        else:
            dsn = build_oracle_makedsn(
                oracledb,
                host=db.host,
                port=db.port,
                database=db.database,
                use_sid=use_sid,
            )
        try:
            conn = oracledb.connect(
                user=db.user,
                password=db.password,
                dsn=dsn,
            )
            conn.call_timeout = timeout_seconds * 1000
            schema = str(getattr(db, "schema", "") or "").strip()
            if schema:
                if not schema.replace("_", "").isalnum():
                    raise ResolutionError("Oracle schema contains invalid characters")
                cursor = conn.cursor()
                cursor.execute(f'ALTER SESSION SET CURRENT_SCHEMA = "{schema}"')
                cursor.close()
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable(f"Oracle connection failed: {type(exc).__name__}") from exc
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            return _rows_from_cursor(
                cursor,
                max_rows,
                max_response_bytes=self.max_response_bytes,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise PolicyViolation(f"Oracle query failed: {type(exc).__name__}") from exc
        finally:
            conn.close()
