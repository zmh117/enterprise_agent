from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any

import pytest
import yaml

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
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST


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
    definition = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]
    assert definition.server_code == SERVER_CODE
    assert definition.input_schema == TOOL_INPUT_SCHEMA
    assert definition.read_only is True


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


def test_compose_keeps_principal_keys_provider_config_and_runtime_urls_separated() -> None:
    compose = yaml.safe_load((REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    ones = services["ones-mcp"]
    assert ones["build"]["target"] == "ones-mcp"
    assert ones["read_only"] is True
    assert "ports" not in ones
    assert ones["expose"] == ["9104"]
    assert set(ones["networks"]) == {"agent-runtime-control", "provider-egress"}
    assert set(ones["secrets"]) == {"app_config_master_key", "principal_jwks"}
    assert ones["environment"]["PRINCIPAL_JWKS_FILE"] == ("/run/secrets/principal_jwks")
    assert ones["environment"]["ONES_MCP_PROVIDER_BASE_URL"] == (
        "${ONES_MCP_PROVIDER_BASE_URL:-http://ones-mock:19121}"
    )
    assert ones["environment"]["ONES_MCP_PROVIDER_ALLOWED_HOSTS"] == (
        "${ONES_MCP_PROVIDER_ALLOWED_HOSTS:-ones-mock}"
    )
    assert ones["environment"]["ONES_MCP_PROVIDER_ALLOW_INSECURE_LOCAL"] == (
        "${ONES_MCP_PROVIDER_ALLOW_INSECURE_LOCAL:-true}"
    )
    assert ones["depends_on"]["ones-mock"]["condition"] == "service_healthy"
    assert not {
        "ONES_IDENTITY_BASE_URL",
        "ONES_IDENTITY_ALLOWED_HOSTS",
        "PRINCIPAL_JWT_PRIVATE_KEY_FILE",
        "DINGTALK_RUNTIME_AUTH_TOKEN_FILE",
        "PYTHON_AGENT_RUNTIME_URL",
        "TYPESCRIPT_AGENT_RUNTIME_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
    }.intersection(ones["environment"])

    worker = services["agent-worker"]
    assert worker["environment"]["PRINCIPAL_JWT_PRIVATE_KEY_FILE"] == (
        "/run/secrets/principal_jwt_private_key"
    )
    assert "principal_jwt_private_key" in worker["secrets"]
    for service_name, service in services.items():
        if service_name != "agent-worker":
            assert "principal_jwt_private_key" not in service.get("secrets", [])

    for runtime_name in ("typescript-agent-runtime", "python-agent-runtime"):
        runtime = services[runtime_name]
        assert runtime["environment"]["ONES_MCP_SERVER_URL"] == ("http://ones-mcp:9104/mcp")
        assert runtime["depends_on"]["ones-mcp"]["condition"] == "service_healthy"
        assert not {
            "PRINCIPAL_JWT_PRIVATE_KEY_FILE",
            "PRINCIPAL_JWKS_FILE",
            "ONES_MCP_PROVIDER_BASE_URL",
            "ONES_MCP_PROVIDER_ALLOWED_HOSTS",
        }.intersection(runtime["environment"])

    dockerfile = (REPOSITORY_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "FROM api-server AS ones-mcp" in dockerfile
    assert 'USER 10003:10003\nCMD ["python", "-m", "services.ones_mcp_server"]' in dockerfile
    project = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["project"]["optional-dependencies"]["ones-mcp"] == ["mcp==2.0.0"]
    assert project["project"]["optional-dependencies"]["tool-mcp"] == ["mcp==1.28.1"]


def test_compose_local_ones_mock_is_internal_and_not_host_published() -> None:
    compose = yaml.safe_load((REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    mock = compose["services"]["ones-mock"]
    assert mock["build"] == {
        "context": "./ones_mock",
        "dockerfile": "Dockerfile",
    }
    assert mock["read_only"] is True
    assert mock["cap_drop"] == ["ALL"]
    assert mock["security_opt"] == ["no-new-privileges:true"]
    assert mock["networks"] == ["agent-runtime-control"]
    assert mock["expose"] == ["19121"]
    assert "ports" not in mock

    dockerfile = (REPOSITORY_ROOT / "ones_mock/Dockerfile").read_text(encoding="utf-8")
    assert "USER 10004:10004" in dockerfile
