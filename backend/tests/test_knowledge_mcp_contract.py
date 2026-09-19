"""正式合同、发布和固定 Runtime 路由；无真实 MCP/Provider/模型请求。"""

import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from app.modules.agent.domain.runtime import AgentRunRequest
from app.modules.agent.infrastructure.runtime_http_client import AgentRuntimeHttpClient
from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.domain.tool_policy import knowledge_tool_dependency_errors
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST, validate_mcp_tool_manifest
from app.modules.model_connection.domain import ModelRuntimeBinding
from app.python_runtime.claude_client import build_system_prompt
from app.python_runtime.mcp_config import FixedMcpClaudeSdkClient
from app.shared.exceptions import AppError
from app.shared.knowledge_tool_contracts import (
    KNOWLEDGE_TOOL_CONTRACTS,
    KNOWLEDGE_USAGE_INSTRUCTIONS,
)
from app.shared.mcp_server_policy import business_principal_header_name
from backend.tests.test_knowledge_job_access import (
    knowledge_contract as knowledge_contract_fixture,
    job_fixture as job_fixture_impl,
)
from backend.tests.test_knowledge_search import (
    readable_fixture as readable_fixture_impl,
    bridge_fixture as bridge_fixture_impl,
    search_fixture as search_fixture_impl,
    search,
)
from backend.tests.test_ones_mcp_runtime import _fixture

knowledge_contract = knowledge_contract_fixture
job_fixture = job_fixture_impl
readable_fixture = readable_fixture_impl
bridge_fixture = bridge_fixture_impl
search_fixture = search_fixture_impl


def test_real_catalogs_and_frozen_application_contracts(job_fixture):
    c, job = job_fixture["runtime"], job_fixture["job"]
    agent_catalog = {
        row["identifier"]: row for row in c.agent_config_service.catalog()["mcp_tools"]
    }
    composition = c.business_application_service.mcp_tool_composition_service
    app_catalog = composition.management_catalog(agent_publication_ids=[job.agent_publication_id])
    tools = {
        row["tool_identifier"]: row
        for row in app_catalog["mcp_tools_by_agent_publication"][job.agent_publication_id]
    }
    roles = c.authorization_center_repository.application_catalog()
    role_tools = {tool["tool_identifier"]: tool for app in roles for tool in app["mcp_tools"]}
    snapshot = c.mcp_tool_snapshot_service.verify(job.id)["snapshot"]
    frozen = {tool["tool_identifier"]: tool for tool in snapshot["tools"]}
    for name in KNOWLEDGE_TOOL_CONTRACTS:
        definition = MCP_TOOL_MANIFEST[name]
        assert agent_catalog[name]["server_code"] == tools[name]["server_code"] == "knowledge-mcp"
        assert frozen[name]["schema_hash"] == definition.schema_hash
        assert frozen[name]["effect"] == "read"
        assert frozen[name]["confirmation_policy"] == "none"
        assert frozen[name]["resource_kind"] == ""
        assert role_tools[name]["display_name_zh"] != "MCP Tool"


@pytest.mark.parametrize(
    "missing", ["knowledge_list_bases", "knowledge_search", "ones_get_work_item_detail"]
)
def test_publication_requires_whole_workflow_without_auto_addition(job_fixture, missing):
    selected = [
        name for name in (*KNOWLEDGE_TOOL_CONTRACTS, "ones_get_work_item_detail") if name != missing
    ]
    assert knowledge_tool_dependency_errors(selected)
    c, job = job_fixture["runtime"], job_fixture["job"]
    before = c.mcp_tool_snapshot_service.verify(job.id)
    with pytest.raises(AppError) as error:
        c.business_application_service.mcp_tool_composition_service.prepare(
            agent_publication_id=job.agent_publication_id, raw_tools=selected
        )
    assert error.value.safe_message == error.value.field_errors[0]["message"]
    assert c.mcp_tool_snapshot_service.verify(job.id) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("required_scope", "knowledge_search"),
        ("schema_hash", "f" * 64),
        ("effect", "mutation"),
        ("resource_kind", "database"),
        ("destructive", True),
        ("open_world", True),
        ("description", "drift"),
        ("input_schema", {"type": "object"}),
    ],
)
def test_manifest_rejects_knowledge_contract_drift(field, value):
    changed = replace(MCP_TOOL_MANIFEST["knowledge_search"], **{field: value})
    with pytest.raises(ValueError):
        validate_mcp_tool_manifest({**MCP_TOOL_MANIFEST, "knowledge_search": changed})


@pytest.mark.parametrize(
    "tool,arguments,valid",
    [
        ("knowledge_list_bases", {}, True),
        ("knowledge_list_bases", {"cursor": "x" * 4096}, True),
        ("knowledge_list_bases", {"cursor": "x" * 4097}, False),
        ("knowledge_list_bases", {"limit": 100}, False),
        ("knowledge_search", {"knowledge_base_id": "kb-1", "query": "缺陷"}, True),
        ("knowledge_search", {"knowledge_base_id": "kb-1", "query": "x" * 2000, "top_k": 20}, True),
        ("knowledge_search", {"knowledge_base_id": "kb-1", "query": "x" * 2001}, False),
        ("knowledge_search", {"knowledge_base_id": "kb-1", "query": "  "}, False),
        ("knowledge_search", {"knowledge_base_id": "kb-1", "query": "x", "top_k": True}, False),
        ("knowledge_search", {"knowledge_base_id": "kb-1", "query": "x", "top_k": 21}, False),
        (
            "knowledge_search",
            {"knowledge_base_id": "kb-1", "query": "x", "team_id": "other"},
            False,
        ),
    ],
)
def test_input_contract_bounds(tool, arguments, valid):
    schema = KNOWLEDGE_TOOL_CONTRACTS[tool].input_schema
    Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid(arguments) is valid


def test_application_outputs_match_strict_reference_only_contracts(search_fixture):
    f = search_fixture
    service = f["search"]
    directory = KnowledgeDirectory(service.access, service.resources, service.audit)
    outputs = {
        "knowledge_list_bases": directory.list_bases(token=f["knowledge_token"], arguments={}),
        "knowledge_search": search(f),
    }
    for name, output in outputs.items():
        schema = KNOWLEDGE_TOOL_CONTRACTS[name].output_schema
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(output)
        assert not Draft202012Validator(schema).is_valid({**output, "raw_text": "合成正文"})


def test_runtime_routes_only_frozen_tools_and_isolates_audiences(job_fixture):
    c, job = job_fixture["runtime"], job_fixture["job"]
    context = c.agent_executor.context_builder.build(job)
    initial = AgentRunRequest(
        job.id, job.internal_user_id, job.project_code, context, "synthetic-invocation"
    )
    context = replace(context, mcp_bindings=AgentRuntimeHttpClient._runtime_bindings(initial))
    context = replace(
        context,
        effective_tool_names=tuple(
            f"mcp__{binding.server_code.replace('-', '_')}__{binding.tool_name}"
            for binding in context.mcp_bindings
        ),
    )
    request = AgentRunRequest(
        job.id, job.internal_user_id, job.project_code, context, "synthetic-invocation"
    )
    client = FixedMcpClaudeSdkClient(
        limits=c.settings.execution,
        api_key="synthetic-model-key",
        mcp_server_url="http://tool-mcp:9103/mcp",
        mcp_principal_tokens={
            "ones-mcp": "synthetic-ones-token",
            "knowledge-mcp": "synthetic-kb-token",
        },
    )
    servers = client._build_mcp_server(request)
    assert set(servers) == {"ones_mcp", "knowledge_mcp"}
    assert servers["knowledge_mcp"]["url"] == "http://knowledge-mcp:9108/mcp"
    assert servers["knowledge_mcp"]["headers"]["Authorization"] == "Bearer synthetic-kb-token"
    assert "synthetic-ones-token" not in json.dumps(servers["knowledge_mcp"])
    assert "synthetic-kb-token" not in json.dumps(servers["ones_mcp"])
    assert business_principal_header_name("knowledge-mcp") == "X-MCP-Principal-Token-Knowledge-Mcp"
    captured = {}
    sdk = SimpleNamespace(
        options=lambda **kwargs: captured.update(kwargs),
        permission_allow=None,
        permission_deny=None,
    )
    model = ModelRuntimeBinding(
        "anthropic_compatible", "https://example.invalid", *(["synthetic"] * 5), "high"
    )
    sandbox = client.sandbox_manager.create(job.id)
    token = client._sandbox.set(sandbox)
    try:
        client._build_options(sdk, context, servers, [], model)
        for name in KNOWLEDGE_TOOL_CONTRACTS:
            result = asyncio.run(
                captured["can_use_tool"](f"mcp__knowledge_mcp__{name}", {}, object())
            )
            assert result["behavior"] == "allow"
        denied = asyncio.run(
            captured["can_use_tool"]("mcp__knowledge_mcp__arbitrary_tool", {}, object())
        )
        assert denied["behavior"] == "deny"
    finally:
        client._sandbox.reset(token)
        sandbox.cleanup()
    assert KNOWLEDGE_USAGE_INSTRUCTIONS in build_system_prompt(context)
    assert KNOWLEDGE_USAGE_INSTRUCTIONS not in build_system_prompt(
        replace(context, effective_tool_names=())
    )


def test_registration_does_not_grant_old_job_new_tools():
    f = _fixture(current_agent_envelope=True)
    c, job = f["runtime"], f["job"]
    try:
        f["issuer"].knowledge_job_gate = KnowledgeJobGate(
            c.database, c.mcp_tool_snapshot_service, c.business_authorization_service
        )
        before = c.mcp_tool_snapshot_service.verify(job.id)
        with pytest.raises(AppError):
            f["issuer"].issue_business_mcp_for_job(job_id=job.id, server_code="knowledge-mcp")
        assert c.mcp_tool_snapshot_service.verify(job.id) == before
        context = c.agent_executor.context_builder.build(job)
        request = AgentRunRequest(job.id, job.internal_user_id, job.project_code, context)
        assert not any(
            binding.server_code == "knowledge-mcp"
            for binding in AgentRuntimeHttpClient._runtime_bindings(request)
        )
    finally:
        c.database.close()


def test_runtime_refuses_arbitrary_knowledge_endpoint(job_fixture):
    with pytest.raises(ValueError):
        FixedMcpClaudeSdkClient(
            limits=job_fixture["runtime"].settings.execution,
            api_key="synthetic",
            mcp_server_url="http://tool-mcp:9103/mcp",
            business_mcp_server_urls={"knowledge-mcp": "https://arbitrary.invalid/mcp"},
        )
