from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from jsonschema import Draft202012Validator
import pytest

from app.modules.agent.infrastructure.tool_manifest import TOOL_DEFINITIONS
from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.domain.loki_policy import build_effective_selector
from app.modules.mcp_tool_runtime.infrastructure.loki_client import _selector_from_payload
from app.modules.mcp_tool_runtime.infrastructure.loki_gateway import HttpLokiClient
from app.modules.mcp_tool_runtime.policies import assert_loki_bounds, assert_loki_label
from app.modules.mcp_tool_runtime.service import ReadOnlyToolService, _loki_selector_from_arguments
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError
from app.shared.loki_contract import assert_loki_selector


FIXED = {"customer": "A", "workshop": "GL001"}
TOOLS = ("query_loki", "diagnose_loki_probe", "diagnose_loki_labels", "diagnose_loki_label_values")


def _validator(tool: str) -> Draft202012Validator:
    return Draft202012Validator(TOOL_DEFINITIONS[tool]["schema"])


@pytest.mark.parametrize(
    "label", ["app", "logtype", "customer", "workshop", "namespace", "custom_label_123", "a" * 128]
)
def test_arbitrary_valid_labels_match_schema_entry_and_domain(label: str) -> None:
    args = {"environment": "test", "base": "", "label": label}
    assert _validator("diagnose_loki_label_values").is_valid(args)
    assert_loki_label(label)
    selector = {label: "value"}
    for tool in ("query_loki", "diagnose_loki_probe"):
        assert _validator(tool).is_valid({"environment": "test", "base": "", "selector": selector})
    assert_loki_bounds(selector=selector, minutes=15, limit=10, settings=ExecutionSettings())
    assert _selector_from_payload({"selector": selector}) == selector
    assert build_effective_selector(
        selector, mandatory_conditions=(("fixed_other", "A"),), require_mandatory=True
    ) == {"fixed_other": "A", **selector}


@pytest.mark.parametrize(
    "label", ["", "a" * 129, "9app", "app-name", 'app"} or {customer', "app\n", "a\x00", None, 12]
)
def test_invalid_label_fails_consistently(label: object) -> None:
    assert not _validator("diagnose_loki_label_values").is_valid(
        {"environment": "test", "base": "", "label": label}
    )
    with pytest.raises(ToolPolicyError) as error:
        assert_loki_label(label)
    assert error.value.error_code == "loki_label_invalid"
    assert "标签名" in error.value.safe_message
    if isinstance(label, str):
        assert not _validator("query_loki").is_valid({"selector": {label: "x"}})


@pytest.mark.parametrize("value", ["中文 日志", 'a"b\\c', "error", "a" * 256])
def test_exact_values_are_shared_and_escaped(value: str) -> None:
    selector = {"app": value}
    assert _validator("query_loki").is_valid({"selector": selector})
    assert_loki_selector(selector)
    assert _selector_from_payload({"selector": selector}) == selector


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 257,
        " space",
        "space ",
        "a\n",
        "a\x00",
        ".*",
        "a?",
        "x!=y",
        "x=~y",
        "x!~y",
        'a"} or {customer="B',
        "a|b",
        5,
        None,
    ],
)
def test_unsafe_or_invalid_values_are_rejected(value: object) -> None:
    selector = {"app": value}
    assert not _validator("query_loki").is_valid({"selector": selector})
    with pytest.raises(ToolPolicyError) as error:
        assert_loki_selector(selector)
    assert error.value.error_code == "loki_selector_value_invalid"
    with pytest.raises(ToolPolicyError) as entry_error:
        _loki_selector_from_arguments({"selector": selector})
    assert entry_error.value.error_code == error.value.error_code


@pytest.mark.parametrize("fixed_key", ["customer", "workshop", "app", "custom_fixed"])
@pytest.mark.parametrize("value", ["A", "override"])
def test_fixed_keys_cannot_be_resubmitted_even_with_same_value(fixed_key: str, value: str) -> None:
    with pytest.raises(ToolPolicyError) as error:
        build_effective_selector(
            {fixed_key: value}, mandatory_conditions=((fixed_key, "A"),), require_mandatory=True
        )
    assert error.value.error_code == "loki_fixed_label_conflict"
    assert "已由 Loki 资源固定" in error.value.safe_message


def _executor(fixed: dict[str, str] | None = None):
    resource = SimpleNamespace(
        loki_selector_conditions=tuple((FIXED if fixed is None else fixed).items()),
        binding=SimpleNamespace(
            loki=SimpleNamespace(
                base_url="http://loki.test:3100",
                tenant_id="test-tenant",
                auth_token="",
                timeout_seconds=5,
                max_minutes=60,
                max_lines=100,
            )
        ),
        resource_code="loki-test",
        resource_revision_id="revision-test",
        resource_content_hash="test-hash",
        placement="",
        scope_target=("test", "", ""),
        table_prefix="",
        redis_namespace_prefixes=(),
    )
    requests = []

    def fetch(request, timeout):
        requests.append(request)
        path = urlparse(request.full_url).path
        if path.endswith("/series"):
            body = {
                "status": "success",
                "data": [
                    {**FIXED, "app": "mes-run", "logtype": "error", "custom_label": "v1"},
                    {**FIXED, "app": "mes-login", "logtype": "info", "custom_label": "v2"},
                ],
            }
        else:
            body = {"status": "success", "data": {"resultType": "streams", "result": []}}
        return BytesIO(json.dumps(body).encode())

    client = HttpLokiClient(
        max_minutes=60, max_lines=100, max_response_chars=8000, urlopen_func=fetch
    )
    executor = DirectReadOnlyToolExecutor(Mock(), limits=ExecutionSettings())
    executor._resolve = Mock(return_value=resource)
    executor._loki = Mock(return_value=client)
    return executor, requests


def _invoke(executor, tool: str, **overrides):
    args = {"environment": "test", "base": "", "minutes": 15, "limit": 20}
    if tool in ("query_loki", "diagnose_loki_probe"):
        args.update(selector={"app": "mes-run", "logtype": "error"}, query="error")
    if tool == "diagnose_loki_label_values":
        args["label"] = "logtype"
    args.update(overrides)
    _validator(tool).validate(args)
    # Exercise the same outer guard that originally rejected app/logtype.
    service = ReadOnlyToolService.__new__(ReadOnlyToolService)
    service.limits = ExecutionSettings()
    service._assert_tool_policy(tool, args)
    return getattr(executor, tool)(context=None, **args)


@pytest.mark.parametrize("tool", TOOLS)
def test_all_four_tools_send_fixed_scope_to_http(tool: str) -> None:
    executor, requests = _executor()
    result = _invoke(executor, tool)
    assert len(requests) == 1
    parsed = urlparse(requests[0].full_url)
    params = parse_qs(parsed.query)
    expression = params.get("match[]", params.get("query"))[0]
    assert 'customer="A"' in expression and 'workshop="GL001"' in expression
    assert requests[0].get_header("X-scope-orgid") == "test-tenant"
    assert "start" in params and "end" in params
    if tool in ("query_loki", "diagnose_loki_probe"):
        assert 'app="mes-run"' in expression and 'logtype="error"' in expression
        assert params["limit"] == ["20"]
    else:
        assert parsed.path == "/loki/api/v1/series"
    if tool == "diagnose_loki_labels":
        assert "custom_label" in result.summary["labels"]
        assert "customer" in result.summary["labels"]
    if tool == "diagnose_loki_label_values":
        assert result.summary["values"] == ["error", "info"]


@pytest.mark.parametrize("tool", TOOLS)
def test_all_four_tools_fail_closed_before_http_when_scope_missing(tool: str) -> None:
    executor, requests = _executor({})
    with pytest.raises(ToolPolicyError) as error:
        _invoke(executor, tool)
    assert error.value.error_code == "loki_resource_scope_required"
    assert not requests
    executor._loki.assert_not_called()


@pytest.mark.parametrize("tool", ["query_loki", "diagnose_loki_probe"])
def test_query_with_no_additional_labels_still_uses_fixed_scope(tool: str) -> None:
    executor, requests = _executor()
    _invoke(executor, tool, selector={})
    expression = parse_qs(urlparse(requests[0].full_url).query)["query"][0]
    assert expression == '{customer="A",workshop="GL001"} |= "error"'


@pytest.mark.parametrize("tool", ["query_loki", "diagnose_loki_probe"])
def test_fixed_scope_conflict_never_reaches_http(tool: str) -> None:
    executor, requests = _executor()
    with pytest.raises(ToolPolicyError) as error:
        _invoke(executor, tool, selector={"customer": "B"})
    assert error.value.error_code == "loki_fixed_label_conflict"
    assert not requests
    executor._loki.assert_not_called()


def test_fixed_and_custom_label_values_are_bounded_and_empty_is_not_denied() -> None:
    executor, requests = _executor()
    assert _invoke(executor, "diagnose_loki_label_values", label="customer").summary["values"] == [
        "A"
    ]
    result = _invoke(executor, "diagnose_loki_label_values", label="custom_label", limit=1)
    assert result.summary["values"] == ["v1"] and result.truncated
    result = _invoke(executor, "diagnose_loki_label_values", label="missing_label")
    assert result.summary["values"] == [] and not result.truncated
    assert len(requests) == 3


@pytest.mark.parametrize("tool", TOOLS)
def test_time_and_result_bounds_still_reject_before_http(tool: str) -> None:
    executor, requests = _executor()
    for args in ({"minutes": 43200}, {"limit": 100000}):
        with pytest.raises(ToolPolicyError):
            _invoke(executor, tool, **args)
    assert not requests


def test_selector_count_is_bounded() -> None:
    selector = {f"label_{i}": "v" for i in range(9)}
    assert not _validator("query_loki").is_valid({"selector": selector})
    with pytest.raises(ToolPolicyError, match="size"):
        assert_loki_selector(selector)


@pytest.mark.parametrize(
    "selector", [{"bad\n": "v"}, {"app": 'x"} or {customer="B'}, {"app": None}]
)
def test_direct_executor_rejects_injection_without_schema_frontend(selector) -> None:
    executor, requests = _executor()
    with pytest.raises(ToolPolicyError):
        executor.query_loki(selector, "", 15, 20, None, environment="test")
    assert not requests
    executor._loki.assert_not_called()


def test_custom_value_quotes_are_encoded_as_a_single_exact_literal() -> None:
    executor, requests = _executor()
    _invoke(executor, "query_loki", selector={"app": 'a"b\\c'})
    expression = parse_qs(urlparse(requests[0].full_url).query)["query"][0]
    assert expression == '{app="a\\"b\\\\c",customer="A",workshop="GL001"} |= "error"'


@pytest.mark.parametrize("method", ["labels", "label_values", "query", "probe"])
def test_http_client_has_no_unscoped_fallback(method: str) -> None:
    executor, requests = _executor()
    resource = executor._resolve()
    client = executor._loki(resource)
    args = {"selector": {}, "minutes": 15, "limit": 20}
    if method == "label_values":
        args["label"] = "app"
    if method in ("query", "probe"):
        args["query"] = ""
    with pytest.raises(ToolPolicyError):
        getattr(client, method)(resource.binding, **args)
    assert not requests
