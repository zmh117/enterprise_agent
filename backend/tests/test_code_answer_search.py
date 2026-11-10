"""Version eligibility precedes vector recall and shared reranking."""

from copy import deepcopy

import pytest

from app.modules.knowledge.application.code_answer_search import search_code_answers
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_answer_reader import CodeAnswerReader
from backend.tests.test_code_answer_indexing import indexing as indexing_fixture, task
from backend.tests.test_code_answer_store import workspace as workspace_fixture, prepared, save

workspace, indexing = workspace_fixture, indexing_fixture


class Reranker:
    profile_hash = "a" * 64

    def __init__(self):
        self.documents = []
        self.available = True

    def check(self):
        if not self.available:
            raise RuntimeError("synthetic reranker unavailable")

    def rank(self, query, documents):
        self.documents = documents
        assert all(1 <= len(blocks) <= 2 for blocks in documents)
        assert all(len(block) <= 1800 for blocks in documents for block in blocks)
        return {"scores": [1.0] * len(documents), "truncated": [False] * len(documents)}


def publish(indexing, revision, *, key="first", private=False, environment_id="code-env-a"):
    workspace, store, executor, _, _ = indexing
    ctx, analysis, result = prepared(workspace, key, revision, environment_id=environment_id)
    result["answer"] = "A 字段必填" if revision == 100 else "A 字段可为空"
    if private:
        store.db.execute(
            f"UPDATE {store.t('code_evidence')} SET relative_path='private/Order.cpp' WHERE analysis_id=?",
            (analysis["id"],),
        )
        saved = workspace[1].save(
            ctx,
            analysis["id"],
            question="Synthetic code question",
            visibility_scope={"paths": ["private"]},
            result=result,
            request_key="save",
        )
    else:
        saved = save(workspace[1], ctx, analysis, result)
    work = task(store, saved["revision_id"])
    assert executor.execute(work["id"])
    assert store.row("code_index_task", work["id"])["state"] == "succeeded"
    return saved


def search(indexing, *, mode="exact", reranker=None, revision=100, environment_id="code-env-a"):
    _, store, _, embedding, qdrant = indexing
    index = store.db.execute_one(f"SELECT * FROM {store.t('vector_index')}")

    def recall(index, selected_revision, document_ids, generation_keys, vector, limit):
        qdrant.selected_versions = getattr(qdrant, "selected_versions", []) + [selected_revision]
        return [
            {**deepcopy(point), "score": 1.0}
            for point in qdrant.points.values()
            if point["payload"]["svn_revision"] == selected_revision
            and point["payload"]["document_id"] in document_ids
            and point["payload"]["index_generation_key"] in generation_keys
            and point["payload"]["searchable"]
        ][:limit]

    qdrant.code_answer_search = recall
    return search_code_answers(
        store=CodeAnswerReader(store.db),
        environment_id=environment_id,
        index=index,
        revision=revision,
        mode=mode,
        allowed_paths=["set_server"],
        query="为什么不能发布工单？",
        top_k=10,
        resource_revision_id="code-config",
        embedding=embedding,
        qdrant=qdrant,
        reranker=reranker or Reranker(),
        check=lambda: None,
    )


def test_exact_version_never_mixes_newer_rules(indexing):
    publish(indexing, 100)
    publish(indexing, 101, key="newer")
    result = search(indexing)
    assert result["match_kind"] == "exact" and result["requires_verification"] is False
    assert [d["svn_revision"] for d in result["documents"]] == [100]
    assert "必填" in result["documents"][0]["evidence"][0]["text"]
    assert indexing[4].selected_versions == [100]


def test_nearest_higher_is_authorized_ready_version_and_only_a_hint(indexing):
    publish(indexing, 101, key="private", private=True)
    publish(indexing, 102, key="visible")
    assert search(indexing)["documents"] == []
    result = search(indexing, mode="next_higher_hint")
    assert result["matched_revision"] == 102 and result["requested_revision"] == 100
    assert result["requires_verification"] and result["match_kind"] == "higher_revision_hint"
    assert indexing[4].selected_versions == [102]
    assert all(d["svn_revision"] == 102 for d in result["documents"])


def test_missing_version_and_dependency_failure_are_not_successful_misses(indexing):
    with pytest.raises(CodeKnowledgeError, match="SVN_REVISION_REQUIRED"):
        search(indexing, revision=None)
    reranker = Reranker()
    reranker.available = False
    with pytest.raises(RuntimeError, match="synthetic reranker unavailable"):
        search(indexing, reranker=reranker)
    assert indexing[3].encoded == 0
    assert not hasattr(indexing[4], "selected_versions")


def test_context_is_returned_whole_and_filtering_precedes_reranking(indexing):
    publish(indexing, 101, key="private", private=True)
    publish(indexing, 101, key="visible")
    reranker = Reranker()
    result = search(indexing, mode="next_higher_hint", reranker=reranker)
    assert len(reranker.documents) == 1
    assert result["documents"][0]["conditions"] == {"operation": "release"}
    assert result["documents"][0]["claims"][0]["evidence_ids"] == ["evidence-visible"]
    assert "private" not in str(result)


def test_same_source_version_and_question_have_separate_environment_answers(indexing):
    first = publish(indexing, 100, key="env-a", environment_id="code-env-a")
    second = publish(indexing, 100, key="env-b", environment_id="code-env-b")
    assert first["document_id"] != second["document_id"]
    assert [d["document_id"] for d in search(indexing)["documents"]] == [first["document_id"]]
    assert [
        d["document_id"] for d in search(indexing, environment_id="code-env-b")["documents"]
    ] == [second["document_id"]]
    reader = CodeAnswerReader(indexing[1].db)
    index = indexing[1].db.execute_one(f"SELECT * FROM {indexing[1].t('vector_index')}")
    with pytest.raises(CodeKnowledgeError, match="CODE_ANSWER_UNAVAILABLE"):
        reader.get(
            base_id="code-kb",
            environment_id="code-env-b",
            source_id=index["source_id"],
            index_id=index["id"],
            document_id=first["document_id"],
            revision_id=first["revision_id"],
            allowed_paths=["set_server"],
        )
    for point in indexing[4].points.values():
        if point["payload"]["document_id"] == first["document_id"]:
            assert (
                reader.chunk(
                    index=index,
                    point=point,
                    allowed_paths=["set_server"],
                    environment_id="code-env-b",
                )
                is None
            )
    workspace, store, executor, _, _ = indexing
    ctx, analysis, corrected = prepared(workspace, "correct-a")
    corrected.update(answer="A 环境更正后的规则", expected_current_revision_id=first["revision_id"])
    updated = save(workspace[1], ctx, analysis, corrected)
    assert updated["document_id"] == first["document_id"]
    assert executor.execute(task(store, updated["revision_id"])["id"])
    other = search(indexing, environment_id="code-env-b")["documents"]
    assert [(d["document_id"], d["revision_id"]) for d in other] == [
        (second["document_id"], second["revision_id"])
    ]


def test_higher_hint_never_uses_another_environments_nearer_version(indexing):
    publish(indexing, 101, key="only-b", environment_id="code-env-b")
    assert search(indexing, mode="next_higher_hint")["documents"] == []
    own = publish(indexing, 103, key="own-a", environment_id="code-env-a")
    result = search(indexing, mode="next_higher_hint")
    assert result["matched_revision"] == 103
    assert [d["document_id"] for d in result["documents"]] == [own["document_id"]]


def application_search(indexing):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.modules.knowledge.application.search import KnowledgeSearch
    from app.modules.knowledge.domain.models import KnowledgeJobAccess, PinnedKnowledgeResource
    from app.modules.knowledge.infrastructure.code_history_bridge import CodeHistoryBridge
    from app.modules.knowledge.infrastructure.code_search_receipts import CodeSearchReceipts
    from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
    from backend.tests.support.code_answers import analysis_context

    workspace, store, _, embedding, qdrant = indexing
    runtime, _, source, checkout = workspace
    ctx = analysis_context(runtime, source, checkout, key="application-query")
    access = KnowledgeJobAccess(
        ctx.job_id, ctx.actor_id, "app", "pub", "a" * 64, "b" * 64, ("code-kb",), "c" * 64
    )
    index = store.db.execute_one(f"SELECT * FROM {store.t('vector_index')}")
    pin = PinnedKnowledgeResource(
        "code-kb", "code-resource", "code-config", source, index["id"], index["code"], "d" * 64
    )
    budget = SimpleNamespace(activate=nullcontext, check=lambda: None, deadline_ms=9999999999999)
    principals = SimpleNamespace(authenticate=lambda *a: access, budget=lambda *a, **kw: budget)
    content = SimpleNamespace(
        records=SimpleNamespace(get=lambda *a: {"source_system": "svn"}),
        vectors=SimpleNamespace(get=lambda *a: index),
        answers=CodeAnswerReader(store.db),
        qdrant=qdrant,
    )
    resources = SimpleNamespace(
        resolve=lambda *a: pin,
        recheck=lambda *a: None,
        store=GovernanceStore(store.db),
        content_for=lambda *a: nullcontext(content),
    )
    bridge = CodeHistoryBridge(store.db, principals, principals, resources, runtime.audit_service)
    history = SimpleNamespace(
        code_history=lambda **kw: bridge.check(
            service_token="synthetic", knowledge_token=kw["token"], request=kw["request"]
        )
    )
    receipts = CodeSearchReceipts(store.db)
    search(indexing)  # Install the synthetic vector transport; the application path below is real.
    service = KnowledgeSearch(
        principals,
        resources,
        embedding,
        qdrant,
        runtime.audit_service,
        access_mode="offline",
        reranker=Reranker(),
        code_history=history,
        code_receipts=receipts,
    )
    return service, ctx, receipts


def test_application_search_receipt_and_full_answer_keep_environment(indexing):
    from app.modules.knowledge.application.code_query import CodeKnowledgeQuery
    from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
    from app.modules.mcp_audit import McpAuditContext, McpAuditCoordinator
    from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS
    from jsonschema import Draft202012Validator

    saved = publish(indexing, 100)
    publish(indexing, 100, key="other", environment_id="code-env-b")
    service, ctx, receipts = application_search(indexing)
    arguments = dict(
        knowledge_base_id="code-kb",
        query="Synthetic code question",
        svn_revision=100,
        environment="env-a",
    )
    audit = McpAuditCoordinator(indexing[1].db, max_payload_bytes=16384)
    handle = audit.begin(
        McpAuditContext(
            correlation_id=ctx.job_id,
            session_id=indexing[1].db.execute_one(
                "SELECT session_id FROM agent_job WHERE id=?", (ctx.job_id,)
            )["session_id"],
            job_id=ctx.job_id,
            invocation_id=ctx.invocation_id,
            actor_user_id=ctx.actor_id,
            server_code="knowledge-mcp",
            tool_identifier="knowledge_search",
        ),
        business_request={},
    )
    result = service.search(token="synthetic", arguments=arguments, search_id=handle.root_audit_id)
    receipt = result.pop("_code_receipt")
    Draft202012Validator(KNOWLEDGE_TOOL_CONTRACTS["knowledge_search"].output_schema).validate(
        result
    )
    assert result["environment"] == "env-a" and result["environment_id"] == "code-env-a"
    assert [item["document_id"] for item in result["documents"]] == [saved["document_id"]]
    audit.complete(
        handle, status="SUCCEEDED", business_response={"code_search": receipt}, duration_ms=1
    )
    query = CodeKnowledgeQuery(service.access, service.resources, receipts=receipts)
    args = dict(
        knowledge_base_id="code-kb",
        environment="env-a",
        search_id=handle.root_audit_id,
        document_id=saved["document_id"],
        revision_id=saved["revision_id"],
    )
    full = query.invoke(tool="knowledge_get_code_answer", token="synthetic", arguments=args)
    Draft202012Validator(
        KNOWLEDGE_TOOL_CONTRACTS["knowledge_get_code_answer"].output_schema
    ).validate(full)
    assert full["environment_id"] == "code-env-a"
    with pytest.raises(CodeKnowledgeError, match="CODE_SEARCH_CONTEXT_CHANGED"):
        query.invoke(
            tool="knowledge_get_code_answer",
            token="synthetic",
            arguments={**args, "environment": "env-b"},
        )
    for environment, error in (
        (None, "CODE_ENVIRONMENT_REQUIRED"),
        ("env-b", "CODE_ENVIRONMENT_MISMATCH"),
    ):
        with pytest.raises(KnowledgeGovernanceError, match=error):
            service.search(
                token="synthetic",
                arguments={**arguments, "environment": environment},
                search_id="other-search",
            )


def test_environment_revocation_during_reranking_cannot_return_evidence(indexing):
    from app.modules.knowledge.domain.governance import KnowledgeGovernanceError

    publish(indexing, 100)
    service, _, _ = application_search(indexing)
    rank = service.reranker.rank

    def revoke(query, documents):
        result = rank(query, documents)
        indexing[1].db.execute(
            "UPDATE platform_environment SET status='disabled' WHERE id='code-env-a'"
        )
        return result

    service.reranker.rank = revoke
    with pytest.raises(KnowledgeGovernanceError, match="CODE_ENVIRONMENT_UNAVAILABLE"):
        service.search(
            token="synthetic",
            arguments=dict(
                knowledge_base_id="code-kb",
                query="Synthetic code question",
                svn_revision=100,
                environment="env-a",
            ),
            search_id="revoked-search",
        )
