from __future__ import annotations

import pytest

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST, validate_mcp_tool_manifest
from app.shared.mcp_server_policy import (
    FILE_MCP_SERVER_CODE,
    DINGTALK_MCP_SERVER_CODE,
    MCP_SERVER_POLICIES,
    ONES_MCP_SERVER_CODE,
    TOOL_MCP_SERVER_CODE,
    McpServerAuthMode,
    McpServerPolicy,
    business_principal_header_name,
    business_principal_server_code_from_header,
    mcp_sdk_server_alias,
    require_business_principal_server,
    validate_mcp_server_policies,
)
from backend.tests.business_mcp_fixtures import (
    TEST_BUSINESS_SERVER_CODE,
    business_mcp_test_manifest,
    business_mcp_test_policies,
)


def test_fixed_mcp_servers_have_one_closed_auth_mode() -> None:
    assert {code: policy.auth_mode for code, policy in MCP_SERVER_POLICIES.items()} == {
        TOOL_MCP_SERVER_CODE: McpServerAuthMode.JOB_CONTEXT,
        ONES_MCP_SERVER_CODE: McpServerAuthMode.BUSINESS_PRINCIPAL_JWT,
        DINGTALK_MCP_SERVER_CODE: McpServerAuthMode.BUSINESS_PRINCIPAL_JWT,
        FILE_MCP_SERVER_CODE: McpServerAuthMode.FILE_PRINCIPAL_JWT,
    }
    validate_mcp_tool_manifest()
    assert {definition.server_code for definition in MCP_TOOL_MANIFEST.values()} <= set(
        MCP_SERVER_POLICIES
    )


def test_test_only_second_business_server_never_enters_production_manifest() -> None:
    assert TEST_BUSINESS_SERVER_CODE not in MCP_SERVER_POLICIES
    assert all(
        definition.server_code != TEST_BUSINESS_SERVER_CODE
        for definition in MCP_TOOL_MANIFEST.values()
    )
    policies = business_mcp_test_policies()
    manifest = business_mcp_test_manifest()
    validate_mcp_tool_manifest(manifest, policies=policies)
    assert policies[TEST_BUSINESS_SERVER_CODE].auth_mode is (
        McpServerAuthMode.BUSINESS_PRINCIPAL_JWT
    )


def test_business_principal_header_mapping_is_exact_and_reversible() -> None:
    assert business_principal_header_name(ONES_MCP_SERVER_CODE) == (
        "X-MCP-Principal-Token-Ones-Mcp"
    )
    assert (
        business_principal_server_code_from_header("x-mcp-principal-token-ones-mcp")
        == ONES_MCP_SERVER_CODE
    )
    policies = business_mcp_test_policies()
    aliases = {code: mcp_sdk_server_alias(code, policies=policies) for code in policies}
    assert aliases[ONES_MCP_SERVER_CODE] == "ones_mcp"
    assert aliases[DINGTALK_MCP_SERVER_CODE] == "dingtalk_mcp"
    assert aliases[TEST_BUSINESS_SERVER_CODE] == "test_business_mcp"
    assert len(set(aliases.values())) == len(aliases)


def test_production_mcp_auth_policy_is_immutable_and_not_runtime_registered() -> None:
    policy = business_mcp_test_policies()[TEST_BUSINESS_SERVER_CODE]
    with pytest.raises(TypeError):
        MCP_SERVER_POLICIES["dynamic-mcp"] = policy  # type: ignore[index]
    assert policy.server_code == TEST_BUSINESS_SERVER_CODE

    invalid = {
        **business_mcp_test_policies(),
        "dynamic-job-mcp": McpServerPolicy(
            server_code="dynamic-job-mcp",
            auth_mode=McpServerAuthMode.JOB_CONTEXT,
        ),
    }
    with pytest.raises(ValueError, match="only Job-context"):
        validate_mcp_server_policies(invalid)


@pytest.mark.parametrize(
    "server_code",
    [
        "",
        "ONES-MCP",
        "ones_mcp",
        "ones:mcp",
        "-ones-mcp",
        "ones-mcp-",
        TOOL_MCP_SERVER_CODE,
        FILE_MCP_SERVER_CODE,
        "unknown-mcp",
    ],
)
def test_business_principal_header_mapping_rejects_unsafe_or_non_business_servers(
    server_code: str,
) -> None:
    with pytest.raises(ValueError):
        require_business_principal_server(server_code)


@pytest.mark.parametrize(
    "header_name",
    [
        "X-MCP-Principal-Token",
        "X-MCP-Principal-Token-File-Service",
        "X-MCP-Principal-Token-Unknown-Mcp",
        "Authorization",
    ],
)
def test_business_principal_header_parser_rejects_legacy_or_unknown_headers(
    header_name: str,
) -> None:
    with pytest.raises(ValueError):
        business_principal_server_code_from_header(header_name)
