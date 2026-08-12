from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from services.ones_mcp_server.contracts import (
    ISSUE_TYPES,
    LOGIN_PATH,
    SERVER_CODE,
    TOOL_IDENTIFIER,
    TOOL_INPUT_SCHEMA,
    TOOL_OUTPUT_SCHEMA,
    WORK_ITEM_SEARCH_DOCUMENT,
    WORK_ITEM_SEARCH_PATH,
    ProviderContractError,
    validate_provider_target,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _production_sources() -> str:
    roots = (
        REPOSITORY_ROOT / "backend/app",
        REPOSITORY_ROOT / "agent-runtime/src",
        REPOSITORY_ROOT / "services",
    )
    sources: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.suffix in {".py", ".ts", ".json"} and "__pycache__" not in path.parts:
                sources.append(path.read_text(encoding="utf-8"))
    return "\n".join(sources)


def _walk_property_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(str(name).lower() for name in properties)
        for child in value.values():
            names.update(_walk_property_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_walk_property_names(child))
    return names


def test_retired_mcp_and_api_platform_architecture_cannot_return() -> None:
    production = _production_sources().lower()
    for forbidden in (
        "runtime-tool-mcp",
        "mcp_signing_key",
        "mcp_access_token",
        "hs256",
        "generic_http_tool",
        "generic_graphql_tool",
    ):
        assert forbidden not in production

    retired_module_roots = (
        REPOSITORY_ROOT / "backend/app/modules/api_capability",
        REPOSITORY_ROOT / "backend/app/modules/api_connection",
        REPOSITORY_ROOT / "backend/app/modules/internal_api_platform",
    )
    for root in retired_module_roots:
        assert not list(root.rglob("*.py")) if root.exists() else True


def test_runtime_protocol_has_no_caller_controlled_mcp_target_or_credential() -> None:
    schema = json.loads(
        (REPOSITORY_ROOT / "agent-runtime/contracts/v1/protocol.schema.json").read_text(
            encoding="utf-8"
        )
    )
    property_names = _walk_property_names(schema)
    assert property_names.isdisjoint(
        {
            "mcp_server_url",
            "server_url",
            "base_url",
            "authorization",
            "principal_jwt",
            "principal_token",
            "provider_token",
        }
    )


def test_first_phase_ones_contract_is_single_fixed_readonly_tool() -> None:
    assert SERVER_CODE == "ones-mcp"
    assert TOOL_IDENTIFIER == "ones_work_item_search"
    assert ISSUE_TYPES == ("demand", "task", "defect")
    assert TOOL_INPUT_SCHEMA["additionalProperties"] is False
    assert TOOL_INPUT_SCHEMA["required"] == ["keyword", "issue_type", "limit"]
    assert TOOL_OUTPUT_SCHEMA["properties"]["untrusted_data"] == {"const": True}
    assert LOGIN_PATH == "/project/api/project/auth/login"
    assert WORK_ITEM_SEARCH_PATH == "/project/api/project/items/graphql"
    assert WORK_ITEM_SEARCH_DOCUMENT.startswith("query SearchWorkItems(")


def test_provider_target_requires_https_except_explicit_local_mock() -> None:
    production = validate_provider_target(
        "https://ones.example.test",
        allowed_hosts=("ones.example.test",),
        app_env="production",
        allow_insecure_local=False,
    )
    assert production.base_url == "https://ones.example.test"
    assert production.allow_insecure_local is False

    local = validate_provider_target(
        "http://ones-mock:8001/",
        allowed_hosts=("ones-mock",),
        app_env="test",
        allow_insecure_local=True,
    )
    assert local.host == "ones-mock"
    assert local.allow_insecure_local is True

    for candidate, environment, allow_insecure in (
        ("http://ones.example.test", "production", True),
        ("http://ones-mock", "test", False),
        ("https://other.example.test", "production", False),
        ("https://user@ones.example.test", "production", False),
        ("https://ones.example.test/custom/path", "production", False),
    ):
        with pytest.raises(ProviderContractError):
            validate_provider_target(
                candidate,
                allowed_hosts=("ones.example.test", "ones-mock"),
                app_env=environment,
                allow_insecure_local=allow_insecure,
            )
