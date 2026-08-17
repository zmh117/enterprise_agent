from __future__ import annotations

import json
import re
import stat
from pathlib import Path
import subprocess
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
    schemas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(
            (REPOSITORY_ROOT / "contracts/agent-runtime").glob("v*/protocol.schema.json")
        )
    ]
    for schema in schemas:
        property_names = _walk_property_names(schema)
        assert property_names.isdisjoint(
            {
                "mcp_server_url",
                "server_url",
                "base_url",
                "authorization",
                "auth_mode",
                "principal_jwt",
                "principal_token",
                "principal_header",
                "provider_token",
            }
        )


def test_business_mcp_auth_policy_has_no_dynamic_registry_or_plugin_scan() -> None:
    production = _production_sources().lower()
    for forbidden in (
        "register_mcp_server",
        "discover_mcp_server",
        "scan_mcp_plugin",
        "issue_dingtalk_for_job",
        "issue_ones_for_job",
    ):
        assert forbidden not in production


def test_business_principal_migration_has_no_dedicated_issuer_or_single_slot() -> None:
    production_paths = (
        REPOSITORY_ROOT / "backend/app/modules/identity/application/principal_jwt.py",
        REPOSITORY_ROOT / "backend/app/modules/agent/infrastructure/runtime_http_client.py",
        REPOSITORY_ROOT / "backend/app/python_runtime/invocations.py",
        REPOSITORY_ROOT / "backend/app/python_runtime/executor.py",
        REPOSITORY_ROOT / "backend/app/python_runtime/mcp_config.py",
        REPOSITORY_ROOT / "backend/app/python_runtime/service.py",
    )
    sources = "\n".join(path.read_text(encoding="utf-8") for path in production_paths)

    assert ".issue_for_job(" not in sources
    assert set(re.findall(r"def issue_([a-z0-9_]+)_for_job\(", sources)) == {
        "business_mcp",
        "file",
    }
    assert '"X-MCP-Principal-Token"' not in sources
    assert '"x-mcp-principal-token"' not in sources
    assert re.search(r"self\._principal_token(?!s)", sources) is None
    assert "def principal_token(" not in sources


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
        "${ONES_MCP_PROVIDER_BASE_URL:-http://host.docker.internal:19121}"
    )
    assert ones["environment"]["ONES_MCP_PROVIDER_ALLOWED_HOSTS"] == (
        "${ONES_MCP_PROVIDER_ALLOWED_HOSTS:-host.docker.internal}"
    )
    assert ones["environment"]["ONES_MCP_PROVIDER_ALLOW_INSECURE_LOCAL"] == (
        "${ONES_MCP_PROVIDER_ALLOW_INSECURE_LOCAL:-true}"
    )
    assert "ones-mock" not in ones["depends_on"]
    assert ones["extra_hosts"] == ["host.docker.internal:host-gateway"]
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
    api = services["api-server"]
    assert api["environment"]["PRINCIPAL_JWT_PRIVATE_KEY_FILE"] == (
        "/run/secrets/principal_jwt_private_key"
    )
    assert "principal_jwt_private_key" in api["secrets"]
    for service_name, service in services.items():
        if service_name not in {"agent-worker", "api-server"}:
            assert "principal_jwt_private_key" not in service.get("secrets", [])

    assert "typescript-agent-runtime" not in services
    runtime = services["python-agent-runtime"]
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
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["optional-dependencies"]["ones-mcp"] == ["mcp==2.0.0"]
    assert project["project"]["optional-dependencies"]["tool-mcp"] == ["mcp==2.0.0"]


def test_secret_bootstrap_makes_container_principal_private_key_read_only(
    tmp_path: Path,
) -> None:
    script = REPOSITORY_ROOT / "scripts/bootstrap_agent_runtime_secrets.sh"
    subprocess.run([str(script), str(tmp_path)], check=True, capture_output=True, text=True)

    principal_private_key = tmp_path / "principal-jwt-private.pem"
    assert stat.S_IMODE(principal_private_key.stat().st_mode) == 0o400
    assert stat.S_IMODE((tmp_path / "principal-jwks.json").stat().st_mode) == 0o644
    file_worker_bootstrap = tmp_path / "file-worker-bootstrap-token"
    delivery_worker_bootstrap = tmp_path / "delivery-worker-bootstrap-token"
    assert not (tmp_path / "service-principal-private.pem").exists()
    assert not (tmp_path / "service-principal-jwks.json").exists()
    assert stat.S_IMODE(file_worker_bootstrap.stat().st_mode) == 0o400
    assert stat.S_IMODE(delivery_worker_bootstrap.stat().st_mode) == 0o400
    assert file_worker_bootstrap.read_bytes() != delivery_worker_bootstrap.read_bytes()

    loaded = principal_private_key.read_bytes()
    file_worker_loaded = file_worker_bootstrap.read_bytes()
    delivery_worker_loaded = delivery_worker_bootstrap.read_bytes()
    subprocess.run([str(script), str(tmp_path)], check=True, capture_output=True, text=True)
    assert principal_private_key.read_bytes() == loaded
    assert file_worker_bootstrap.read_bytes() == file_worker_loaded
    assert delivery_worker_bootstrap.read_bytes() == delivery_worker_loaded
    assert stat.S_IMODE(principal_private_key.stat().st_mode) == 0o400


def test_local_ones_mock_is_independent_and_host_published() -> None:
    compose = yaml.safe_load((REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "ones-mock" not in compose["services"]

    mock_compose = yaml.safe_load(
        (REPOSITORY_ROOT / "ones_mock/docker-compose.ones-mock.yml").read_text(encoding="utf-8")
    )
    mock = mock_compose["services"]["ones-mock"]
    assert mock["build"] == {
        "context": ".",
        "dockerfile": "Dockerfile",
    }
    assert mock["read_only"] is True
    assert mock["cap_drop"] == ["ALL"]
    assert mock["security_opt"] == ["no-new-privileges:true"]
    assert mock["ports"] == ["127.0.0.1:19121:19121"]

    dockerfile = (REPOSITORY_ROOT / "ones_mock/Dockerfile").read_text(encoding="utf-8")
    assert "USER 10004:10004" in dockerfile
