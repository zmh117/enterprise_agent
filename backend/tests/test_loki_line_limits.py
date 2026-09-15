from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.domain.errors import PolicyViolation
from app.modules.mcp_tool_runtime.domain.topology import LokiConnection
from app.modules.mcp_tool_runtime.service import ReadOnlyToolService
from app.modules.platform_config.application.runtime_config import RUNTIME_CONFIG_DEFINITIONS
from app.modules.platform_config.application.validation import PlatformConfigValidationError
from app.modules.platform_config.domain.provider_contracts import (
    CanonicalProviderDocument,
    ProviderContractRegistry,
)
from app.shared.config import ExecutionSettings, LokiSettings, load_settings
from app.shared.exceptions import ToolPolicyError
from app.shared.runtime_config_loader import apply_runtime_config_overlay
from backend.tests.support.runtime import container, test_settings as make_settings


TOOLS = ("query_loki", "diagnose_loki_probe", "diagnose_loki_labels", "diagnose_loki_label_values")


def test_platform_and_resource_defaults_are_consistent() -> None:
    with patch.dict(os.environ, {"APP_ENV": "test"}, clear=True):
        settings = load_settings()
    assert ExecutionSettings().max_loki_lines == settings.execution.max_loki_lines == 10000
    assert LokiSettings().max_lines == settings.loki.max_lines == 10000
    assert LokiConnection(base_url="http://loki.test").max_lines == 1000
    definitions = {item.key: item for item in RUNTIME_CONFIG_DEFINITIONS}
    for key in ("MAX_LOKI_LINES", "LOKI_MAX_LINES"):
        assert definitions[key].default == 10000


def test_explicit_env_limits_are_not_overwritten() -> None:
    with patch.dict(
        os.environ,
        {"APP_ENV": "test", "MAX_LOKI_LINES": "200", "LOKI_MAX_LINES": "300"},
        clear=True,
    ):
        settings = load_settings()
    assert settings.execution.max_loki_lines == 200
    assert settings.loki.max_lines == 300


def test_explicit_db_limits_survive_definition_reconciliation() -> None:
    runtime = container()
    service = runtime.platform_config_service
    for key, value in (("MAX_LOKI_LINES", 200), ("LOKI_MAX_LINES", 300)):
        # Simulate the pre-upgrade registry default without touching the explicit value.
        definition = service.repository.get_runtime_config_definition(key)
        service.upsert_runtime_config_definition(
            {**definition, "default": 500}, actor_id="user_local_admin"
        )
        service.upsert_runtime_config_value(
            {"key": key, "scope_type": "global", "value": value},
            actor_id="user_local_admin",
        )
    service.ensure_runtime_config_definitions(actor_id="user_local_admin")
    for key in ("MAX_LOKI_LINES", "LOKI_MAX_LINES"):
        assert service.repository.get_runtime_config_definition(key)["default"] == 10000
    settings = apply_runtime_config_overlay(
        make_settings(), service.repository.database, service_name="tool-mcp"
    )
    assert settings.execution.max_loki_lines == 200
    assert settings.loki.max_lines == 300


def _resource_config(max_lines: object) -> dict:
    return {
        "base_url": "http://loki.test:3100",
        "timeout_seconds": 5,
        "max_minutes": 60,
        "max_lines": max_lines,
        "max_response_bytes": 1048576,
    }


@pytest.mark.parametrize("max_lines", [1, 100, 1000])
def test_resource_contract_accepts_at_most_1000(max_lines: int) -> None:
    registry = ProviderContractRegistry()
    document = registry.normalize(provider_type="loki", config=_resource_config(max_lines))
    assert document.config["max_lines"] == max_lines
    field = next(item for item in registry.require("loki").fields if item["name"] == "max_lines")
    assert (field["minimum"], field["maximum"]) == (1, 1000)


@pytest.mark.parametrize("max_lines", [0, -1, 1001, 5000, 10000, True, "invalid"])
def test_resource_contract_rejects_invalid_max_lines(max_lines: object) -> None:
    with pytest.raises(PlatformConfigValidationError):
        ProviderContractRegistry().normalize(
            provider_type="loki", config=_resource_config(max_lines)
        )


def test_existing_published_resource_is_not_silently_rewritten() -> None:
    document = CanonicalProviderDocument(
        provider_type="loki",
        contract_version="loki_v1",
        resource_kind="loki",
        config=_resource_config(2000),
        secret_refs={},
    )
    projected = ProviderContractRegistry().runtime_projection(document, resolve_secret=Mock())
    assert projected["max_lines"] == document.config["max_lines"] == 2000


def _service(resource_lines: int = 1000, platform_lines: int = 10000):
    resource = SimpleNamespace(
        binding=SimpleNamespace(
            loki=LokiConnection(
                base_url="http://loki.test:3100",
                max_lines=resource_lines,
            )
        ),
        loki_selector_conditions=(("customer", "test"),),
        resource_code="test-loki",
        resource_revision_id="test-revision",
        resource_content_hash="test-hash",
        placement="",
        scope_target=("test", "", ""),
        table_prefix="",
        redis_namespace_prefixes=(),
    )
    limits = replace(ExecutionSettings(), max_loki_lines=platform_lines)
    executor = DirectReadOnlyToolExecutor(Mock(), limits=limits)
    executor._resolve = Mock(return_value=resource)
    # Keep the production factory's min(platform, resource); replace only HTTP I/O.
    client = executor._loki(resource)
    requests = []

    def fetch(request, timeout):
        requests.append(request)
        parsed = urlparse(request.full_url)
        if parsed.path.endswith("/series"):
            data = [{"customer": "test", "app": "test-app"}]
        else:
            count = int(parse_qs(parsed.query)["limit"][0])
            data = {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {"customer": "test"},
                        "values": [[str(i), "test"] for i in range(count)],
                    }
                ],
            }
        return BytesIO(json.dumps({"status": "success", "data": data}).encode())

    client._urlopen_func = fetch
    executor._loki = Mock(return_value=client)
    service = ReadOnlyToolService.__new__(ReadOnlyToolService)
    service.limits = limits
    service.tool_executor = executor
    return service, requests


def _call(service, tool: str, **extra):
    args = {"environment": "test", "label": "app", **extra}
    service._assert_tool_policy(tool, args)
    return service._execute(
        tool,
        args,
        job_id="same-test-job",
        user_id="test-user",
        project_code="test",
        tool_call_id="test-call",
        application_id="test-app",
        snapshot_context={},
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_all_tools_accept_resource_boundary_and_reject_before_http(tool: str) -> None:
    service, requests = _service()
    _call(service, tool, limit=1000)
    assert len(requests) == 1
    with pytest.raises(PolicyViolation):
        _call(service, tool, limit=1001)
    assert len(requests) == 1


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("resource_lines,platform_lines", [(200, 10000), (1000, 200)])
def test_smaller_explicit_limit_is_enforced(
    tool: str, resource_lines: int, platform_lines: int
) -> None:
    service, requests = _service(resource_lines, platform_lines)
    _call(service, tool, limit=200)
    with pytest.raises((PolicyViolation, ToolPolicyError)):
        _call(service, tool, limit=201)
    assert len(requests) == 1


@pytest.mark.parametrize("tool", TOOLS)
def test_omitted_limit_stays_100(tool: str) -> None:
    service, _ = _service()
    service.tool_executor = Mock()
    _call(service, tool)
    assert getattr(service.tool_executor, tool).call_args.kwargs["limit"] == 100


def test_same_job_can_read_more_than_platform_limit_across_calls() -> None:
    service, requests = _service()
    total = sum(_call(service, "query_loki", limit=1000).summary["line_count"] for _ in range(11))
    assert total == 11000
    assert len(requests) == 11
