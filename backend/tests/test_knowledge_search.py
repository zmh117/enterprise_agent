"""合成在线检索编排、HTTP 双身份桥和预算边界，不代表真实召回质量。"""

from app.modules.knowledge.infrastructure.reader_access import job_budget

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import json
from copy import deepcopy

import httpx
import pytest

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.infrastructure.reader_access import KnowledgePrincipalAccess
from app.modules.knowledge.infrastructure.readability_client import KnowledgeReadabilityClient
from app.modules.knowledge.application.readability import BRIDGE_PATH, ReadabilityCandidates
from app.modules.knowledge.application.search import KnowledgeSearch
from app.modules.knowledge.application import retrieval_budget
from app.modules.knowledge.application.retrieval_budget import DEADLINE_HEADER, current_budget
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.vector_clients import InternalHttp
from app.shared.exceptions import AppError
from backend.tests.test_knowledge_job_access import knowledge_contract as knowledge_contract_fixture
from backend.tests.test_knowledge_readability import readable_fixture as readable_fixture_impl
from backend.tests.test_knowledge_readability_bridge import bridge_fixture as bridge_fixture_impl

knowledge_contract = knowledge_contract_fixture
readable_fixture = readable_fixture_impl
bridge_fixture = bridge_fixture_impl


@pytest.fixture
def search_fixture(bridge_fixture):
    f = bridge_fixture
    hops = []

    def transport(request):
        assert str(request.url) == "http://api-server:8000" + BRIDGE_PATH
        assert request.headers["authorization"] == "Bearer " + f["service_token"]
        assert request.headers["x-knowledge-principal"] == "Bearer " + f["knowledge_token"]
        hops.append(request.extensions["timeout"]["read"])
        response = f["bridge_client"].post(
            BRIDGE_PATH,
            content=request.content,
            headers={
                key: value
                for key, value in request.headers.items()
                if key
                in {
                    "authorization",
                    "x-knowledge-principal",
                    "content-type",
                    DEADLINE_HEADER.lower(),
                }
            },
        )
        return httpx.Response(response.status_code, content=response.content)

    client = KnowledgeReadabilityClient(
        SimpleNamespace(access_token=lambda: f["service_token"]),
        transport=httpx.MockTransport(transport),
    )
    search = KnowledgeSearch(
        KnowledgePrincipalAccess(f["bridge"].gateway.principal, f["endpoint"].gate),
        f["endpoint"].resources,
        f["vector"].embedding,
        f["vector"].qdrant,
        client,
        f["runtime"].audit_service,
    )
    return {**f, "search": search, "hops": hops}


def search(f, **extra):
    return f["search"].search(
        token=f["knowledge_token"],
        arguments={
            "knowledge_base_id": f["body"]["knowledge_base_id"],
            "query": "合成查询-不要记录",
            **extra,
        },
    )


def test_reference_search_through_both_http_hops_no_text_or_token(search_fixture):
    f = search_fixture
    result = search(f)
    assert len(result["documents"]) == 1 and result["partial"] is False
    hit = result["documents"][0]
    assert hit["work_item_uuid"].startswith("MOCK-ONES-TASK-")
    assert 1 <= len(hit["evidence"]) <= 3
    assert f["vector"].qdrant.search_limits == [200]
    assert f["calls"] == ["POST"] and len(f["hops"]) == 1 and f["hops"][0] <= 60
    safe = json.dumps(result, ensure_ascii=False) + json.dumps(
        f["runtime"].database.execute("select * from audit_event"), ensure_ascii=False, default=str
    )
    for forbidden in (
        "合成查询-不要记录",
        "合成正文",
        "embedding_text",
        "evidence_text",
        "candidates",
        "filtered",
        f["knowledge_token"],
        f["service_token"],
        f["mock"].token,
    ):
        assert forbidden not in safe
    assert current_budget() is None


@pytest.mark.parametrize(
    "changes",
    [
        {"query": ""},
        {"query": " "},
        {"query": "x" * 2001},
        {"query": []},
        {"query": "\ud800"},
        {"top_k": 0},
        {"top_k": 21},
        {"top_k": True},
        {"top_k": 1.0},
        {"collection": "anything"},
        {"filter": {}},
        {"team_id": "other"},
        {"actor": "other"},
        {"url": "https://untrusted.invalid"},
        {"vector": []},
    ],
)
def test_strict_search_inputs_before_external_io(search_fixture, changes):
    f = search_fixture
    with pytest.raises(KnowledgeGovernanceError):
        search(f, **changes)
    assert f["vector"].qdrant.search_limits == [] and not f["hops"]


@pytest.mark.parametrize("query,top_k", [("x", 1), ("x" * 2000, 20)])
def test_query_top_k_boundaries(search_fixture, query, top_k):
    assert search(search_fixture, query=query, top_k=top_k)["documents"]


@pytest.mark.parametrize("status", [403, 404, 401, 429, 500])
def test_permission_filter_is_not_provider_failure(search_fixture, status):
    f = search_fixture

    def fail(*args):
        raise f["provider_http"].status_error(status)

    f["provider_http"]._open_response = fail
    if status in {403, 404}:
        result = search(f)
        assert result["documents"] == [] and result["partial"] is False
        assert "denied" not in json.dumps(result)
    else:
        with pytest.raises(KnowledgeGovernanceError, match="knowledge_readability_failed"):
            search(f)


@pytest.mark.parametrize("corruption", ["duplicate", "nan", "payload", "too_many", "stale"])
def test_current_candidate_contract(search_fixture, corruption, monkeypatch):
    f = search_fixture
    original = f["vector"].qdrant.search

    def candidates(*args):
        points = deepcopy(original(*args))
        if corruption == "duplicate":
            points.append(points[0])
        elif corruption == "nan":
            points[0]["score"] = float("nan")
        elif corruption == "payload":
            points[0]["payload"]["document_id"] = "other"
        elif corruption == "too_many":
            points *= 201
        elif corruption == "stale":
            for point in points:
                point["payload"]["chunk_id"] = "unknown-chunk"
        return points

    monkeypatch.setattr(f["vector"].qdrant, "search", candidates)
    if corruption == "stale":
        assert search(f)["documents"] == []
    else:
        with pytest.raises(KnowledgeGovernanceError, match="knowledge_search_dependency_failed"):
            search(f)
    assert not f["hops"]


@pytest.mark.parametrize("change", ["kb", "member", "identity", "resource", "candidate", "job"])
def test_final_recheck_after_all_upstream_success(search_fixture, change, monkeypatch):
    f = search_fixture
    original = f["search"].readability.check

    def check(**kwargs):
        result = original(**kwargs)
        f["runtime"].database.execute(
            {
                "kb": "delete from rbac_role_application_knowledge_base",
                "member": "update rbac_user_role set status='disabled'",
                "identity": "update user_external_identity set status='disabled' where provider='ones'",
                "resource": "update \"knowledge.retrieval_resource\" set status='disabled'",
                "candidate": 'update "knowledge.document_chunk" set evidence_hash=\''
                + "0" * 64
                + "'",
                "job": "update agent_job set status='SUCCEEDED'",
            }[change]
        )
        return result

    monkeypatch.setattr(f["search"].readability, "check", check)
    with pytest.raises(AppError):
        search(f)


class SyntheticReadability:
    """仅大候选预算用例的权限替身；完整 HTTP 权限链在上面单独验证。"""

    def __init__(self, f, *, allow_after=0, failure_after=None):
        self.f, self.allow_after, self.failure_after = f, allow_after, failure_after
        self.checked = []

    def check(self, *, token, request):
        if self.failure_after is not None and len(self.checked) >= self.failure_after:
            raise KnowledgeGovernanceError("knowledge_readability_failed")
        facts = ReadabilityCandidates.load(self.f["endpoint"].resources, request)
        items = []
        for chunk in request.chunk_ids:
            row = facts.documents[facts.evidence[chunk]["document_id"]]
            allowed = len(self.checked) >= self.allow_after
            self.checked.append(row["id"])
            item = {"chunk_id": chunk, "readable": allowed}
            if allowed:
                item.update(
                    task_id=row["external_id"],
                    document_id=row["id"],
                    revision_id=row["current_revision_id"],
                    source_id=facts.pin.source_id,
                    number=1,
                )
            items.append(item)
        return {
            "knowledge_base_id": request.knowledge_base_id,
            "resource_revision_id": request.resource_revision_id,
            "index_id": request.index_id,
            "job_id": self.f["job"].id,
            "actor_id": "user_local_admin",
            "items": items,
        }


@pytest.mark.parametrize("readable_fixture", [{"documents": 70}], indirect=True)
@pytest.mark.parametrize("allow_after", [0, 45, 60])
def test_fill_from_bounded_pool_never_check_more_than_50_work_items(search_fixture, allow_after):
    f = search_fixture
    readability = SyntheticReadability(f, allow_after=allow_after)
    f["search"].readability = readability
    result = search(f)
    assert len(readability.checked) <= 50 and len(set(readability.checked)) == len(
        readability.checked
    )
    assert f["vector"].qdrant.search_limits == [200]
    assert len(result["documents"]) == min(10, max(0, len(readability.checked) - allow_after))
    assert result["partial"] == (len(result["documents"]) < 10)
    if result["partial"]:
        assert result["partial_reason"] == "bounded_search"


@pytest.mark.parametrize("readable_fixture", [{"documents": 20}], indirect=True)
def test_failure_after_allowed_results_discards_entire_call(search_fixture):
    f = search_fixture
    f["search"].readability = SyntheticReadability(f, allow_after=8, failure_after=10)
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_readability_failed"):
        search(f)


def test_job_remaining_budget_and_retry_change(search_fixture):
    f = search_fixture
    budget = job_budget(f["runtime"].database, f["job"].id)
    assert 0 < budget.remaining() <= 60
    f["runtime"].database.execute(
        "update agent_job set retry_count=retry_count+1 where id=?", (f["job"].id,)
    )
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_job_denied"):
        budget.check()
    f["runtime"].database.execute(
        "update agent_job set locked_at=? where id=?",
        ((datetime.now(UTC) - timedelta(hours=2)).isoformat(), f["job"].id),
    )
    with pytest.raises(KnowledgeGovernanceError, match="budget_exhausted"):
        search(f)
    assert not f["hops"]


@pytest.mark.parametrize("late", [False, True])
def test_soft_cutoff_partial_and_late_result_discard(search_fixture, monkeypatch, late):
    f = search_fixture
    tick = [100.0]
    monkeypatch.setattr(retrieval_budget, "time", SimpleNamespace(monotonic=lambda: tick[0]))
    original = f["vector"].qdrant.search

    def query(*args):
        result = original(*args)
        tick[0] += 61 if late else 59.5
        return result

    monkeypatch.setattr(f["vector"].qdrant, "search", query)
    if late:
        with pytest.raises(KnowledgeGovernanceError, match="budget_exhausted"):
            search(f)
    else:
        result = search(f)
        assert result["documents"] == [] and result["partial"] is True
    assert not f["hops"] and current_budget() is None


def test_online_http_budget_disables_retry_without_changing_offline_default(
    search_fixture, monkeypatch
):
    f = search_fixture
    calls, sleeps = [], []

    def unavailable(request):
        calls.append(request.extensions["timeout"]["read"])
        return httpx.Response(500)

    http = InternalHttp("http://knowledge-qdrant:6333", transport=httpx.MockTransport(unavailable))
    from app.modules.knowledge.infrastructure import vector_clients

    monkeypatch.setattr(vector_clients.time, "sleep", lambda seconds: sleeps.append(seconds))
    try:
        with job_budget(f["runtime"].database, f["job"].id).activate():
            with pytest.raises(VectorError):
                http.request("GET", "/collections")
        assert len(calls) == 1 and calls[0] <= 60 and sleeps == []
        calls.clear()
        with pytest.raises(VectorError):
            http.request("GET", "/collections")
        assert len(calls) == 3 and sleeps == [1, 2]
    finally:
        http.close()


@pytest.mark.parametrize("stage", ["embedding_profile", "qdrant_profile", "embedding_query"])
@pytest.mark.parametrize("mutation", ["kb", "resource", "identity"])
def test_revocation_stops_next_upstream_stage(search_fixture, monkeypatch, stage, mutation):
    f = search_fixture
    target, method = {
        "embedding_profile": (f["search"].embedding, "check"),
        "qdrant_profile": (f["search"].qdrant, "check"),
        "embedding_query": (f["search"].embedding, "call"),
    }[stage]
    original = getattr(target, method)

    def revoke(*args, **kwargs):
        value = original(*args, **kwargs)
        f["runtime"].database.execute(
            {
                "kb": "delete from rbac_role_application_knowledge_base",
                "resource": "update \"knowledge.retrieval_resource\" set status='disabled'",
                "identity": "update user_external_identity set status='disabled' where provider='ones'",
            }[mutation]
        )
        return value

    monkeypatch.setattr(target, method, revoke)
    with pytest.raises(KnowledgeGovernanceError):
        search(f)
    assert not f["vector"].qdrant.search_limits and not f["hops"]
    assert current_budget() is None


@pytest.mark.parametrize("stage", ["embedding", "qdrant", "readability"])
def test_unexpected_dependency_exception_and_failure_audit_are_sanitized(
    search_fixture, monkeypatch, stage
):
    f = search_fixture
    leaked = "synthetic-private-body-" + f["knowledge_token"]
    target, method = {
        "embedding": (f["search"].embedding, "check"),
        "qdrant": (f["search"].qdrant, "search"),
        "readability": (f["search"].readability, "check"),
    }[stage]

    def fail(*args, **kwargs):
        raise RuntimeError(leaked)

    monkeypatch.setattr(target, method, fail)
    with pytest.raises(KnowledgeGovernanceError) as failure:
        search(f)
    assert failure.value.error_code == "knowledge_search_dependency_failed"
    audits = f["runtime"].database.execute(
        "select * from audit_event where event_type='knowledge.search.denied'"
    )
    assert len(audits) == 1
    assert leaked not in str(failure.value) + json.dumps(audits, default=str)
    assert "合成查询-不要记录" not in json.dumps(audits, ensure_ascii=False, default=str)
    assert failure.value.__suppress_context__ and current_budget() is None


def test_four_inflight_limit_and_no_slot_leak_on_failure(search_fixture):
    f = search_fixture
    service = f["search"]
    for _ in range(4):
        assert service._slots.acquire(blocking=False)
    try:
        with pytest.raises(KnowledgeGovernanceError, match="knowledge_search_busy"):
            search(f)
        assert not f["hops"] and not f["vector"].qdrant.search_limits
    finally:
        for _ in range(4):
            service._slots.release()
    for _ in range(5):
        with pytest.raises(KnowledgeGovernanceError):
            search(f, query="")
    assert search(f)["documents"]


def test_no_positive_permission_cache_between_search_calls(search_fixture):
    f = search_fixture
    assert search(f)["documents"]

    def forbidden(*args):
        raise f["provider_http"].status_error(403)

    f["provider_http"]._open_response = forbidden
    result = search(f)
    assert result["documents"] == [] and result["partial"] is False
    assert len(f["hops"]) == 2


def test_bridge_client_does_not_relabel_exhausted_budget_as_permission_failure(
    search_fixture, monkeypatch
):
    f = search_fixture
    tick = [100.0]
    monkeypatch.setattr(retrieval_budget, "time", SimpleNamespace(monotonic=lambda: tick[0]))
    with pytest.raises(KnowledgeGovernanceError, match="budget_exhausted"):
        with job_budget(f["runtime"].database, f["job"].id).activate():
            tick[0] += 61
            f["search"].readability.check(token=f["knowledge_token"], request=None)
    assert not f["hops"] and current_budget() is None


@pytest.mark.parametrize(
    "change,visible,denied",
    [
        ("none", True, False),
        ("ones_forbidden", True, False),
        ("kb", False, True),
        ("source", False, True),
        ("resource", False, True),
        ("index", False, True),
        ("team", True, False),
        ("user", None, True),
        ("role", None, True),
        ("member", None, True),
        ("expired", None, True),
        ("list_tool", None, True),
        ("search_tool", None, True),
        ("detail_tool", None, True),
        ("old_hash", None, True),
        ("direct", None, True),
    ],
)
def test_directory_search_share_current_kb_gate_but_directory_is_not_ones_permission(
    search_fixture, change, visible, denied
):
    f = search_fixture
    directory = KnowledgeDirectory(
        f["search"].access, f["search"].resources, f["runtime"].audit_service
    )
    commands = {
        "kb": "delete from rbac_role_application_knowledge_base",
        "source": 'update "knowledge.source" set source_system=\'other\'',
        "resource": "update \"knowledge.retrieval_resource\" set status='disabled'",
        "index": "update \"knowledge.vector_index\" set state='FAILED'",
        "team": 'update user_external_identity set metadata_json=\'{"team_uuids":["other"],"default_team_id":"other"}\' where provider=\'ones\'',
        "user": "update app_user set status='disabled' where id='user_local_admin'",
        "role": "update rbac_role set status='disabled' where code='ones-mcp-runtime-reader'",
        "member": "update rbac_user_role set status='disabled'",
        "expired": "update rbac_user_role set expires_at='2000-01-01T00:00:00+00:00'",
        "list_tool": "delete from rbac_role_application_mcp_tool where tool_identifier='knowledge_list_bases'",
        "search_tool": "delete from rbac_role_application_mcp_tool where tool_identifier='knowledge_search'",
        "detail_tool": "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'",
        "old_hash": "update agent_job_mcp_tool_snapshot set authorization_hash='" + "f" * 64 + "'",
        "direct": "update agent_job set business_application_id=null",
    }
    if change in commands:
        f["runtime"].database.execute(commands[change])
    if change == "ones_forbidden":

        def forbidden(*args):
            raise f["provider_http"].status_error(403)

        f["provider_http"]._open_response = forbidden
    if visible is None:
        with pytest.raises(AppError):
            directory.list_bases(token=f["knowledge_token"], arguments={})
    else:
        items = directory.list_bases(token=f["knowledge_token"], arguments={})["items"]
        assert bool(items) is visible
    assert not f["hops"] and not f["calls"]  # 目录绝不以探测工作项代替全库授权。
    if denied:
        with pytest.raises(KnowledgeGovernanceError):
            search(f)
        assert not f["hops"] and not f["vector"].qdrant.search_limits
    else:
        result = search(f)
        # 合成 Provider 不存在新 Team 的任务，必须过滤，不能以目录可见代替可读。
        assert bool(result["documents"]) is (change == "none")
