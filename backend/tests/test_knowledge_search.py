"""合成在线检索编排、HTTP 双身份桥和预算边界，不代表真实召回质量。"""

from app.modules.knowledge.infrastructure.reader_access import job_budget

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import json
from copy import deepcopy
from dataclasses import replace
from backend.tests.support.knowledge_reranker import SyntheticReranker

import httpx
import pytest

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.infrastructure.reader_access import KnowledgePrincipalAccess
from app.modules.knowledge.infrastructure.readability_client import KnowledgeReadabilityClient
from app.modules.knowledge.application.readability import BRIDGE_PATH
from app.modules.knowledge.application.search import KnowledgeSearch, SearchRequest
from app.modules.knowledge.domain.models import KnowledgeAccessMode
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
        f["runtime"].audit_service,
        reranker=SyntheticReranker(),
        access_mode=KnowledgeAccessMode.OFFLINE,
        readability=client,
    )
    return {**f, "search": search, "readability_client": client, "hops": hops}


def search(f, **extra):
    return f["search"].search(
        token=f["knowledge_token"],
        arguments={
            "knowledge_base_id": f["body"]["knowledge_base_id"],
            "query": "合成查询-不要记录",
            **extra,
        },
    )


@pytest.mark.parametrize("mode", [KnowledgeAccessMode.ONLINE, KnowledgeAccessMode.OFFLINE])
def test_resource_code_search_uses_resource_identity_not_content_code(search_fixture, mode):
    f = search_fixture
    f["search"].access_mode = mode
    directory = KnowledgeDirectory(f["search"].access, f["search"].resources, f["search"].audit)
    page = directory.list_bases(token=f["knowledge_token"], arguments={})
    assert page["items"][0]["code"] == "synthetic"
    result = f["search"].search(
        token=f["knowledge_token"], arguments={"resource_code": "synthetic", "query": "合成查询"}
    )
    assert result["knowledge_base_id"] == f["body"]["knowledge_base_id"]
    assert result["documents"]
    assert bool(f["hops"]) is (mode is KnowledgeAccessMode.ONLINE)


@pytest.mark.parametrize(
    "kind", ["unknown", "content_code", "unauthorized", "disabled", "unpublished", "replaced"]
)
def test_resource_code_rejects_unavailable_target_before_retrieval(
    search_fixture, monkeypatch, kind
):
    f = search_fixture
    service, db = f["search"], f["runtime"].database
    code = "synthetic"
    expected = "knowledge_resource_code_unavailable"
    if kind == "unknown":
        code = "not-a-resource"
    elif kind == "content_code":
        code = "synthetic_base"
    elif kind == "unauthorized":
        original = service.access.authenticate
        monkeypatch.setattr(
            service.access,
            "authenticate",
            lambda *a, **k: replace(original(*a, **k), knowledge_base_ids=()),
        )
    elif kind in {"disabled", "unpublished"}:
        field, value = (
            ("status", "disabled") if kind == "disabled" else ("published_revision_id", None)
        )
        db.execute(
            f'UPDATE "knowledge.retrieval_resource" SET {field}=? WHERE code=?', (value, code)
        )
        expected = "knowledge_resource_unavailable"
    else:
        original_resolve = service.resources.resolve
        monkeypatch.setattr(
            service.resources,
            "resolve",
            lambda base: replace(original_resolve(base), resource_id="replacement-resource"),
        )
        expected = "knowledge_resource_changed"
    with pytest.raises(KnowledgeGovernanceError) as exc:
        service.search(
            token=f["knowledge_token"], arguments={"resource_code": code, "query": "合成查询"}
        )
    assert exc.value.error_code == expected
    assert not f["vector"].qdrant.search_limits and not f["hops"]


@pytest.mark.parametrize(
    "selector",
    [
        {},
        {"resource_code": "synthetic", "knowledge_base_id": "kb"},
        {"resource_code": ""},
        {"resource_code": None},
        {"resource_code": "a b"},
        {"resource_code": "a" * 129},
        {"resource_code": "synthetic", "resource_id": "injected"},
    ],
)
def test_resource_selector_rejects_ambiguous_or_invalid_input(selector):
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_input_invalid"):
        SearchRequest.parse({**selector, "query": "合成查询"})


def test_offline_search_returns_snapshot_content_without_provider_or_audit_text(search_fixture):
    f = search_fixture
    result = search(f)
    assert len(result["documents"]) == 1 and result["partial"] is False
    hit = result["documents"][0]
    assert hit["work_item_uuid"].startswith("MOCK-ONES-TASK-")
    assert 1 <= len(hit["evidence"]) <= 3
    assert f["vector"].qdrant.search_limits == [200]
    assert not f["calls"] and not f["hops"]
    assert result["content_mode"] == "ingested_snapshot"
    assert result["content_scope"] == "matched_chunks"
    assert hit["title"] and hit["ingested_at"] and hit["source_name"]
    assert isinstance(hit["number"], str)
    assert any(evidence["text"] for evidence in hit["evidence"])
    safe = json.dumps(
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


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize(
    "stage,outcome,expected",
    [
        ("profile", 503, "knowledge_embedding_unavailable"),
        ("profile", "timeout", "knowledge_embedding_read_timeout"),
        ("embed", 429, "knowledge_embedding_busy"),
        ("embed", 408, "knowledge_embedding_read_timeout"),
        ("embed", 503, "knowledge_embedding_unavailable"),
        ("embed", "timeout", "knowledge_embedding_read_timeout"),
    ],
)
def test_embedding_failure_keeps_classification_through_content_connection(
    search_fixture, monkeypatch, configured, stage, outcome, expected
):
    from app.modules.knowledge.infrastructure.content_access import ManagedContentAccess
    from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient
    from app.modules.knowledge.infrastructure.embedding_profile import profile
    from app.modules.knowledge.domain.vector_contract import fingerprint

    f, calls = search_fixture, []

    def respond(request):
        calls.append(request.url.path)
        assert request.url.host == "knowledge-embedding-online"
        if request.url.path == "/profile" and stage == "embed":
            return httpx.Response(
                200, json={"profile": profile(), "profile_hash": fingerprint(profile())}
            )
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic-private")
        code = "knowledge_embedding_busy" if outcome == 429 else "knowledge_embedding_read_timeout"
        return httpx.Response(outcome, json={"error_code": code, "detail": "synthetic-private"})

    embedding = EmbeddingClient(online=True, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(f["search"], "embedding", embedding)
    qdrant = f["vector"].qdrant
    monkeypatch.setattr(qdrant, "http", SimpleNamespace(close=lambda: None), raising=False)
    adapter = ManagedContentAccess(
        f["runtime"].database, lambda *args: {}, qdrant_factory=lambda **kwargs: qdrant
    )
    config = {
        "postgres": {"mode": "platform"},
        "qdrant": {"url": "http://knowledge-qdrant:6333", "api_key_ref": ""},
    }
    monkeypatch.setattr(
        f["search"].resources,
        "content_for",
        lambda pin: adapter.open(
            config if configured else None,
            knowledge_base_id=pin.knowledge_base_id,
            revision_id=pin.revision_id,
        ),
    )
    try:
        with pytest.raises(KnowledgeGovernanceError) as captured:
            search(f)
        assert captured.value.error_code == expected
        assert calls == (["/profile"] if stage == "profile" else ["/profile", "/embed"])
        assert not qdrant.search_limits and not f["hops"]
        audits = f["runtime"].database.execute(
            "select * from audit_event where event_type='knowledge.search.denied'"
        )
        safe = json.dumps(audits, ensure_ascii=False, default=str) + captured.value.safe_message
        assert len(audits) == 1 and expected in safe
        assert "synthetic-private" not in safe and "合成查询-不要记录" not in safe
        assert current_budget() is None
    finally:
        embedding.http.close()


@pytest.mark.parametrize("outcome", ["success", "route_failure", "publication_changed"])
def test_hybrid_route_keeps_readability_scope_and_fails_without_dense_fallback(
    search_fixture, monkeypatch, outcome
):
    from app.modules.knowledge.application import candidates as candidates_module

    f = search_fixture
    calls = []
    qdrant = f["vector"].qdrant
    original = qdrant.search
    monkeypatch.setattr(candidates_module, "hybrid_index", lambda index: True)

    def hybrid(index, vector, query, limit, *, mode):
        assert mode == "hybrid"
        calls.append(limit)
        assert index["knowledge_base_id"] == f["body"]["knowledge_base_id"]
        if outcome == "route_failure":
            raise VectorError("knowledge_vector_response_invalid")
        if outcome == "publication_changed":

            def changed(pin):
                raise KnowledgeGovernanceError("knowledge_resource_changed")

            monkeypatch.setattr(f["search"].resources, "recheck", changed)
        return original(index, vector, limit)

    monkeypatch.setattr(qdrant, "hybrid_search", hybrid, raising=False)
    monkeypatch.setattr(qdrant, "search", lambda *args: pytest.fail("must not silently fall back"))
    if outcome == "success":
        result = search(f)
        assert len(result["documents"]) == 1
        assert not f["calls"] and not f["hops"]
    else:
        with pytest.raises(AppError):
            search(f)
        assert not f["calls"]
    assert calls == [200]


@pytest.mark.parametrize("points,partial", [(99, False), (100, True)])
def test_hybrid_overlapping_routes_report_possible_truncation(
    search_fixture, monkeypatch, points, partial
):
    from app.modules.knowledge.application import candidates as candidates_module

    f = search_fixture
    monkeypatch.setattr(candidates_module, "hybrid_index", lambda index: True)
    from app.modules.knowledge.application import search as search_module

    monkeypatch.setattr(
        search_module, "candidate_pool", lambda *args: candidates_module.CandidatePool([], {}, [])
    )
    monkeypatch.setattr(
        f["vector"].qdrant, "hybrid_search", lambda *args, **kwargs: [{}] * points, raising=False
    )
    result = search(f)
    assert result["documents"] == [] and result["partial"] is partial


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
def test_source_provider_failure_does_not_block_offline_search(search_fixture, status):
    f = search_fixture

    def fail(*args):
        pytest.fail("offline retrieval must never call the source provider")

    f["provider_http"]._open_response = fail
    assert search(f)["documents"]
    assert not f["calls"] and not f["hops"]


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


@pytest.mark.parametrize(
    "change", ["kb", "member", "user", "resource", "candidate", "job", "snapshot", "removed"]
)
def test_final_recheck_after_all_upstream_success(search_fixture, change, monkeypatch):
    f = search_fixture
    original = f["search"].resources.store.document_snapshots

    def check(*args, **kwargs):
        result = original(*args, **kwargs)
        f["runtime"].database.execute(
            {
                "kb": "delete from rbac_role_application_knowledge_base",
                "member": "update rbac_user_role set status='disabled'",
                "user": "update app_user set status='disabled' where id='user_local_admin'",
                "snapshot": "update \"knowledge.document_revision\" set title='changed'",
                "removed": "update \"knowledge.knowledge_base_document\" set state='excluded'",
                "resource": "update \"knowledge.retrieval_resource\" set status='disabled'",
                "candidate": 'update "knowledge.document_chunk" set evidence_hash=\''
                + "0" * 64
                + "'",
                "job": "update agent_job set status='SUCCEEDED'",
            }[change]
        )
        return result

    monkeypatch.setattr(f["search"].resources.store, "document_snapshots", check)
    with pytest.raises(AppError):
        search(f)


@pytest.mark.parametrize("readable_fixture", [{"documents": 70}], indirect=True)
def test_offline_search_reranks_at_most_50_and_returns_requested_topk(search_fixture, monkeypatch):
    f = search_fixture
    original = f["search"].reranker.rank
    sizes = []

    def rank(query, documents):
        sizes.append(len(documents))
        return original(query, documents)

    monkeypatch.setattr(f["search"].reranker, "rank", rank)
    result = search(f, top_k=20)
    assert sizes == [50]
    assert len(result["documents"]) == 20
    assert [doc["rank"] for doc in result["documents"]] == list(range(1, 21))
    assert f["vector"].qdrant.search_limits == [200]
    assert not f["calls"] and not f["hops"]


def test_job_remaining_budget_and_retry_change(search_fixture):
    f = search_fixture
    budget = job_budget(f["runtime"].database, f["job"].id)
    assert 0 < budget.remaining() <= 360
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


@pytest.mark.parametrize(
    "elapsed,late,partial",
    [
        (125, False, False),
        (185, False, False),
        (245, False, False),
        (359.5, False, False),
        (361, True, None),
    ],
)
def test_extended_budget_soft_cutoff_and_late_result_discard(
    search_fixture, monkeypatch, elapsed, late, partial
):
    f = search_fixture
    # 单独验证检索硬上限；合成 Job 的默认 300 秒不能先截断这组边界。
    db = f["runtime"].database
    policy = json.loads(
        db.execute_one("select execution_policy_json from agent_job where id=?", (f["job"].id,))[
            "execution_policy_json"
        ]
    )
    for key in ("requested", "effective"):
        policy[key]["timeout_seconds"] = 600
    db.execute(
        "update agent_job set execution_policy_json=? where id=?", (json.dumps(policy), f["job"].id)
    )
    tick = [100.0]
    monkeypatch.setattr(retrieval_budget, "time", SimpleNamespace(monotonic=lambda: tick[0]))
    original = f["vector"].qdrant.search

    def query(*args):
        result = original(*args)
        tick[0] += elapsed
        return result

    monkeypatch.setattr(f["vector"].qdrant, "search", query)
    if late:
        with pytest.raises(KnowledgeGovernanceError, match="budget_exhausted"):
            search(f)
    else:
        result = search(f)
        assert bool(result["documents"]) is not partial
        assert result["partial"] is partial
    if late or partial:
        assert not f["hops"]
    assert current_budget() is None


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
        assert len(calls) == 1 and 240 < calls[0] <= 360 and sleeps == []
        calls.clear()
        with pytest.raises(VectorError):
            http.request("GET", "/collections")
        assert calls == [180, 180, 180] and sleeps == [1, 2]
    finally:
        http.close()


@pytest.mark.parametrize(
    "stage", ["embedding_profile", "qdrant_profile", "embedding_query", "rerank"]
)
@pytest.mark.parametrize("mutation", ["kb", "resource", "user"])
def test_revocation_stops_next_upstream_stage(search_fixture, monkeypatch, stage, mutation):
    f = search_fixture
    target, method = {
        "embedding_profile": (f["search"].embedding, "check"),
        "qdrant_profile": (f["search"].qdrant, "check"),
        "embedding_query": (f["search"].embedding, "call"),
        "rerank": (f["search"].reranker, "rank"),
    }[stage]
    original = getattr(target, method)

    def revoke(*args, **kwargs):
        value = original(*args, **kwargs)
        f["runtime"].database.execute(
            {
                "kb": "delete from rbac_role_application_knowledge_base",
                "resource": "update \"knowledge.retrieval_resource\" set status='disabled'",
                "user": "update app_user set status='disabled' where id='user_local_admin'",
                "snapshot": "update \"knowledge.document_revision\" set title='changed'",
                "removed": "update \"knowledge.knowledge_base_document\" set state='excluded'",
            }[mutation]
        )
        return value

    monkeypatch.setattr(target, method, revoke)
    with pytest.raises(KnowledgeGovernanceError):
        search(f)
    assert f["vector"].qdrant.search_limits == ([200] if stage == "rerank" else [])
    assert not f["hops"]
    assert current_budget() is None


@pytest.mark.parametrize("stage", ["embedding", "qdrant", "snapshot"])
def test_unexpected_dependency_exception_and_failure_audit_are_sanitized(
    search_fixture, monkeypatch, stage
):
    f = search_fixture
    leaked = "synthetic-private-body-" + f["knowledge_token"]
    target, method = {
        "embedding": (f["search"].embedding, "check"),
        "qdrant": (f["search"].qdrant, "search"),
        "snapshot": (f["search"].resources.store, "document_snapshots"),
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


def test_no_positive_knowledge_permission_cache_between_search_calls(search_fixture):
    f = search_fixture
    assert search(f)["documents"]
    f["runtime"].database.execute("delete from rbac_role_application_knowledge_base")
    with pytest.raises(KnowledgeGovernanceError):
        search(f)
    assert not f["hops"]


def test_bridge_client_does_not_relabel_exhausted_budget_as_permission_failure(
    search_fixture, monkeypatch
):
    f = search_fixture
    tick = [100.0]
    monkeypatch.setattr(retrieval_budget, "time", SimpleNamespace(monotonic=lambda: tick[0]))
    with pytest.raises(KnowledgeGovernanceError, match="budget_exhausted"):
        with job_budget(f["runtime"].database, f["job"].id).activate():
            tick[0] += 361
            f["readability_client"].check(token=f["knowledge_token"], request=None)
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
        ("detail_tool", True, False),
        ("no_identity", True, False),
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
        "source": "update \"knowledge.source\" set source_system='other'",
        "resource": "update \"knowledge.retrieval_resource\" set status='disabled'",
        "index": "update \"knowledge.vector_index\" set state='FAILED'",
        "no_identity": "update user_external_identity set status='disabled' where provider='ones'",
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
        assert result["documents"]
        assert not f["hops"] and not f["calls"]


@pytest.mark.parametrize("change", ["embedding", "revision"])
def test_reranked_inputs_changed_during_inference_fail_even_outside_returned_topk(
    search_fixture, monkeypatch, change
):
    f = search_fixture
    original = f["search"].reranker.rank

    def mutate(query, documents):
        result = original(query, documents)
        sql = (
            'update "knowledge.document_chunk" set embedding_hash=' + "'" + "0" * 64 + "'"
            if change == "embedding"
            else 'update "knowledge.document" set current_revision_id=NULL'
        )
        f["runtime"].database.execute(sql)
        return result

    monkeypatch.setattr(f["search"].reranker, "rank", mutate)
    with pytest.raises(AppError):
        search(f, top_k=1)


@pytest.mark.parametrize("code", ["busy", "read_timeout", "input_limit", "profile_mismatch"])
def test_online_rerank_failures_never_run_ones_or_return_original_ranking(
    search_fixture, monkeypatch, code
):
    f = search_fixture

    def fail(*args):
        raise VectorError("knowledge_rerank_" + code)

    monkeypatch.setattr(f["search"].reranker, "rank", fail)
    with pytest.raises(KnowledgeGovernanceError) as caught:
        search(f)
    expected = code if code != "profile_mismatch" else "unavailable"
    assert caught.value.error_code == "knowledge_rerank_" + expected
    assert not f["hops"]
