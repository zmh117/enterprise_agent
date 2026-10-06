from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import gzip
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock
import zlib

import pytest
from mcp import types

from app.modules.agent.infrastructure.tool_manifest import TOOL_DEFINITIONS
from app.modules.mcp_tool_runtime.domain.addressing import ResourceBinding
from app.modules.mcp_tool_runtime.domain.errors import PolicyViolation
from app.modules.mcp_tool_runtime.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    ResourceKind,
)
from app.modules.mcp_tool_runtime.infrastructure.db import drivers, value_decoder
from app.modules.mcp_tool_runtime.infrastructure.db.drivers import _rows_from_cursor
from app.modules.mcp_tool_runtime.infrastructure.db.value_decoder import (
    CHUNK_BYTES,
    DecodeBudget,
    InputBudgetExceeded,
    decode_value,
)
from app.modules.mcp_tool_runtime.service import _storage_summary
from app.modules.mcp_tool_runtime.contracts import ToolResult
from app.python_runtime.job_sandbox import JobSandboxError, JobSandboxManager
from app.python_runtime.tool_result_bridge import ToolResultBridge, materialize_tool_result
from app.services.tool_mcp import ToolMcpError, _bounded_result
from app.shared.query_result_contract import QUERY_RESULT_MAX_BYTES
from app.shared.exceptions import ToolPolicyError
from app.shared.tool_contract import tool_schema_hash
from app.shared.tool_response_summary import tool_response_summary


def _wrap(raw, carrier):
    if carrier == "base64":
        return base64.b64encode(raw).decode("ascii")
    if carrier == "hex":
        return raw.hex()
    if carrier == "hex_prefix":
        return "0X" + raw.hex().upper()
    if carrier == "base64_bytes":
        return base64.b64encode(raw)
    if carrier == "hex_bytes":
        return raw.hex().encode("ascii")
    if carrier == "bytearray":
        return bytearray(raw)
    if carrier == "memoryview":
        return memoryview(raw)
    return raw


@pytest.mark.parametrize(
    "text", ["", "PI 的显示内容\n合成记录", '{"nested":"ordinary"}', "x" * 100000]
)
@pytest.mark.parametrize(
    "carrier",
    ["raw", "bytearray", "memoryview", "base64", "hex", "hex_prefix", "base64_bytes", "hex_bytes"],
)
def test_supported_carriers_preserve_exact_utf8_string(text, carrier):
    original = _wrap(zlib.compress(text.encode()), carrier)
    projected, facts = decode_value(original, DecodeBudget())
    assert type(projected) is str and projected == text
    assert facts["status"] == "decoded"
    assert facts["decoded_size_bytes"] == len(text.encode())


@pytest.mark.parametrize(
    "value",
    [
        None,
        7,
        True,
        2.5,
        "ordinary" * 10000,
        "eJ-fake-prefix",
        "",
        "YWJjZA==",
        "789cZZ",
        "0x123",
        "0x78 9c",
    ],
)
def test_ordinary_values_are_unchanged(value):
    assert decode_value(value, DecodeBudget()) == (value, None)


@pytest.mark.parametrize("carrier", ["raw", "base64", "hex", "base64_bytes"])
@pytest.mark.parametrize(
    "failure", ["checksum", "truncated", "trailing", "multistream", "dictionary", "encoding"]
)
def test_failed_candidates_preserve_whole_original(carrier, failure):
    raw = zlib.compress(b"synthetic-content")
    status = "invalid_zlib"
    if failure == "checksum":
        raw = raw[:-1] + bytes([raw[-1] ^ 1])
    elif failure == "truncated":
        raw = raw[:-2]
    elif failure == "trailing":
        raw += b"tail"
    elif failure == "multistream":
        raw += zlib.compress(b"second")
    elif failure == "dictionary":
        stream = zlib.compressobj(zdict=b"synthetic-dictionary")
        raw = stream.compress(b"synthetic-dictionary-text") + stream.flush()
        status = "unsupported_dictionary"
    else:
        raw = zlib.compress("中文".encode("gbk"))
        status = "unsupported_text_encoding"
    original = _wrap(raw, carrier)
    projected, facts = decode_value(original, DecodeBudget())
    assert facts["status"] == status and "decoded_size_bytes" not in facts
    if isinstance(original, str):
        assert projected == original
    else:
        assert projected == {
            "type": "binary",
            "encoding": "base64",
            "data": base64.b64encode(original).decode(),
            "size_bytes": len(original),
        }


def test_noncanonical_base64_and_unsupported_compression_are_not_candidates():
    # Change unused pad bits without changing decoded bytes.
    raw = zlib.compress(b"xx")
    canonical = base64.b64encode(raw).decode()
    assert canonical.endswith("==")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    altered = canonical[:-3] + alphabet[alphabet.index(canonical[-3]) + 1] + "=="
    assert base64.b64decode(altered) == raw
    for value in [
        altered,
        canonical[:-1],
        canonical + "\n",
        " " + canonical,
        canonical[:-2] + "__",
    ]:
        assert decode_value(value, DecodeBudget()) == (value, None)
    raw_stream = zlib.compressobj(wbits=-15)
    raw_deflate = raw_stream.compress(b"synthetic") + raw_stream.flush()
    for binary in [gzip.compress(b"synthetic"), raw_deflate, b"PK\x03\x04synthetic"]:
        projection, facts = decode_value(binary, DecodeBudget())
        assert facts["status"] == "binary_uninterpreted"
        assert base64.b64decode(projection["data"]) == binary
    nested = base64.b64encode(zlib.compress(b"inner")).decode()
    assert decode_value(zlib.compress(nested.encode()), DecodeBudget())[0] == nested


@pytest.mark.parametrize("size", [99, 100, 101])
def test_exact_expansion_boundary_and_one_probe(size, monkeypatch):
    real = zlib.decompressobj
    calls = []

    class RecordingStream:
        def __init__(self):
            self.stream = real()

        def decompress(self, data, max_length):
            calls.append(max_length)
            assert max_length > 0
            return self.stream.decompress(data, max_length)

        def __getattr__(self, name):
            return getattr(self.stream, name)

    monkeypatch.setattr(value_decoder.zlib, "decompressobj", RecordingStream)
    budget = DecodeBudget(max_bytes=100)
    projected, facts = decode_value(zlib.compress(b"x" * size), budget)
    assert budget.expanded_bytes == min(100, size)
    assert sum(calls) <= 101
    if size <= 100:
        assert projected == "x" * size and facts["status"] == "decoded"
    else:
        assert isinstance(projected, dict) and facts["status"] == "decode_limit_exceeded"


def test_failed_expansion_and_input_consumption_are_not_restored():
    budget = DecodeBudget(max_bytes=100)
    _, facts = decode_value(zlib.compress(b"\xff" * 80), budget)
    assert facts["status"] == "unsupported_text_encoding"
    assert budget.expanded_bytes == 80
    original = base64.b64encode(zlib.compress(b"x" * 30)).decode()
    assert decode_value(original, budget) == (
        original,
        {
            "status": "decode_limit_exceeded",
            "input_format": "base64_zlib",
            "input_size_bytes": len(original),
        },
    )
    assert budget.expanded_bytes == 100
    later = base64.b64encode(zlib.compress(b"small")).decode()
    assert decode_value(later, budget)[1]["status"] == "decode_limit_exceeded"
    with pytest.raises(InputBudgetExceeded):
        decode_value("x" * 100, budget)
    assert budget.input_bytes == 12 + len(original) + len(later)


def test_checksum_failure_charges_reserved_expansion_budget():
    raw = zlib.compress(b"x" * 20)
    budget = DecodeBudget(max_bytes=100)
    assert decode_value(raw[:-1] + b"\x00", budget)[1]["status"] == "invalid_zlib"
    assert budget.expanded_bytes == 100


def test_expansion_high_ratio_chunking_and_deadline(monkeypatch):
    raw = zlib.compress(b"x" * (QUERY_RESULT_MAX_BYTES + 1))
    budget = DecodeBudget()
    projected, facts = decode_value(raw, budget)
    assert isinstance(projected, dict) and facts["status"] == "decode_limit_exceeded"
    assert budget.expanded_bytes == QUERY_RESULT_MAX_BYTES
    with pytest.raises(TimeoutError, match="timed out"):
        decode_value(raw, DecodeBudget(deadline=time.monotonic() - 1))
    monkeypatch.setattr(value_decoder.time, "monotonic", Mock(side_effect=[0, 0, 0, 0, 2]))
    with pytest.raises(TimeoutError):
        decode_value(raw, DecodeBudget(deadline=1))


class Cursor:
    def __init__(self, rows, columns=("alias_content",)):
        self.rows = list(rows)
        self.description = [(column,) for column in columns]
        self.fetches = []
        self.statements = []
        self.connection = None
        self.closes = 0

    def fetchmany(self, count):
        assert count == 1
        self.fetches.append(count)
        rows, self.rows = self.rows[:count], self.rows[count:]
        return rows

    def execute(self, sql):
        self.statements.append(sql)

    def close(self):
        self.closes += 1


def _rows(cursor, cap=QUERY_RESULT_MAX_BYTES, **kwargs):
    return _rows_from_cursor(cursor, 100, max_response_bytes=cap, **kwargs)


def _payload(result):
    data = {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": len(result.rows),
        "complete": not result.truncated,
        "truncation_reasons": ["provider_result_truncated"] if result.truncated else [],
    }
    if result.field_decoding is not None:
        data["field_decoding"] = result.field_decoding
    return {"data": data, "truncated": result.truncated, "metadata": {}}


def test_rows_and_diagnostics_fit_atomically_and_size_is_exact():
    raw = zlib.compress(b"synthetic")
    first = _rows(Cursor([(raw,)]))
    expected = {
        "columns": first.columns,
        "rows": first.rows,
        "field_decoding": first.field_decoding,
    }
    assert first.response_bytes == len(
        json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode()
    )
    cursor = Cursor([(raw,), (raw,), (b"do-not-fetch",)])
    result = _rows(cursor, first.response_bytes)
    assert result.rows == first.rows and result.field_decoding == first.field_decoding
    assert result.truncated and len(cursor.fetches) == 2
    no_fit = _rows(Cursor([(raw,)]), first.response_bytes - 1)
    assert no_fit.rows == [] and no_fit.field_decoding is None and no_fit.truncated


def test_binary_fallback_expansion_and_cumulative_input_reject_entire_row(monkeypatch):
    raw = b"not-zlib" * 30
    result = _rows(Cursor([(raw,)]), len(raw) + 50)
    assert result.rows == [] and result.field_decoding is None and result.truncated
    monkeypatch.setattr(drivers, "DecodeBudget", lambda **kw: DecodeBudget(max_bytes=20, **kw))
    cursor = Cursor([("中文中文",), ("x" * 9,), ("never",)])
    result = _rows(cursor)
    assert result.rows == [{"alias_content": "中文中文"}] and result.truncated
    assert len(cursor.fetches) == 2


class Lob:
    def __init__(self, value, *, size=None, kind="BLOB", owner=None, fail=None):
        self.value = value
        self.declared_size = len(value) if size is None else size
        self.type = kind
        self.owner = owner
        self.fail = fail
        self.sizes = 0
        self.reads = []

    def size(self):
        self.sizes += 1
        assert self.owner is None or not self.owner.closed
        return self.declared_size

    def read(self, *, offset, amount):
        assert self.owner is None or not self.owner.closed
        self.reads.append((offset, amount))
        if self.fail:
            raise RuntimeError("synthetic-private-body")
        return self.value[offset - 1 : offset - 1 + amount]

    def __str__(self):
        raise AssertionError("A LOB locator must never be stringified")


ORACLE = SimpleNamespace(LOB=Lob, DB_TYPE_BLOB="BLOB")


def test_oracle_blob_is_chunked_size_checked_and_sensitive_cell_is_never_read():
    blob = Lob(b"ordinary-binary" * 10000)
    secret = Lob(zlib.compress(b"synthetic-secret"))
    result = _rows(Cursor([(blob, secret)], ("content", "access_token")), oracle=ORACLE)
    assert base64.b64decode(result.rows[0]["content"]["data"]) == blob.value
    assert blob.sizes == 2 and len(blob.reads) > 1
    assert all(amount <= CHUNK_BYTES for _, amount in blob.reads)
    assert result.rows[0]["access_token"] == "[REDACTED]"
    assert secret.sizes == 0 and secret.reads == []
    oversized = Lob(b"", size=QUERY_RESULT_MAX_BYTES + 1)
    result = _rows(Cursor([(oversized,)]), oracle=ORACLE)
    assert result.truncated and result.rows == [] and oversized.reads == []


@pytest.mark.parametrize("kind", ["BFILE", "CLOB", "NCLOB"])
def test_other_oracle_lobs_are_rejected_without_read_or_stringification(kind):
    blob = Lob(b"synthetic", kind=kind)
    with pytest.raises(PolicyViolation, match="unsupported LOB"):
        _rows(Cursor([(blob,)]), oracle=ORACLE)
    assert blob.reads == [] and blob.sizes == 0


def test_unknown_read_object_is_not_read_and_extra_row_blob_not_materialized():
    class Unknown:
        read = Mock(side_effect=AssertionError("Must not be read"))

        def __str__(self):
            return "unknown-value"

    unknown = Unknown()
    result = _rows(Cursor([(unknown,)]), oracle=ORACLE)
    assert result.rows == [{"alias_content": "unknown-value"}]
    unknown.read.assert_not_called()
    extra = Lob(b"unused")
    cursor = Cursor([(zlib.compress(b"ok"),), (extra,)])
    result = _rows_from_cursor(cursor, 1, max_response_bytes=1000, oracle=ORACLE)
    assert result.truncated and result.rows == [{"alias_content": "ok"}]
    assert extra.sizes == 0 and extra.reads == []


@pytest.mark.parametrize("failure", ["read_error", "short", "wrong_type", "changed_size"])
def test_blob_failures_never_return_partial_values(failure):
    blob = Lob(b"synthetic", size=20 if failure == "short" else None, fail=failure == "read_error")
    if failure == "wrong_type":
        blob.read = Mock(return_value="not-bytes")
    elif failure == "changed_size":
        blob.size = Mock(side_effect=[9, 10])
    with pytest.raises((PolicyViolation, RuntimeError)):
        _rows(Cursor([(blob,)]), oracle=ORACLE)


def _driver(monkeypatch, engine, cursor):
    connection = SimpleNamespace(closed=False, cursor=lambda: cursor)
    cursor.connection = connection

    def close():
        connection.closed = True

    connection.close = close
    connect = Mock(return_value=connection)
    mysql = SimpleNamespace(connect=connect, cursors=SimpleNamespace(SSCursor=object))
    oracle = SimpleNamespace(
        connect=connect, LOB=Lob, DB_TYPE_BLOB="BLOB", makedsn=lambda *a, **kw: "synthetic-dsn"
    )
    module = {"mysql": mysql, "sqlserver": SimpleNamespace(connect=connect), "oracle": oracle}[
        engine
    ]
    monkeypatch.setitem(
        sys.modules,
        {"mysql": "pymysql", "sqlserver": "pymssql", "oracle": "oracledb"}[engine],
        module,
    )
    monkeypatch.setattr(drivers, "assert_oracle_client_mode_ready", lambda _: None)
    db = DatabaseConnection(
        host="synthetic.invalid", port=1, database="synthetic", user="synthetic", password=""
    )
    base = Base(code="test", engine=DatabaseEngine(engine), database=db)
    binding = ResourceBinding(
        environment=Environment(code="test"),
        base=base,
        kind=ResourceKind.DATABASE,
        workshop=None,
        engine=base.engine,
        database=db,
    )
    executor = {
        "mysql": drivers.MysqlExecutor,
        "sqlserver": drivers.SqlServerExecutor,
        "oracle": drivers.OracleExecutor,
    }[engine]()
    return executor, binding, connection, connect, module


@pytest.mark.parametrize("engine", ["mysql", "sqlserver", "oracle"])
@pytest.mark.parametrize("carrier", ["raw", "base64", "hex"])
def test_all_drivers_decode_inside_connection_and_close(monkeypatch, engine, carrier):
    raw = zlib.compress("合成 PI".encode())
    value = _wrap(raw, carrier)
    if engine == "sqlserver" and carrier == "raw":
        value = raw  # Driver may return bytes; string wrapping covered in other cases.
    cursor = Cursor([])
    executor, binding, connection, connect, module = _driver(monkeypatch, engine, cursor)
    if engine == "oracle":
        value = Lob(value.encode() if isinstance(value, str) else value, owner=connection)
    cursor.rows = [(value,)]
    result = executor.execute(binding, "SELECT synthetic", timeout_seconds=10, max_rows=5)
    assert result.rows == [{"alias_content": "合成 PI"}]
    assert result.field_decoding["decoded_count"] == 1 and connection.closed
    assert cursor.fetches == [1, 1]
    if engine == "mysql":
        assert connect.call_args.kwargs["cursorclass"] is module.cursors.SSCursor
        assert cursor.closes == 0 and cursor.connection is None
    if engine == "oracle":
        assert cursor.arraysize == 1 and cursor.prefetchrows == 1
        assert value.reads and connection.call_timeout == 10000


@pytest.mark.parametrize("engine", ["mysql", "sqlserver", "oracle"])
def test_driver_errors_hide_body_and_close_connection(monkeypatch, engine, caplog):
    cursor = Cursor([])
    executor, binding, connection, _, _ = _driver(monkeypatch, engine, cursor)
    cursor.fetchmany = Mock(side_effect=RuntimeError("synthetic-private-body"))
    with pytest.raises(PolicyViolation) as error:
        executor.execute(binding, "SELECT synthetic", timeout_seconds=1, max_rows=5)
    assert connection.closed and "synthetic-private-body" not in str(error.value)
    assert "synthetic-private-body" not in caplog.text
    import traceback

    assert "synthetic-private-body" not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("engine", ["mysql", "sqlserver", "oracle"])
def test_driver_deadline_failure_is_stable_and_closes_connection(monkeypatch, engine):
    cursor = Cursor([])
    executor, binding, connection, _, _ = _driver(monkeypatch, engine, cursor)
    cursor.fetchmany = Mock(side_effect=TimeoutError("synthetic-private-body"))
    with pytest.raises(ToolPolicyError) as error:
        executor.execute(binding, "SELECT synthetic", timeout_seconds=1, max_rows=5)
    assert error.value.error_code == "database_query_timeout" and connection.closed
    assert "synthetic-private-body" not in error.value.safe_message


def test_many_rows_mixed_diagnostics_and_aliases_have_exact_size():
    result = _rows(
        Cursor(
            [(zlib.compress(b"ok"), b"ordinary"), ("plain", zlib.compress(b"\xff")), ("x", None)],
            ("renamed", "other_alias"),
        )
    )
    expected = {
        "columns": result.columns,
        "rows": result.rows,
        "field_decoding": result.field_decoding,
    }
    assert result.response_bytes == len(
        json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert result.field_decoding["candidate_count"] == 2
    assert len(result.field_decoding["cells"]) == 3
    assert [(cell["row_index"], cell["column"]) for cell in result.field_decoding["cells"]] == [
        (0, "renamed"),
        (0, "other_alias"),
        (1, "other_alias"),
    ]


def test_direct_query_projects_driver_diagnostics_with_existing_contract():
    from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
    from app.modules.mcp_tool_runtime.domain.schema_directory import SchemaColumn, SchemaTable
    from app.modules.mcp_tool_runtime.infrastructure.db.schema_directory import (
        FakeSchemaInspector,
        SchemaInspectorFactory,
    )
    from app.shared.config import ExecutionSettings
    from backend.tests.test_tool_pagination import _ResolvedDatabaseResourceResolver, _context

    executed = _rows(Cursor([(zlib.compress(b"synthetic"),)]))
    executor = DirectReadOnlyToolExecutor(
        _ResolvedDatabaseResourceResolver(), limits=ExecutionSettings()
    )
    executor.schema_inspectors = SchemaInspectorFactory(
        {
            DatabaseEngine.MYSQL: FakeSchemaInspector(
                [SchemaTable("orders", [SchemaColumn("content", "mediumblob", True)])]
            )
        }
    )
    provider = SimpleNamespace(execute=Mock(return_value=executed))
    executor.executors[DatabaseEngine.MYSQL] = provider
    result = executor.query_database(
        "",
        "select content as alias_content from orders",
        100,
        _context(),
        environment="prod",
        base="main",
    )
    assert result.summary["rows"] == executed.rows
    assert result.summary["field_decoding"] == executed.field_decoding
    assert result.raw == {"row_count": 1} and result.summary["tables"] == ["orders"]
    assert provider.execute.call_args.kwargs["max_rows"] == 100


def test_sensitive_bytes_and_decoded_plaintext_are_redacted_before_return():
    raw = zlib.compress(b'{"password":"synthetic-secret", "visible":"ok"}')
    result = _rows(Cursor([(raw, raw)], ("content", "password")))
    assert result.rows[0]["password"] == "[REDACTED]"
    assert json.loads(result.rows[0]["content"]) == {"password": "[REDACTED]", "visible": "ok"}
    assert len(result.field_decoding["cells"]) == 1
    assert "synthetic-secret" not in json.dumps(result.rows)


def test_file_query_and_decoding_completeness_are_independent(tmp_path):
    raw = zlib.compress(b"synthetic-private-body")
    bad = raw[:-2]
    result = _rows(Cursor([(raw,), (bad,), (b"ordinary",)]))
    payload = _payload(result)
    sandbox = JobSandboxManager(tmp_path).create("job-decoding")
    summary = materialize_tool_result(sandbox, "query_database", payload)
    assert summary["complete"] and summary["file_complete"]
    assert not summary["field_decoding"]["complete"]
    assert summary["field_decoding"]["candidate_count"] == 2
    assert (
        summary["field_decoding"]["decoded_count"] == summary["field_decoding"]["failed_count"] == 1
    )
    assert "cells" not in summary["field_decoding"] and "synthetic-private-body" not in json.dumps(
        summary
    )
    saved = (sandbox.path / summary["result_file"]).read_text()
    assert "synthetic-private-body" in saved and '"cells"' in saved
    sandbox.authorize_tool("Read", {"file_path": summary["result_file"]})
    for tool in ["Write", "Edit"]:
        with pytest.raises(JobSandboxError):
            sandbox.authorize_tool(tool, {"file_path": summary["result_file"], "content": "x"})
    other = JobSandboxManager(tmp_path).create("another-job")
    with pytest.raises(JobSandboxError):
        other.authorize_tool("Read", {"file_path": summary["result_file"]})
    sandbox.cleanup()
    other.cleanup()
    assert not sandbox.path.exists()
    assert tool_response_summary(payload)["field_decoding"] == summary["field_decoding"]
    legacy = _storage_summary(
        ToolResult(summary=payload["data"], raw={}), tool_name="query_database"
    )
    assert "synthetic-private-body" not in json.dumps(legacy) and "cells" not in json.dumps(legacy)


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "status",
        "format",
        "index",
        "column",
        "duplicate",
        "count",
        "complete",
        "size",
        "decoded_size",
        "boolean_count",
        "null",
        "extra",
        "wrong_body",
    ],
)
def test_invalid_diagnostics_fail_before_publishing(tmp_path, mutation):
    payload = _payload(_rows(Cursor([(zlib.compress(b"synthetic"),)])))
    decoding = payload["data"]["field_decoding"]
    cell = decoding["cells"][0]
    if mutation == "version":
        decoding["policy_version"] = "unknown"
    elif mutation in {"status", "format"}:
        cell["status" if mutation == "status" else "input_format"] = []
    elif mutation == "index":
        cell["row_index"] = 1
    elif mutation == "column":
        cell["column"] = "unknown"
    elif mutation == "duplicate":
        decoding["cells"].append(deepcopy(cell))
    elif mutation == "count":
        decoding["candidate_count"] = 0
    elif mutation == "complete":
        decoding["complete"] = False
    elif mutation == "size":
        cell["input_size_bytes"] = QUERY_RESULT_MAX_BYTES + 1
    elif mutation == "decoded_size":
        cell["decoded_size_bytes"] = True
    elif mutation == "boolean_count":
        decoding["decoded_count"] = True
    elif mutation == "null":
        payload["data"]["field_decoding"] = None
    elif mutation == "extra":
        cell["body"] = "synthetic-private-body"
    else:
        payload["data"]["rows"][0]["alias_content"] = {}
    sandbox = JobSandboxManager(tmp_path).create("invalid-decoding")
    with pytest.raises(ValueError):
        materialize_tool_result(sandbox, "query_database", payload)
    assert not list((sandbox.path / "work").iterdir())
    sandbox.cleanup()


def test_binary_fallback_validation_legacy_compatibility_and_query_truncation(tmp_path):
    result = _rows(Cursor([(b"ordinary-binary",)]))
    payload = _payload(result)
    sandbox = JobSandboxManager(tmp_path).create("binary-decoding")
    summary = materialize_tool_result(sandbox, "query_database", payload)
    assert summary["field_decoding"]["candidate_count"] == 0
    payload["data"]["rows"][0]["alias_content"]["size_bytes"] += 1
    with pytest.raises(ValueError):
        materialize_tool_result(sandbox, "query_database", payload)
    legacy = {"data": {"columns": ["id"], "rows": [{"id": 1}], "row_count": 1}, "truncated": False}
    assert "field_decoding" not in materialize_tool_result(sandbox, "query_database", legacy)
    decoded = _payload(_rows(Cursor([(zlib.compress(b"ok"),)])))
    decoded["truncated"] = True
    decoded["data"]["complete"] = False
    decoded["data"]["truncation_reasons"] = ["provider_result_truncated"]
    summary = materialize_tool_result(sandbox, "query_database", decoded)
    assert (
        summary["file_complete"]
        and summary["field_decoding"]["complete"]
        and not summary["complete"]
    )
    sandbox.cleanup()


def test_final_envelope_cap_still_includes_decoding_metadata():
    payload = _payload(_rows(Cursor([(zlib.compress(b"x"),)])))
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    assert _bounded_result(payload, max_bytes=len(encoded)) == payload
    with pytest.raises(ToolMcpError):
        _bounded_result(payload, max_bytes=len(encoded) - 1)


def test_bridge_preserves_safe_audit_handle_on_invalid_decoding(tmp_path):
    async def run():
        payload = _payload(_rows(Cursor([(zlib.compress(b"synthetic-private-body"),)])))
        payload["data"]["field_decoding"]["complete"] = False
        schema = TOOL_DEFINITIONS["query_database"]["schema"]
        session = SimpleNamespace(
            initialize=Mock(),
            list_tools=Mock(),
            call_tool=Mock(),
        )

        async def initialize():
            pass

        async def list_tools(**kwargs):
            return types.ListToolsResult(
                tools=[types.Tool(name="query_database", inputSchema=schema)]
            )

        async def call_tool(*args, **kwargs):
            return types.CallToolResult.model_validate(
                {
                    "content": [],
                    "structuredContent": payload,
                    "_meta": {"enterprise-agent/mcp-call-id": "audit-decoding"},
                }
            )

        session.initialize, session.list_tools, session.call_tool = (
            initialize,
            list_tools,
            call_tool,
        )
        sandbox = JobSandboxManager(tmp_path).create("bridge-decoding")
        bridge = ToolResultBridge(
            sdk=SimpleNamespace(create_sdk_mcp_server=lambda **kw: {"instance": object()}),
            url="http://synthetic.invalid",
            headers={},
            frozen={"query_database": tool_schema_hash(schema)},
            sandbox=sandbox,
            timeout=1,
            session=session,
        )
        await bridge.connect()
        result = (await bridge.call_tool("query_database", {})).model_dump(by_alias=True)
        assert (
            result["isError"]
            and result["structuredContent"]["error_code"]
            == "resource_query_result_materialization_failed"
        )
        assert result["_meta"]["enterprise-agent/mcp-call-id"] == "audit-decoding"
        assert "synthetic-private-body" not in json.dumps(result)
        assert not list((sandbox.path / "work").iterdir())
        sandbox.cleanup()

    asyncio.run(run())
