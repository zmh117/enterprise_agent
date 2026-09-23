"""真实合成 Job/角色/来源/发布索引上的知识目录分页，不访问真实 Provider。"""

from dataclasses import replace
import json

import pytest

from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.reader_access import KnowledgePrincipalAccess
from app.shared.exceptions import AppError
from backend.tests.test_knowledge_job_access import knowledge_contract as knowledge_contract_fixture
from backend.tests.test_knowledge_readability import readable_fixture as readable_fixture_impl
from backend.tests.test_knowledge_readability_bridge import bridge_fixture as bridge_fixture_impl

knowledge_contract = knowledge_contract_fixture
readable_fixture = readable_fixture_impl
bridge_fixture = bridge_fixture_impl


@pytest.fixture
def directory_fixture(bridge_fixture):
    f = bridge_fixture
    directory = KnowledgeDirectory(
        KnowledgePrincipalAccess(f["bridge"].gateway.principal, f["endpoint"].gate),
        f["endpoint"].resources,
        f["runtime"].audit_service,
    )
    return {**f, "directory": directory}


def listing(f, arguments=None):
    return f["directory"].list_bases(token=f["knowledge_token"], arguments=arguments or {})


@pytest.mark.parametrize(
    "readable_fixture", [0, 1, 50, 51, 121, {"bases": 3, "documents": 3}], indirect=True
)
def test_stable_keyset_every_authorized_base_once(directory_fixture, readable_fixture):
    f = directory_fixture
    expected = f["runtime"].database.execute(
        "select knowledge_base_id from \"knowledge.retrieval_resource\" where status='enabled' order by knowledge_base_id"
    )
    ids, args, pages = [], {}, []
    while True:
        page = listing(f, args)
        pages.append(page)
        assert set(page) == {"items", "has_more", "next_cursor"}
        assert len(page["items"]) <= 50
        for item in page["items"]:
            assert set(item) == {"knowledge_base_id", "code", "name", "status"}
            assert item["status"] == "AVAILABLE"
        ids.extend(item["knowledge_base_id"] for item in page["items"])
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert len(page["items"]) == 50 and len(page["next_cursor"]) <= 4096
        args = {"cursor": page["next_cursor"]}
    assert ids == [row["knowledge_base_id"] for row in expected]
    assert not f["calls"] and not f["exchanges"]
    if len(pages) > 1:
        replay = listing(f, {"cursor": pages[0]["next_cursor"]})
        assert replay["items"] == pages[1]["items"] and replay["has_more"] == pages[1]["has_more"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"cursor": ""},
        {"cursor": None},
        {"cursor": 3},
        {"cursor": "x" * 4097},
        {"cursor": "bad"},
        {"cursor": "汉字"},
        {"limit": 500},
        {"actor_id": "other"},
        {"environment": "jnw"},
    ],
)
def test_strict_input_no_catalog_side_channel(directory_fixture, arguments):
    f = directory_fixture
    with pytest.raises(KnowledgeGovernanceError):
        listing(f, arguments)
    assert not f["calls"] and not f["exchanges"]


@pytest.mark.parametrize("readable_fixture", [51], indirect=True)
@pytest.mark.parametrize(
    "change",
    [
        "tamper",
        "expired",
        "restart",
        "actor",
        "job",
        "application",
        "snapshot_hash",
        "authorization_hash",
        "role",
        "resource",
        "binding",
        "identity",
        "name",
    ],
)
def test_cursor_isolated_and_invalidated(directory_fixture, change, monkeypatch):
    f = directory_fixture
    directory, db = f["directory"], f["runtime"].database
    cursor = listing(f)["next_cursor"]
    code = "knowledge_cursor_invalid"
    original = directory.access.authenticate
    if change == "tamper":
        cursor = cursor[:30] + ("A" if cursor[30] != "A" else "B") + cursor[31:]
    elif change == "expired":
        now = directory._clock()
        directory._clock = lambda: now + 301
    elif change == "restart":
        f["directory"] = KnowledgeDirectory(directory.access, directory.resources, directory.audit)
    elif change in {"actor", "job", "application", "snapshot_hash", "authorization_hash"}:
        field = {"actor": "actor_id", "job": "job_id", "application": "application_id"}.get(
            change, change
        )
        # 游标层独立测试绑定差异；真实 JWT/持久化主体差异另由 Job/Principal 用例覆盖。
        if change == "actor":
            monkeypatch.setattr(directory, "_binding", lambda access: "other-user-binding")
        else:
            monkeypatch.setattr(
                directory.access,
                "authenticate",
                lambda *a: replace(original(*a), **{field: "other"}),
            )
    else:
        sql = {
            "role": "delete from rbac_role_application_knowledge_base where knowledge_base_id='kb-page-0001'",
            "resource": "update \"knowledge.retrieval_resource\" set status='disabled' where knowledge_base_id='kb-page-0001'",
            "binding": "update \"knowledge.source\" set source_system='other'",
            "identity": 'update user_external_identity set metadata_json=\'{"team_uuids":["other"],"default_team_id":"other"}\' where provider=\'ones\'',
            "name": "update \"knowledge.retrieval_resource\" set name='changed' where knowledge_base_id='kb-page-0001'",
        }[change]
        db.execute(sql)
        code = "knowledge_cursor_stale"
    with pytest.raises(KnowledgeGovernanceError) as exc:
        listing(f, {"cursor": cursor})
    assert exc.value.error_code == code


@pytest.mark.parametrize("mutation", ["kb", "role", "detail", "identity", "job"])
def test_return_recheck_drops_directory_after_revocation(directory_fixture, monkeypatch, mutation):
    f = directory_fixture
    original = f["directory"]._catalog
    calls = 0

    def catalog(*args):
        nonlocal calls
        result = original(*args)
        calls += 1
        if calls == 1:
            f["runtime"].database.execute(
                {
                    "kb": "delete from rbac_role_application_knowledge_base",
                    "role": "update rbac_user_role set status='disabled'",
                    "detail": "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'",
                    "identity": "update user_external_identity set status='disabled' where provider='ones'",
                    "job": "update agent_job set status='SUCCEEDED'",
                }[mutation]
            )
        return result

    monkeypatch.setattr(f["directory"], "_catalog", catalog)
    with pytest.raises(AppError):
        listing(f)


def test_current_user_source_and_no_document_metadata(directory_fixture):
    f = directory_fixture
    assert len(listing(f)["items"]) == 1
    encoded = json.dumps(listing(f), ensure_ascii=False)
    for forbidden in (
        "合成正文",
        "document_count",
        "chunk_ids",
        "team_id",
        "query",
        "index_id",
        f["knowledge_token"],
        f["mock"].token,
    ):
        assert forbidden not in encoded
    db = f["runtime"].database
    db.execute(
        "update user_external_identity set tenant_code='other-instance' where provider='ones'"
    )
    # 目录只说明 KB 可检索；固定 ONES 实例及逐项权限由内部桥再次校验。
    assert len(listing(f)["items"]) == 1
    with pytest.raises(AppError):
        f["directory"].list_bases(token=f["token"], arguments={})
