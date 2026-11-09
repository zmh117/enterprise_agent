"""Version identity, evidence gating and atomic derived work, without a model."""

from copy import deepcopy

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_answer_store import CodeAnswerStore
from app.modules.knowledge.infrastructure.storage import insert
from backend.tests.support.code_answers import (
    CODE_INDEX_ID,
    analysis_context,
    code_configuration,
    confirm,
)
from backend.tests.support.runtime import container


@pytest.fixture
def workspace(tmp_path):
    runtime = container()
    try:
        _, source, checkout, _ = code_configuration(runtime, tmp_path)
        yield (
            runtime,
            CodeAnswerStore(runtime.database, authorize=lambda context: None),
            source,
            checkout,
        )
    finally:
        runtime.database.close()


def prepared(workspace, key="one", revision=100):
    runtime, store, source, checkout = workspace
    ctx = analysis_context(runtime, source, checkout, key=key, revision=revision)
    analysis = confirm(store, ctx, store.begin(ctx, key))
    evidence_id = "evidence-" + key
    insert(
        store.db,
        "code_evidence",
        dict(
            id=evidence_id,
            analysis_id=analysis["id"],
            kind="file_read",
            relative_path="set_server/Order.cpp",
            line_start=10,
            line_end=20,
            svn_revision=revision,
            repository_content_hash="c" * 64,
            read_content_hash="d" * 64,
            representation_json={"encoding": "utf-8", "eol": "lf"},
            tool_call_id="read-" + key,
            evidence_hash=digest([revision, "set_server/Order.cpp", 10, 20]),
            observed_at=now(),
            validated_at=now(),
        ),
    )
    result = dict(
        title="工单发布",
        answer="A 字段为空时不能发布。",
        conditions={"operation": "release"},
        claims=[
            dict(
                claim_id="release",
                conclusion="A 字段必填",
                conditions={},
                evidence_ids=[evidence_id],
            )
        ],
        coverage={"paths": ["set_server/Order.cpp"]},
        unknowns=[],
        support_status="supported",
    )
    store.finalizing(ctx, analysis["id"])
    return ctx, analysis, result


def save(store, ctx, analysis, result):
    return store.save(
        ctx,
        analysis["id"],
        question="Synthetic code question",
        visibility_scope={"paths": ["set_server"]},
        result=result,
        request_key="save",
    )


def test_versions_are_distinct_and_replay_does_not_reindex(workspace):
    _, store, _, _ = workspace
    ctx, analysis, result = prepared(workspace)
    first = save(store, ctx, analysis, result)
    assert save(store, ctx, analysis, result) == first
    assert first["index_state"] == "pending"
    row = store.row("code_analysis", analysis["id"])
    assert row["read_released_at"] and row["closed_at"]
    ctx, analysis, result = prepared(workspace, "next", 101)
    result["answer"] = "A 字段为空时可以发布。"
    result["claims"][0]["conclusion"] = "A 字段不再必填"
    second = save(store, ctx, analysis, result)
    assert first["revision_id"] != second["revision_id"]
    assert {
        r["svn_revision"] for r in store.db.execute(f"SELECT * FROM {store.t('code_answer')}")
    } == {100, 101}
    assert len(store.db.execute(f"SELECT * FROM {store.t('code_index_task')}")) == 2
    assert store.db.execute("PRAGMA foreign_key_check") == []


def test_same_version_unchanged_reuses_and_correction_requires_cas(workspace):
    _, store, _, _ = workspace
    ctx, analysis, result = prepared(workspace)
    first = save(store, ctx, analysis, result)
    ctx, analysis, result = prepared(workspace, "same")
    same = save(store, ctx, analysis, result)
    assert first["revision_id"] == same["revision_id"]
    assert len(store.db.execute(f"SELECT * FROM {store.t('document_revision')}")) == 1
    ctx, analysis, result = prepared(workspace, "correct")
    result["answer"] = "A 字段为空且校验开关启用时不能发布。"
    with pytest.raises(CodeKnowledgeError, match="CODE_ANSWER_REVISION_CONFLICT"):
        save(store, ctx, analysis, result)
    assert store.row("code_analysis", analysis["id"])["state"] == "validating"
    result["expected_current_revision_id"] = first["revision_id"]
    corrected = save(store, ctx, analysis, result)
    assert corrected["revision_id"] != first["revision_id"]
    tasks = store.db.execute(f"SELECT action,revision_id FROM {store.t('code_index_task')}")
    assert len(tasks) == 3
    assert {tuple(r.values()) for r in tasks} >= {("remove", first["revision_id"])}
    document = store.db.execute_one(f"SELECT current_revision_id FROM {store.t('document')}")
    assert document["current_revision_id"] == corrected["revision_id"]


def test_partial_does_not_create_shared_document(workspace):
    _, store, _, _ = workspace
    ctx, analysis, result = prepared(workspace)
    result.update(
        support_status="partial", unknowns=[{"critical": True, "reason": "external dependency"}]
    )
    saved = save(store, ctx, analysis, result)
    assert saved["revision_id"] is None and saved["index_state"] == "not_applicable"
    assert store.db.execute(f"SELECT * FROM {store.t('document')}") == []
    assert store.db.execute(f"SELECT * FROM {store.t('code_index_task')}") == []
    changed = deepcopy(result)
    changed["answer"] = "Different replay"
    with pytest.raises(CodeKnowledgeError, match="CODE_IDEMPOTENCY_CONFLICT"):
        save(store, ctx, analysis, changed)


@pytest.mark.parametrize(
    "mutation", ["unread", "wrong_revision", "outside_scope", "unvalidated", "critical_unknown"]
)
def test_supported_answers_reject_missing_or_wrong_evidence(workspace, mutation):
    _, store, _, _ = workspace
    ctx, analysis, result = prepared(workspace)
    if mutation == "unread":
        result["claims"][0]["evidence_ids"] = ["not-observed"]
    elif mutation == "critical_unknown":
        result["unknowns"] = [{"reason": "unknown"}]
    else:
        field, value = {
            "wrong_revision": ("svn_revision", 101),
            "outside_scope": ("relative_path", "private/Other.cpp"),
            "unvalidated": ("validated_at", None),
        }[mutation]
        store.db.execute(f"UPDATE {store.t('code_evidence')} SET {field}=?", (value,))
    with pytest.raises(CodeKnowledgeError):
        save(store, ctx, analysis, result)
    assert store.db.execute(f"SELECT * FROM {store.t('document')}") == []
    assert store.row("code_analysis", analysis["id"])["read_released_at"] is None


def test_each_cache_hit_gets_private_record_without_another_index_task(workspace):
    from app.modules.knowledge.infrastructure.code_qa_store import CodeQaStore

    _, store, source, _ = workspace
    ctx, analysis, result = prepared(workspace)
    saved = save(store, ctx, analysis, result)
    revision = store.db.execute_one(
        f"SELECT document_id FROM {store.t('document_revision')} WHERE id=?",
        (saved["revision_id"],),
    )
    qa = CodeQaStore(store.db)
    args = dict(
        job_id=ctx.job_id,
        result_revision=1,
        base_id=ctx.knowledge_base_id,
        actor_id=ctx.actor_id,
        source_id=source,
        requested_revisions=[100],
        question="Synthetic code question",
        answer=result["answer"],
        support_status="supported",
        answer_origin="cache",
        references=[
            dict(
                document_id=revision["document_id"],
                revision_id=saved["revision_id"],
                svn_revision=100,
                version_mode="exact",
            )
        ],
    )
    first = qa.record(**args)
    assert qa.record(**args) == first
    assert qa.record(**{**args, "result_revision": 2}) != first
    assert len(qa.for_job(ctx.job_id, ctx.actor_id)) == 2
    assert qa.for_job(ctx.job_id, "another-actor") == []
    assert len(store.db.execute(f"SELECT * FROM {store.t('code_index_task')}")) == 1
    with pytest.raises(CodeKnowledgeError, match="CODE_QA_REPLAY_CONFLICT"):
        qa.record(**{**args, "answer": "changed final response"})
    with pytest.raises(CodeKnowledgeError, match="CODE_QA_VERSION_MISMATCH"):
        qa.record(**{**args, "requested_revisions": [101]})
    with pytest.raises(CodeKnowledgeError, match="CODE_QA_TARGET_EVIDENCE_REQUIRED"):
        qa.record(**{**args, "references": []})


def indexed(store, revision_id):
    store.db.execute(
        f"UPDATE {store.t('code_index_task')} SET state='succeeded',expected_chunks=1,completed_chunks=1,ready_at=?,step='done' WHERE revision_id=? AND action='upsert'",
        (now(), revision_id),
    )


def test_version_selection_filters_permissions_membership_and_readiness_before_hint(workspace):
    from app.modules.knowledge.infrastructure.code_answer_reader import CodeAnswerReader

    _, store, source, _ = workspace
    saved = {}
    for version in (100, 101, 102, 103):
        ctx, analysis, result = prepared(workspace, key=str(version), revision=version)
        if version == 102:
            store.db.execute(
                f"UPDATE {store.t('code_evidence')} SET relative_path='private/Rule.cpp' WHERE analysis_id=?",
                (analysis["id"],),
            )
            saved[version] = store.save(
                ctx,
                analysis["id"],
                question="Synthetic code question",
                visibility_scope={"paths": ["private"]},
                result=result,
                request_key="save",
            )
        else:
            saved[version] = save(store, ctx, analysis, result)
        if version != 100:
            indexed(store, saved[version]["revision_id"])
    reader = CodeAnswerReader(store.db)
    args = dict(
        base_id="code-kb",
        source_id=source,
        index_id=CODE_INDEX_ID,
        revision=100,
        allowed_paths=["set_server"],
    )
    assert reader.select_version(**args, mode="exact")["matched_revision"] is None
    hint = reader.select_version(**args, mode="next_higher_hint")
    assert hint["requested_revision"] == 100 and hint["matched_revision"] == 101
    assert hint["requires_code_verification"]
    store.db.execute(
        f"UPDATE {store.t('knowledge_base_document')} SET state='removed' WHERE document_id IN (SELECT document_id FROM {store.t('code_answer')} WHERE svn_revision=101)"
    )
    assert reader.select_version(**args, mode="next_higher_hint")["matched_revision"] == 103
    indexed(store, saved[100]["revision_id"])
    exact = reader.select_version(**args, mode="exact")
    assert exact["matched_revision"] == 100
    answer = reader.get(
        base_id="code-kb",
        source_id=source,
        index_id=CODE_INDEX_ID,
        document_id=exact["document_ids"][0],
        revision_id=saved[100]["revision_id"],
        allowed_paths=["set_server"],
    )
    assert answer["content_scope"] == "full_answer" and answer["svn_revision"] == 100


def test_correction_pending_index_does_not_fall_back_to_obsolete_answer(workspace):
    from app.modules.knowledge.infrastructure.code_answer_reader import CodeAnswerReader

    _, store, source, _ = workspace
    ctx, analysis, result = prepared(workspace)
    first = save(store, ctx, analysis, result)
    indexed(store, first["revision_id"])
    ctx, analysis, result = prepared(workspace, "correct")
    result.update(answer="Corrected answer", expected_current_revision_id=first["revision_id"])
    save(store, ctx, analysis, result)
    reader = CodeAnswerReader(store.db)
    assert (
        reader.select_version(
            base_id="code-kb",
            source_id=source,
            index_id=CODE_INDEX_ID,
            revision=100,
            mode="exact",
            allowed_paths=["set_server"],
        )["matched_revision"]
        is None
    )
