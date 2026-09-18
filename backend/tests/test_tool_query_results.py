from __future__ import annotations

import asyncio
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mcp import types

from app.modules.agent.infrastructure.tool_manifest import TOOL_DEFINITIONS
from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.infrastructure.loki_client import summarize_loki_response
from app.modules.mcp_tool_runtime.infrastructure.loki_schemas import LokiQuery
from app.modules.mcp_tool_runtime.resource_resolver import DirectResourceResolver
from app.modules.platform_config.domain.provider_contracts import ProviderContractRegistry
from app.modules.platform_config.application.database_resource_verifier import LokiResourceProbe
from app.modules.platform_config.application.loki_draft_discovery import (
    HttpLokiDraftDiscoveryGateway,
)
from app.modules.mcp_tool_runtime.infrastructure.loki_gateway import HttpLokiClient
from app.modules.mcp_tool_runtime.domain.errors import PolicyViolation
from app.modules.platform_config.application.runtime_config import (
    validate_runtime_config_value_bounds,
)
from app.modules.platform_config.application.validation import PlatformConfigValidationError
from app.python_runtime.job_sandbox import JobSandboxManager, JobSandboxError
from app.python_runtime.tool_result_bridge import ToolResultBridge, materialize_tool_result
from app.services.tool_mcp import _bounded_result, ToolMcpError
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError, NonRetryableExecutionError
from app.shared.loki_contract import assert_loki_query_limits
from app.shared.query_result_contract import QUERY_RESULT_MAX_BYTES
from app.shared.tool_contract import tool_schema_hash
from backend.tests.test_loki_line_limits import _resource_config, _service, _call
from backend.tests.test_tool_pagination import (
    _RowsDatabase,
    _resource,
    _SecretMustNotResolve,
    _context,
)
from backend.tests.test_tool_pagination import _ResolvedDatabaseResourceResolver
from app.modules.mcp_tool_runtime.domain.topology import DatabaseEngine
from app.modules.mcp_tool_runtime.domain.schema_directory import SchemaColumn, SchemaTable
from app.modules.mcp_tool_runtime.infrastructure.db.executor import FakeQueryExecutor
from app.modules.mcp_tool_runtime.infrastructure.db.schema_directory import (
    FakeSchemaInspector,
    SchemaInspectorFactory,
)
from app.shared.secret_redaction import redact_sensitive_text
from app.modules.mcp_tool_runtime.contracts import ResourceAccessGrant


def _payload(name="query_loki", count=1):
    if name in {"query_loki", "diagnose_loki_probe"}:
        data = {"highlights": ["正文" * 3000] * count, "line_count": count}
    elif name == "query_database":
        data = {"columns": ["id"], "rows": [{"id": i} for i in range(count)], "row_count": count}
    elif name == "query_redis_scan":
        data = {
            "keys": [f"allowed:{i}" for i in range(count)],
            "has_more": False,
            "next_cursor": "",
        }
    else:
        data = {"key": "allowed:1", "value_summary": "正文" * 3000}
    return {"data": data, "metadata": {}, "truncated": False}


@pytest.mark.parametrize(
    "name,count",
    [
        ("query_loki", 1),
        ("diagnose_loki_probe", 1),
        ("query_database", 10000),
        ("query_redis_scan", 200),
        ("query_redis_get", 1),
    ],
)
def test_full_query_results_are_readonly_job_files(tmp_path, name, count):
    sandbox = JobSandboxManager(tmp_path).create("job-query")
    try:
        payload = _payload(name, count)
        result = materialize_tool_result(sandbox, name, payload)
        assert result["returned"] == count
        assert result["file_complete"] and result["complete"]
        path = sandbox.path / result["result_file"]
        saved = json.loads(path.read_text().split("```json\n")[1].split("\n```", 1)[0])
        assert saved == payload
        assert "正文" not in json.dumps(result, ensure_ascii=False)
        sandbox.authorize_tool("Read", {"file_path": result["result_file"]})
        with pytest.raises(JobSandboxError):
            sandbox.authorize_tool("Write", {"file_path": result["result_file"], "content": "x"})
    finally:
        sandbox.cleanup()
    assert not sandbox.path.exists()


def test_redis_continuation_is_preserved_without_claiming_complete(tmp_path):
    sandbox = JobSandboxManager(tmp_path).create("job-query")
    payload = _payload("query_redis_scan")
    payload["data"].update(has_more=True, next_cursor="opaque-page")
    payload["truncated"] = True
    result = materialize_tool_result(sandbox, "query_redis_scan", payload)
    assert result["next_cursor"] == "opaque-page"
    assert result["file_complete"] and not result["complete"]
    assert result["truncation_reasons"] == ["more_pages"]


def test_loki_never_drops_long_lines_and_marks_limit():
    query = LokiQuery(selector={"app": "test"}, query="", minutes=15, limit=2, logql="{}")
    lines = ["a" * 6000, "b" * 6000]
    body = {"data": {"result": [{"stream": {}, "values": [["1", line] for line in lines]}]}}
    result = summarize_loki_response(body, query, 4000)
    assert result.summary["highlights"] == lines
    assert result.truncated
    assert result.summary["truncation_reasons"] == ["line_limit_reached"]


@pytest.mark.parametrize("minutes", [1, 1440, 43200])
def test_thirty_day_resource_and_platform_config(minutes):
    config = {**_resource_config(10000), "max_minutes": minutes}
    assert (
        ProviderContractRegistry()
        .normalize(provider_type="loki", config=config)
        .config["max_minutes"]
        == minutes
    )
    assert validate_runtime_config_value_bounds("MAX_LOKI_MINUTES", minutes) == minutes


@pytest.mark.parametrize("minutes", [0, 43201])
def test_thirty_day_ceiling(minutes):
    with pytest.raises(PlatformConfigValidationError):
        validate_runtime_config_value_bounds("MAX_LOKI_MINUTES", minutes)
    with pytest.raises(PlatformConfigValidationError):
        ProviderContractRegistry().normalize(
            provider_type="loki", config={**_resource_config(10000), "max_minutes": minutes}
        )


def test_loki_all_tools_accept_configured_thirty_days_and_ten_thousand():
    for name in (
        "query_loki",
        "diagnose_loki_probe",
        "diagnose_loki_labels",
        "diagnose_loki_label_values",
    ):
        service, requests = _service(10000, 10000)
        service.limits = replace(service.limits, max_loki_minutes=43200)
        client = service.tool_executor._loki.return_value
        client._max_minutes = 43200
        resource = service.tool_executor._resolve.return_value
        resource.binding.loki = replace(resource.binding.loki, max_minutes=43200)
        _call(service, name, minutes=43200, limit=10000)
        assert len(requests) == 1


@pytest.mark.parametrize("legacy_bytes", [None, 1024, 10485760])
def test_effective_limits_directory_does_not_resolve_secrets(legacy_bytes):
    config = _resource_config(500)
    if legacy_bytes is not None:
        config["max_response_bytes"] = legacy_bytes
    row = {
        **_resource(1),
        "resource_kind": "loki",
        "placement": "",
        "config_json": json.dumps(config),
        "scope_bindings_json": json.dumps(
            [{"environment_code": "prod", "base_code": "", "workshop_code": ""}]
        ),
    }
    executor = DirectReadOnlyToolExecutor(
        DirectResourceResolver(_RowsDatabase([row]), secret_provider=_SecretMustNotResolve()),
        limits=replace(ExecutionSettings(), max_loki_minutes=30),
    )
    result = executor.list_available_tool_resources(
        _context(),
        grants=(
            ResourceAccessGrant(
                tool_identifier="query_loki",
                resource_kind="loki",
                environment="prod",
            ),
        ),
    )
    limits = result.summary["resources"][0]["effective_limits"]
    assert limits["max_lines"] == 500 and limits["max_minutes"] == 30
    assert limits["max_response_bytes"] == QUERY_RESULT_MAX_BYTES
    assert "base_url" not in json.dumps(result.summary)
    with pytest.raises(ToolPolicyError) as error:
        assert_loki_query_limits(minutes=60, limit=100, max_minutes=30, max_lines=500)
    assert error.value.error_code == "loki_time_range_exceeded"
    assert "30" in error.value.safe_message


@pytest.mark.parametrize("legacy_bytes", [None, 1024, 10485760])
def test_loki_retired_byte_setting_is_not_required_retained_or_projected(legacy_bytes):
    registry = ProviderContractRegistry()
    config = _resource_config(1000)
    if legacy_bytes is not None:
        config["max_response_bytes"] = legacy_bytes
    original = dict(config)
    document = registry.normalize(provider_type="loki", config=config)
    assert config == original
    assert "max_response_bytes" not in document.config
    assert all(field["name"] != "max_response_bytes" for field in registry.require("loki").fields)
    # Existing Published Revisions are projected directly, without normalization.
    legacy_document = replace(document, config=original)
    assert "max_response_bytes" not in registry.runtime_projection(
        legacy_document, resolve_secret=lambda _: pytest.fail("Unexpected secret lookup")
    )


@pytest.mark.parametrize("path", ["query", "discovery", "verification"])
@pytest.mark.parametrize("oversized", [False, True])
def test_loki_http_paths_use_fixed_platform_budget(path, oversized):
    reads = []
    body = (
        b" " * (QUERY_RESULT_MAX_BYTES + 1)
        if oversized
        else json.dumps(
            {"status": "success", "data": [], "padding": "x" * (2 * 1024 * 1024)}
        ).encode()
    )

    class Response(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def fetch(*args, **kwargs):
        return Response(body)

    config = {**_resource_config(1000), "max_response_bytes": 1024}
    if path == "query":
        client = HttpLokiClient(
            max_minutes=60, max_lines=1000, max_response_chars=4000, urlopen_func=fetch
        )
        connection = SimpleNamespace(**config, tenant_id="", auth_token="")

        def invoke():
            return client._fetch_json(
                SimpleNamespace(loki=connection), "/loki/api/v1/query_range", {}
            )
    elif path == "discovery":
        gateway = HttpLokiDraftDiscoveryGateway(resolve_secret=lambda _: "", urlopen_func=fetch)

        def invoke():
            return gateway._fetch(config, "/loki/api/v1/labels", {})
    else:
        config["scope_bindings"] = [{"selector_conditions": {"customer": "test"}}]
        probe = LokiResourceProbe(fetch)

        def invoke():
            return probe._verify_scope_bindings(config, headers={}, timeout_seconds=5)

    if oversized:
        with pytest.raises((PolicyViolation, RuntimeError, NonRetryableExecutionError)):
            invoke()
    else:
        invoke()
    assert reads == [QUERY_RESULT_MAX_BYTES + 1]


def test_result_bytes_independent_of_inline_budget():
    payload = _payload("query_redis_get")
    payload["data"]["value_summary"] = "a" * (600 * 1024)
    with pytest.raises(ToolMcpError):
        _bounded_result(payload)
    assert _bounded_result(payload, max_bytes=QUERY_RESULT_MAX_BYTES) == payload


@pytest.mark.parametrize("limit", [100, 10000])
def test_database_executor_does_not_clamp_explicit_limit(limit):
    executor = DirectReadOnlyToolExecutor(
        _ResolvedDatabaseResourceResolver(), limits=ExecutionSettings()
    )
    executor.schema_inspectors = SchemaInspectorFactory(
        {
            DatabaseEngine.MYSQL: FakeSchemaInspector(
                [
                    SchemaTable("orders", [SchemaColumn("id", "bigint", False)]),
                ]
            )
        }
    )
    provider = FakeQueryExecutor([{"id": i} for i in range(10001)])
    executor.executors[DatabaseEngine.MYSQL] = provider
    result = executor.query_database(
        "", "select id from orders", limit, _context(), environment="prod", base="main"
    )
    assert result.summary["row_count"] == limit
    assert f"LIMIT {limit}" in provider.calls[0][1]
    assert result.truncated
    with pytest.raises(ToolPolicyError):
        executor.query_database(
            "", "select id from orders", 10001, _context(), environment="prod", base="main"
        )
    assert len(provider.calls) == 1


def test_large_text_redaction_preserves_nonsecret_content():
    text = "x" * (600 * 1024)
    assert redact_sensitive_text(text) == text
    redacted = redact_sensitive_text(
        text + " https://user:synthetic-password@example.invalid/path token=synthetic-token"
    )
    assert redacted.startswith(text)
    assert "synthetic-password" not in redacted and "synthetic-token" not in redacted


def test_bridge_rejects_oversized_result_before_file_creation(tmp_path):
    sandbox = JobSandboxManager(tmp_path).create("job-query")
    payload = _payload("query_redis_get")
    payload["data"]["value_summary"] = "x" * QUERY_RESULT_MAX_BYTES
    with pytest.raises(ValueError, match="budget"):
        materialize_tool_result(sandbox, "query_redis_get", payload)
    assert not list((sandbox.path / "work").iterdir())


def test_materialization_failure_releases_reservation(tmp_path, monkeypatch):
    sandbox = JobSandboxManager(tmp_path).create("job-query")
    original = type(sandbox).publish_runtime_artifact
    monkeypatch.setattr(
        type(sandbox), "publish_runtime_artifact", Mock(side_effect=OSError("synthetic"))
    )
    with pytest.raises(OSError):
        materialize_tool_result(sandbox, "query_loki", _payload())
    assert not list((sandbox.path / "work").iterdir())
    monkeypatch.setattr(type(sandbox), "publish_runtime_artifact", original)
    for _ in range(80):
        materialize_tool_result(sandbox, "query_loki", _payload())
    with pytest.raises(JobSandboxError) as error:
        materialize_tool_result(sandbox, "query_loki", _payload())
    assert error.value.code == "sandbox_file_count_exceeded"


def test_bridge_fails_closed_and_preserves_audit_meta(tmp_path):
    async def run():
        sandbox = JobSandboxManager(tmp_path).create("job-query")
        schema = TOOL_DEFINITIONS["query_loki"]["schema"]

        class Session:
            async def initialize(self):
                pass

            async def list_tools(self, **kwargs):
                return types.ListToolsResult(
                    tools=[types.Tool(name="query_loki", inputSchema=schema)]
                )

            async def call_tool(self, *args, **kwargs):
                payload = _payload()
                payload["data"]["line_count"] = 2
                return types.CallToolResult.model_validate(
                    {
                        "content": [],
                        "structuredContent": payload,
                        "_meta": {"enterprise-agent/mcp-call-id": "audit"},
                    }
                )

        bridge = ToolResultBridge(
            sdk=SimpleNamespace(create_sdk_mcp_server=lambda **kw: {"instance": object()}),
            url="http://synthetic.invalid",
            headers={},
            frozen={"query_loki": tool_schema_hash(schema)},
            sandbox=sandbox,
            timeout=1,
            session=Session(),
        )
        await bridge.connect()
        result = (await bridge.call_tool("query_loki", {})).model_dump(by_alias=True)
        assert result["isError"]
        assert (
            result["structuredContent"]["error_code"]
            == "resource_query_result_materialization_failed"
        )
        assert result["_meta"]["enterprise-agent/mcp-call-id"] == "audit"
        assert "正文" not in json.dumps(result, ensure_ascii=False)
        assert not list((sandbox.path / "work").iterdir())
        bridge.frozen["query_loki"] = "bad"
        with pytest.raises(NonRetryableExecutionError):
            await bridge.connect()

    asyncio.run(run())
