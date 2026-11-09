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


def publish(indexing, revision, *, key="first", private=False):
    workspace, store, executor, _, _ = indexing
    ctx, analysis, result = prepared(workspace, key, revision)
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


def search(indexing, *, mode="exact", reranker=None, revision=100):
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
