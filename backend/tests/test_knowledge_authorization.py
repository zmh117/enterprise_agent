"""角色应用 KB 允许范围的合成合同；不代表 Knowledge MCP / ONES 实环境验收。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.bootstrap import build_test_container
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.knowledge.infrastructure.storage import insert
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import digest
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_role_authorization_control_center import (
    ADMIN_ID,
    _active_application,
    _admin_headers,
    _business_role,
    _container,
    _settings,
    _topology,
)


# 已注册的只读 Tool 用于验证通用 RBAC 联合求值，不冒充尚未注册的 Knowledge Tool。
TOOL = "query_database"


def add_base(c, key):
    insert(
        c.database,
        "knowledge_base",
        {
            "id": key,
            "code": key,
            "display_name": f"合成知识库 {key}",
            "description": "合成授权测试",
            "state": "storage_only",
            "created_at": now(),
        },
    )


def access(app, ids=(), *, tools=(TOOL,), **extra):
    return {
        "application_id": app["id"],
        "tool_identifiers": list(tools),
        "scopes": [],
        "knowledge_base_ids": list(ids),
        **extra,
    }


@pytest.fixture
def fixture(request, tmp_path):
    # SQLite shared-cache memory databases reject concurrent reads while a table is written.
    # Use an isolated file database for the real concurrent-save test, as existing RBAC tests do.
    c = (
        build_test_container(
            replace(_settings(), database_dsn=f"sqlite:///{tmp_path / 'kb-auth.sqlite'}"),
            migrate=True,
            seed=True,
        )
        if getattr(request, "param", None) == "file"
        else _container()
    )
    add_base(c, "kb-ones")
    add_base(c, "kb-ops")
    apps = [_active_application(c, code, capabilities=(TOOL,)) for code in ("app-one", "app-two")]
    user = c.identity_repository.create_user(username="kb-reader", display_name="合成知识用户")
    role = _business_role(
        c,
        code="kb-reader",
        user_id=user["id"],
        applications=[access(apps[0], ["kb-ones"]), access(apps[1])],
    )
    yield c, apps, user, role
    c.database.close()


def decide(c, app, user, key="kb-ones"):
    return c.business_authorization_service.decide(
        user_id=user["id"],
        application_id=app["id"],
        tool_identifier=TOOL,
        knowledge_base_id=key,
        stage="tool_call",
    )


def save(c, role, apps, *, revision=2, actor=ADMIN_ID):
    return c.authorization_center_service.replace_business_access(
        actor_id=actor,
        role_id=role["id"],
        expected_revision=revision,
        applications=apps,
        confirmed=True,
        reason="合成知识库授权变更",
    )


def test_same_role_app1_granted_app2_not_granted_and_preview_agrees(fixture):
    c, apps, user, role = fixture
    assert decide(c, apps[0], user)["allowed"]
    assert not decide(c, apps[1], user)["allowed"]
    assert not decide(c, apps[0], user, "kb-ops")["allowed"]
    assert not decide(c, apps[0], {"id": ADMIN_ID})["allowed"]
    for app in apps:
        projection = c.business_authorization_service.knowledge_access_projection(
            user_id=user["id"],
            application_id=app["id"],
            tool_identifiers=(TOOL,),
        )
        assert bool(projection) == decide(c, app, user)["allowed"]
    app = create_app(c.settings, container_factory=lambda _: c)
    app.state.container = c
    client = TestClient(app)
    preview = client.post(
        "/api/admin/authorization/explanations",
        headers=_admin_headers(),
        json={
            "user_id": user["id"],
            "application_id": apps[1]["id"],
            "tool_identifier": TOOL,
            "knowledge_base_id": "kb-ones",
            "stage": "tool_call",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["decision"]["reason"] == "application_knowledge_base_denied"
    detail = c.authorization_center_service.role_detail(actor_id=ADMIN_ID, role_id=role["id"])
    assert [row["knowledge_base_ids"] for row in detail["business"]["applications"]] == [
        ["kb-ones"],
        [],
    ]


def test_unconfigured_role_is_not_a_veto_but_roles_cannot_splice_tool_and_kb(fixture):
    c, apps, user, role = fixture
    _business_role(c, code="no-knowledge", user_id=user["id"], applications=[access(apps[0])])
    assert decide(c, apps[0], user)["allowed"]
    save(c, role, [access(apps[0], ["kb-ones"], tools=())])
    assert not decide(c, apps[0], user)["allowed"]
    assert (
        c.business_authorization_service.knowledge_access_projection(
            user_id=user["id"],
            application_id=apps[0]["id"],
            tool_identifiers=(TOOL,),
        )
        == ()
    )
    _business_role(
        c, code="complete-allow", user_id=user["id"], applications=[access(apps[0], ["kb-ones"])]
    )
    assert decide(c, apps[0], user)["source_role_codes"] == ["complete-allow"]


@pytest.mark.parametrize(
    "target", ["user", "role", "membership", "expired", "application", "access", "kb_revoke"]
)
def test_current_revocation_blocks_decision_and_projection(fixture, target):
    c, apps, user, role = fixture
    assert decide(c, apps[0], user)["allowed"]
    if target == "user":
        c.database.execute("update app_user set status='disabled' where id=?", (user["id"],))
    elif target == "role":
        c.database.execute("update rbac_role set status='disabled' where id=?", (role["id"],))
    elif target in ("membership", "expired"):
        clause = (
            "status='disabled'"
            if target == "membership"
            else "expires_at='2000-01-01T00:00:00+00:00'"
        )
        c.database.execute(
            f"update rbac_user_role set {clause} where role_id=? and user_id=?",
            (role["id"], user["id"]),
        )
    elif target == "application":
        c.database.execute(
            "update business_application set status='disabled' where id=?", (apps[0]["id"],)
        )
    elif target == "access":
        c.database.execute(
            "update rbac_role_application_access set status='disabled' where role_id=?",
            (role["id"],),
        )
    else:
        save(c, role, [access(apps[0])])
    assert not decide(c, apps[0], user)["allowed"]
    assert (
        c.business_authorization_service.knowledge_access_projection(
            user_id=user["id"],
            application_id=apps[0]["id"],
            tool_identifiers=(TOOL,),
        )
        == ()
    )


def test_current_all_is_explicit_and_copy_preserves_app_partition(fixture):
    c, apps, user, role = fixture
    result = save(c, role, [access(apps[0], knowledge_current_all=True), access(apps[1])])
    assert result["applications"][0]["knowledge_base_ids"] == ["kb-ones", "kb-ops"]
    add_base(c, "kb-future")
    assert not decide(c, apps[0], user, "kb-future")["allowed"]
    copied = c.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code="copy-kb",
        name="复制合成角色",
        description="",
        purpose_tags=[],
        copy_from_role_id=role["id"],
    )
    assert [a["knowledge_base_ids"] for a in copied["business"]["applications"]] == [
        ["kb-ones", "kb-ops"],
        [],
    ]
    save(c, role, [], revision=3)


@pytest.mark.parametrize(
    "extra",
    [
        {"effect": "deny"},
        {"deny": ["kb-ones"]},
        {"knowledge_base_ids": ["*"]},
        {"knowledge_base_ids": ["kb-ones", "kb-ones"]},
        {"knowledge_base_ids": ["missing"]},
        {"knowledge_base_ids": [3]},
        {"knowledge_base_ids": [{"id": "kb-ones"}]},
        {"knowledge_current_all": "true"},
        {"knowledge_base_ids": ["x" * 129]},
    ],
)
def test_invalid_scope_is_rejected_atomically_without_erasing_grants(fixture, extra):
    c, apps, user, role = fixture
    item = access(apps[0], ["kb-ones"])
    item.update(extra)
    with pytest.raises(NonRetryableExecutionError):
        save(c, role, [item])
    assert decide(c, apps[0], user)["allowed"]
    assert c.authorization_center_repository.get_role(role["id"])["business_revision"] == 2


@pytest.mark.parametrize("field", ["effect", "deny", "knowledge_denies"])
def test_api_forbids_deny_fields(fixture, field):
    c, apps, _, role = fixture
    app = create_app(c.settings, container_factory=lambda _: c)
    app.state.container = c
    client = TestClient(app)
    response = client.put(
        f"/api/admin/authorization/roles/{role['id']}/business-access",
        headers=_admin_headers(),
        json={
            "expected_revision": 2,
            "confirmed": True,
            "reason": "合成测试",
            "applications": [access(apps[0], **{field: "deny"})],
        },
    )
    assert response.status_code == 422


def test_api_roundtrip_requires_management_permission_and_keeps_app_scopes_separate(fixture):
    c, apps, user, role = fixture
    app = create_app(c.settings, container_factory=lambda _: c)
    app.state.container = c
    client = TestClient(app)
    endpoint = f"/api/admin/authorization/roles/{role['id']}/business-access"
    payload = {
        "expected_revision": 2,
        "confirmed": True,
        "reason": "合成授权",
        "applications": [access(apps[0], ["kb-ones", "kb-ops"]), access(apps[1])],
    }
    denied = client.put(endpoint, headers={"x-admin-user-id": user["id"]}, json=payload)
    assert denied.status_code == 403
    assert (
        c.database.execute_one(
            "select id from audit_event where event_type='permission.rbac.denied' and actor_id=?",
            (user["id"],),
        )
        is not None
    )
    assert not decide(c, apps[0], user, "kb-ops")["allowed"]
    saved = client.put(endpoint, headers=_admin_headers(), json=payload)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 3
    assert [a["knowledge_base_ids"] for a in saved.json()["applications"]] == [
        ["kb-ones", "kb-ops"],
        [],
    ]
    assert decide(c, apps[0], user, "kb-ops")["allowed"]
    assert not decide(c, apps[1], user, "kb-ops")["allowed"]


def test_business_revision_hash_and_stale_save_do_not_touch_other_partitions(fixture):
    c, apps, user, role = fixture
    service = c.business_authorization_service

    def facts():
        return service.capture_runtime_facts(
            user_id=user["id"],
            application_id=apps[0]["id"],
            publication_id=apps[0]["publication_id"],
            publication_config_hash=apps[0]["publication_config_hash"],
        )

    before = facts()
    assert before["knowledge_grants"][0]["knowledge_base_ids"] == ["kb-ones"]
    assert before == facts()
    result = save(c, role, [access(apps[0], ["kb-ops"])])
    assert result["revision"] == 3
    assert digest(facts()) != digest(before)
    with pytest.raises(NonRetryableExecutionError) as error:
        save(c, role, [])
    assert error.value.error_code == "revision_conflict"
    assert decide(c, apps[0], user, "kb-ops")["allowed"]
    assert not decide(c, apps[0], user)["allowed"]
    current = c.authorization_center_repository.get_role(role["id"])
    assert current["admin_revision"] == role["admin_revision"]
    assert current["metadata_revision"] == role["metadata_revision"]


@pytest.mark.parametrize("attempt", range(5))
@pytest.mark.parametrize("fixture", ["file"], indirect=True)
def test_competing_business_updates_have_one_winner(fixture, attempt):
    c, apps, _, role = fixture
    barrier = Barrier(2)

    def update(key):
        barrier.wait(timeout=5)
        try:
            save(c, role, [access(apps[0], [key])])
            return "saved"
        except NonRetryableExecutionError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["kb-ones", "kb-ops"]))
    assert sorted(results) == ["revision_conflict", "saved"]
    rows = c.authorization_center_repository.list_business_access(role["id"])
    assert len(rows) == 1 and len(rows[0]["knowledge_base_ids"]) == 1


def test_real_job_snapshot_hash_includes_kb_grant_without_rewriting_old_jobs(fixture):
    c, apps, user, role = fixture
    scope, _ = _topology(c)
    app = apps[0]

    def create_job(key):
        return c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key=key,
                user_message="合成授权哈希测试",
                requester_id=user["id"],
                source_channel="debug_api",
                reply_route={
                    "type": "dingtalk_conversation",
                    "connector_id": "connector-dingtalk-enterprise-default",
                    "target": {"conversation_id": "synthetic-kb-test"},
                    "options": {},
                },
                business_application_id=app["id"],
                business_application_code=app["code"],
                business_application_publication_id=app["publication_id"],
                business_application_config_hash=app["publication_config_hash"],
                routing_context={
                    "project_code": "default",
                    "environment": "local",
                    "base": "base-one",
                    "workshop": "",
                    "service": "",
                },
                fixed_agent_publication_id="agent_publication_default_v1",
                fixed_agent_revision=1,
                fixed_agent_config_hash=c.agent_config_service.publication(
                    "agent_publication_default_v1"
                )["config_hash"],
                agent_code="default-diagnostic-agent",
            )
        )

    save(c, role, [access(app, ["kb-ones"], scopes=[scope])])
    old_job = create_job("kb-job-before")
    old_snapshot = c.mcp_tool_snapshot_service.verify(old_job.id)
    save(c, role, [access(app, ["kb-ops"], scopes=[scope])], revision=3)
    new_job = create_job("kb-job-after")
    new_snapshot = c.mcp_tool_snapshot_service.verify(new_job.id)
    assert new_snapshot["authorization_hash"] != old_snapshot["authorization_hash"]
    assert c.mcp_tool_snapshot_service.verify(old_job.id) == old_snapshot
    assert not decide(c, app, user, "kb-ones")["allowed"]


def test_delegation_and_catalog_are_application_bounded(fixture):
    c, apps, user, role = fixture
    target = c.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code="delegate-target",
        name="合成委派目标",
        description="",
        purpose_tags=[],
    )["role"]
    c.authorization_center_service.replace_admin_capabilities(
        actor_id=ADMIN_ID,
        role_id=role["id"],
        expected_revision=1,
        bindings=[{"capability_code": "authorization.manage", "resource_code": target["id"]}],
        confirmed=True,
        reason="合成授权",
    )
    catalog = c.authorization_center_service.assignable_catalog(actor_id=user["id"])
    by_app = {a["id"]: a for a in catalog["applications"]}
    assert [b["id"] for b in by_app[apps[0]["id"]]["knowledge_bases"]] == ["kb-ones"]
    assert by_app[apps[1]["id"]]["knowledge_bases"] == []
    with pytest.raises(NonRetryableExecutionError):
        save(c, target, [access(apps[1], ["kb-ones"])], revision=1, actor=user["id"])
    with pytest.raises(NonRetryableExecutionError):
        save(c, target, [access(apps[0], ["kb-ops"])], revision=1, actor=user["id"])
    result = save(
        c, target, [access(apps[0], knowledge_current_all=True)], revision=1, actor=user["id"]
    )
    assert result["applications"][0]["knowledge_base_ids"] == ["kb-ones"]


def test_knowledge_tool_delegation_cannot_join_separate_actor_roles(fixture):
    c, apps, user, _ = fixture
    separate = _business_role(
        c, code="only-tool", user_id=user["id"], applications=[access(apps[0])]
    )
    row = c.database.execute_one(
        "select id from rbac_role_application_access where role_id=?", (separate["id"],)
    )
    # Isolated future-tool grant fixture: this does not register or publish Knowledge MCP.
    c.database.execute(
        "update rbac_role_application_mcp_tool set tool_identifier='knowledge_search' where application_access_id=?",
        (row["id"],),
    )
    with pytest.raises(NonRetryableExecutionError):
        c.authorization_center_service._knowledge_selection(
            access(apps[0], ["kb-ones"]),
            actor_id=user["id"],
            platform_admin=False,
            tools=["knowledge_search"],
            field="applications.0",
        )
