from __future__ import annotations

import json
import time
from typing import Any

from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import ToolPolicyError
from app.shared.query_result_contract import FIELD_DECODING_POLICY
from app.shared.secret_redaction import REDACTED, is_sensitive_key, sanitize_for_persistence

from ...domain.addressing import ResourceBinding
from ...domain.errors import PolicyViolation, ResolutionError, UpstreamUnavailable
from ...domain.topology import OracleClientMode
from .executor import ExecutedRows
from .oracle_client import (
    assert_oracle_client_mode_ready,
    build_oracle_dsn,
    build_oracle_makedsn,
)
from .value_decoder import CHUNK_BYTES, DecodeBudget, InputBudgetExceeded, decode_value


def _require_db(binding: ResourceBinding) -> Any:
    if binding.database is None:
        raise ResolutionError("Base has no database connection configured")
    return binding.database


def _json_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    )


def _oracle_value(value: Any, oracle: Any, budget: DecodeBudget) -> Any:
    if not isinstance(value, oracle.LOB):
        return value
    if value.type != oracle.DB_TYPE_BLOB:
        # LOB.__str__ can read CLOB/BFILE. Never pass a live locator to serialization.
        raise PolicyViolation("Database result contains an unsupported LOB type")
    budget.check_time()
    size = value.size()
    if type(size) is not int or size < 0:
        raise PolicyViolation("Database BLOB size is invalid")
    budget.check_input_size(size)
    parts: list[bytes] = []
    offset = 0
    while offset < size:
        budget.check_time()
        amount = min(CHUNK_BYTES, size - offset)
        part = value.read(offset=offset + 1, amount=amount)
        budget.check_time()
        if not isinstance(part, bytes) or not part or len(part) > amount:
            raise PolicyViolation("Database BLOB read was incomplete")
        parts.append(part)
        offset += len(part)
    if value.size() != size:
        raise PolicyViolation("Database BLOB size changed during read")
    budget.check_time()
    return b"".join(parts)


def _rows_from_cursor(  # noqa: PLR0915
    cursor: Any,
    max_rows: int,
    *,
    max_response_bytes: int,
    deadline: float | None = None,
    oracle: Any = None,
) -> ExecutedRows:
    columns = [desc[0] for desc in (cursor.description or [])]
    budget = DecodeBudget(deadline=deadline)
    truncated = False
    rows: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {
        "policy_version": FIELD_DECODING_POLICY,
        "candidate_count": 0,
        "decoded_count": 0,
        "failed_count": 0,
        "complete": True,
        "cells": [],
    }
    base_bytes = _json_size({"columns": columns, "rows": []})
    row_bytes = cell_bytes = 0
    response_bytes = base_bytes
    while len(rows) < max_rows:
        budget.check_time()
        fetched = cursor.fetchmany(1)
        budget.check_time()
        if not fetched:
            break
        row = dict(zip(columns, fetched[0]))
        row_cells: list[dict[str, Any]] = []
        try:
            for column, value in row.items():
                if is_sensitive_key(column):
                    row[column] = REDACTED
                    continue
                value = _oracle_value(value, oracle, budget) if oracle is not None else value
                row[column], facts = decode_value(value, budget)
                if facts is not None:
                    row_cells.append({"row_index": len(rows), "column": column, **facts})
        except InputBudgetExceeded:
            truncated = True
            break
        row = sanitize_for_persistence(row)
        next_row_bytes = row_bytes + _json_size(row) + bool(rows)
        next_cell_bytes = cell_bytes + sum(_json_size(cell) for cell in row_cells)
        next_cell_bytes += len(row_cells) - (0 if cells else bool(row_cells))
        next_metadata = {**metadata}
        for cell in row_cells:
            if cell["status"] != "binary_uninterpreted":
                next_metadata["candidate_count"] += 1
                next_metadata["decoded_count"] += cell["status"] == "decoded"
        next_metadata["failed_count"] = (
            next_metadata["candidate_count"] - next_metadata["decoded_count"]
        )
        next_metadata["complete"] = next_metadata["failed_count"] == 0
        proposed_bytes = base_bytes + next_row_bytes
        if cells or row_cells:
            proposed_bytes += (
                len(',"field_decoding":') + _json_size(next_metadata) + next_cell_bytes
            )
        budget.check_time()
        if proposed_bytes > max_response_bytes:
            truncated = True
            break
        rows.append(row)
        cells.extend(row_cells)
        metadata = next_metadata
        row_bytes, cell_bytes, response_bytes = next_row_bytes, next_cell_bytes, proposed_bytes
    else:
        # Probe for coverage only; don't adapt/read the extra row's BLOB locators.
        budget.check_time()
        truncated = bool(cursor.fetchmany(1))
        budget.check_time()
    metadata["cells"] = cells
    return ExecutedRows(
        columns=columns,
        rows=rows,
        truncated=truncated,
        response_bytes=response_bytes,
        field_decoding=metadata if cells else None,
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
                cursorclass=pymysql.cursors.SSCursor,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable(f"MySQL connection failed: {type(exc).__name__}") from None
        cursor = None
        try:
            deadline = time.monotonic() + timeout_seconds
            cursor = conn.cursor()
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {timeout_seconds * 1000}")
            cursor.execute(sql)
            return _rows_from_cursor(
                cursor,
                max_rows,
                max_response_bytes=self.max_response_bytes,
                deadline=deadline,
            )
        except TimeoutError:
            raise ToolPolicyError(
                "Database result processing timed out",
                safe_message="数据库查询结果处理超时，请缩小查询范围",
                error_code="database_query_timeout",
            ) from None
        except Exception as exc:  # pragma: no cover - needs live DB
            raise PolicyViolation(f"MySQL query failed: {type(exc).__name__}") from None
        finally:
            # SSCursor.close/__del__ drains unread rows. Detach it, then close the
            # dedicated connection/socket without reading any remaining result.
            if cursor is not None:
                cursor.connection = None
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
                database=db.database or "",
                login_timeout=timeout_seconds,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable(
                f"SQL Server connection failed: {type(exc).__name__}"
            ) from None
        try:
            deadline = time.monotonic() + timeout_seconds
            cursor = conn.cursor()
            cursor.execute(f"SET LOCK_TIMEOUT {timeout_seconds * 1000}")
            cursor.execute(sql)
            return _rows_from_cursor(
                cursor,
                max_rows,
                max_response_bytes=self.max_response_bytes,
                deadline=deadline,
            )
        except TimeoutError:
            raise ToolPolicyError(
                "Database result processing timed out",
                safe_message="数据库查询结果处理超时，请缩小查询范围",
                error_code="database_query_timeout",
            ) from None
        except Exception as exc:  # pragma: no cover - needs live DB
            raise PolicyViolation(f"SQL Server query failed: {type(exc).__name__}") from None
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
        conn = None
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
            if conn is not None:
                conn.close()
            raise UpstreamUnavailable(f"Oracle connection failed: {type(exc).__name__}") from None
        try:
            deadline = time.monotonic() + timeout_seconds
            cursor = conn.cursor()
            cursor.arraysize = 1
            cursor.prefetchrows = 1
            cursor.execute(sql)
            return _rows_from_cursor(
                cursor,
                max_rows,
                max_response_bytes=self.max_response_bytes,
                deadline=deadline,
                oracle=oracledb,
            )
        except TimeoutError:
            raise ToolPolicyError(
                "Database result processing timed out",
                safe_message="数据库查询结果处理超时，请缩小查询范围",
                error_code="database_query_timeout",
            ) from None
        except Exception as exc:  # pragma: no cover - needs live DB
            raise PolicyViolation(f"Oracle query failed: {type(exc).__name__}") from None
        finally:
            conn.close()
