"""真实 Job/发布/快照和 RBAC；知识合同仅在测试进程注册，未对生产开放。"""

import json

import pytest

from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate, KNOWLEDGE_TOOLS
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.mcp_tool_runtime.manifest import (
    MCP_TOOL_MANIFEST,
    McpToolDefinition,
    mcp_tool_schema_hash,
)
from app.shared import mcp_server_policy
from app.shared.exceptions import AppError
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.identity.application.principal_jwt import (
    PrincipalTokenIssuer,
    PrincipalTokenVerifier,
    PrincipalJwks,
)
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from backend.tests.test_role_authorization_control_center import _active_application
from backend.tests.test_knowledge_authorization import add_base
from backend.tests.test_ones_mcp_runtime import _fixture


@pytest.fixture
def knowledge_contract(monkeypatch):
    monkeypatch.setattr(
        ToolRegistry, "READONLY_TOOLS", frozenset({*ToolRegistry.READONLY_TOOLS, *KNOWLEDGE_TOOLS})
    )
    policies = {
        **mcp_server_policy.MCP_SERVER_POLICIES,
        "knowledge-mcp": mcp_server_policy.McpServerPolicy(
            server_code="knowledge-mcp",
            auth_mode=mcp_server_policy.McpServerAuthMode.BUSINESS_PRINCIPAL_JWT,
        ),
    }
    monkeypatch.setattr(mcp_server_policy, "MCP_SERVER_POLICIES", policies)
    for name in KNOWLEDGE_TOOLS:
        schema = {"type": "object", "additionalProperties": False, "properties": {}}
        monkeypatch.setitem(
            MCP_TOOL_MANIFEST,
            name,
            McpToolDefinition(
                server_code="knowledge-mcp",
                identifier=name,
                description="仅合成测试使用",
                input_schema=schema,
                schema_hash=mcp_tool_schema_hash(schema),
                required_scope=name,
            ),
        )


@pytest.fixture
def job_fixture(knowledge_contract, tmp_path):
    def configure(runtime, selection):
        add_base(runtime, "kb-test")
        add_base(runtime, "kb-future")
        runtime.database.execute(
            "insert into rbac_role_application_knowledge_base(application_access_id,knowledge_base_id,created_at) "
            "select id,'kb-test',created_at from rbac_role_application_access where application_id=?",
            (selection["application_id"],),
        )

    f = _fixture(
        capabilities=("ones_work_item_search", "ones_get_work_item_detail", *KNOWLEDGE_TOOLS),
        before_job=configure,
        current_agent_envelope=True,
    )
    c = f["runtime"]
    f["gate"] = KnowledgeJobGate(
        c.database, c.mcp_tool_snapshot_service, c.business_authorization_service
    )
    yield f
    c.database.close()


def resolve(f):
    return f["gate"].require(
        job_id=f["job"].id, actor_id="user_local_admin", knowledge_base_id="kb-test"
    )


def test_persisted_business_job_gate_and_return_recheck(job_fixture):
    f = job_fixture
    access = resolve(f)
    assert access.knowledge_base_ids == ("kb-test",)
    f["gate"].recheck(access)
    assert f["gate"].resolve(job_id=access.job_id, actor_id=access.actor_id) == access
    with pytest.raises(KnowledgeGovernanceError):
        f["gate"].require(
            job_id=access.job_id, actor_id=access.actor_id, knowledge_base_id="kb-future"
        )


@pytest.mark.parametrize(
    "change",
    [
        "direct",
        "terminal",
        "user",
        "actor",
        "application",
        "publication",
        "publication_hash",
        "session",
        "role",
        "membership",
        "expired",
        "kb",
        "tool",
        "detail",
        "snapshot",
        "old_hash",
        "cross_application",
        "agent_tool",
        "published_tool",
        "agent_publication",
        "service_actor",
    ],
)
def test_current_boundary_changes_fail_closed(job_fixture, change):
    f, db = job_fixture, job_fixture["runtime"].database
    access = resolve(f)
    if change == "actor":
        with pytest.raises(AppError):
            f["gate"].resolve(job_id=access.job_id, actor_id="other-user")
        return
    if change == "cross_application":
        other = _active_application(f["runtime"], "kb-other-app", capabilities=())
        db.execute(
            "update agent_job set business_application_id=? where id=?",
            (other["id"], access.job_id),
        )
        with pytest.raises(AppError):
            resolve(f)
        return
    commands = {
        "direct": "update agent_job set business_application_id=null",
        "terminal": "update agent_job set status='SUCCEEDED'",
        "user": "update app_user set status='disabled' where id='user_local_admin'",
        "application": "update business_application set status='disabled'",
        "publication": "update business_application_publication set snapshot_json='{}'",
        "publication_hash": "update agent_job set business_application_config_hash='wrong'",
        "session": "update agent_session set application_publication_id=null",
        "role": "update rbac_role set status='disabled' where code='ones-mcp-runtime-reader'",
        "membership": "update rbac_user_role set status='disabled' where role_id in (select id from rbac_role where code='ones-mcp-runtime-reader')",
        "expired": "update rbac_user_role set expires_at='2000-01-01T00:00:00+00:00'",
        "kb": "delete from rbac_role_application_knowledge_base",
        "tool": "delete from rbac_role_application_mcp_tool where tool_identifier='knowledge_search'",
        "detail": "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'",
        "snapshot": "update agent_job_mcp_tool_snapshot set snapshot_hash='" + "f" * 64 + "'",
        "old_hash": "update agent_job_mcp_tool_snapshot set authorization_hash='" + "f" * 64 + "'",
        "cross_application": "update agent_job set business_application_id=null",
        "agent_tool": "update agent_publication_mcp_tool set schema_hash='"
        + "f" * 64
        + "' where tool_identifier='knowledge_search'",
        "published_tool": "delete from business_application_publication_mcp_tool where tool_identifier='knowledge_search'",
        "agent_publication": "update agent_publication set snapshot_json='{}'",
        "service_actor": "update app_user set account_type='service' where id='user_local_admin'",
    }
    db.execute(commands[change])
    with pytest.raises(AppError):
        f["gate"].recheck(access)


def test_expanded_role_does_not_expand_frozen_job(job_fixture):
    f, db = job_fixture, job_fixture["runtime"].database
    before = resolve(f)
    db.execute(
        "insert into rbac_role_application_knowledge_base(application_access_id,knowledge_base_id,created_at) "
        "select application_access_id,'kb-future',created_at from rbac_role_application_knowledge_base"
    )
    after = resolve(f)
    assert after.knowledge_base_ids == before.knowledge_base_ids
    assert before.authorization_hash == after.authorization_hash
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_authorization_changed"):
        f["gate"].recheck(before)


def test_legacy_job_without_frozen_kb_facts_is_denied(job_fixture):
    f, db = job_fixture, job_fixture["runtime"].database
    row = db.execute_one(
        "select business_application_route_decision_json as value from agent_job where id=?",
        (f["job"].id,),
    )
    route = json.loads(row["value"])
    route["runtime_authorization"].pop("knowledge_grants")
    db.execute(
        "update agent_job set business_application_route_decision_json=? where id=?",
        (json.dumps(route), f["job"].id),
    )
    db.execute(
        "update agent_job_mcp_tool_snapshot set authorization_hash=? where job_id=?",
        (fingerprint(route["runtime_authorization"]), f["job"].id),
    )
    with pytest.raises(KnowledgeGovernanceError):
        resolve(f)


def test_knowledge_freezing_does_not_require_environment_scope(job_fixture):
    f, db = job_fixture, job_fixture["runtime"].database
    access = resolve(f)
    db.execute("delete from rbac_role_application_scope")
    publication = db.execute_one(
        "select config_hash from business_application_publication where id=?",
        (access.application_publication_id,),
    )
    facts = f["runtime"].business_authorization_service.capture_runtime_facts(
        user_id=access.actor_id,
        application_id=access.application_id,
        publication_id=access.application_publication_id,
        publication_config_hash=publication["config_hash"],
    )
    grants = {row["tool_identifier"]: row["source_role_codes"] for row in facts["tool_grants"]}
    assert all(grants[name] for name in KNOWLEDGE_TOOLS)
    assert not grants["ones_get_work_item_detail"]  # 非知识工具原冻结合同不变。


def test_direct_agent_is_rejected_before_job_creation(job_fixture):
    c = job_fixture["runtime"]
    # 仅绕过旧项目 use grant，以证明即使拥有该 grant 也无法旁路业务应用边界。
    from unittest.mock import patch

    before = c.database.execute_one("select count(*) as n from agent_job")["n"]
    with patch.object(c.permission_service, "require_action"), pytest.raises(AppError) as error:
        c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="synthetic-direct-knowledge",
                user_message="合成测试",
                requester_id="user_local_admin",
                fixed_agent_publication_id="agent_publication_default_v1",
                agent_code="default-diagnostic-agent",
            )
        )
    assert error.value.error_code == "knowledge_business_application_required"
    assert c.database.execute_one("select count(*) as n from agent_job")["n"] == before


def test_knowledge_principal_uses_gate_and_exact_audience_scope(job_fixture):
    f, c = job_fixture, job_fixture["runtime"]
    issuer = PrincipalTokenIssuer(
        c.database,
        c.mcp_tool_snapshot_service,
        c.business_authorization_service,
        f["issuer"].signing_key,
        c.audit_service,
        server_policies=mcp_server_policy.MCP_SERVER_POLICIES,
        knowledge_job_gate=f["gate"],
    )
    verifier = PrincipalTokenVerifier(
        PrincipalJwks.from_dict(issuer.signing_key.public_jwks()),
        expected_audience="knowledge-mcp",
        server_policies=mcp_server_policy.MCP_SERVER_POLICIES,
    )
    token = issuer.issue_business_mcp_for_job(job_id=f["job"].id, server_code="knowledge-mcp")
    claims = verifier.verify_for_running_job(
        token,
        database=c.database,
        snapshot_service=c.mcp_tool_snapshot_service,
        required_scope=mcp_server_policy.mcp_invoke_scope("knowledge-mcp", "knowledge_search"),
    )
    assert claims["sub"] == "user_local_admin"
    assert len(claims["scope"]) == 2
    with pytest.raises(AppError):
        verifier.verify_for_running_job(
            f["token"],
            database=c.database,
            snapshot_service=c.mcp_tool_snapshot_service,
            required_scope=mcp_server_policy.mcp_invoke_scope("knowledge-mcp", "knowledge_search"),
        )
    with pytest.raises(AppError):
        f["service"].authenticate(token)
    c.database.execute(
        "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'"
    )
    with pytest.raises(AppError):
        issuer.issue_business_mcp_for_job(job_id=f["job"].id, server_code="knowledge-mcp")
