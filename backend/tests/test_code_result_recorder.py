"""Standard result finalization records cache hits without creating derived knowledge."""

from dataclasses import replace
import pytest

from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.job.infrastructure.session_repository import SessionRepository
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.code_result_recorder import (
    CodeResultRecorder,
    business_text,
)
from app.modules.mcp_audit import McpAuditContext, McpAuditCoordinator
from backend.tests.support.code_answers import analysis_context
from backend.tests.test_code_answer_store import workspace as workspace_fixture, prepared, save

workspace = workspace_fixture


def frozen_job(workspace, *, key="cache"):
    runtime, _, source, checkout = workspace
    ctx = analysis_context(runtime, source, checkout, key=key)
    request = RuntimePoolStore(runtime.database).request(ctx.invocation_id)
    request["prompt"]["retrieved_context"]["code_source"] = {
        "contract": "code-source-capability/v2",
        "sources": [
            {
                "knowledge_base_id": "code-kb",
                "source_id": source,
                "config_revision_id": "code-config",
            }
        ],
    }
    request["request_digest"] = canonical_request_digest(request)
    runtime.database.execute(
        "UPDATE agent_runtime_invocation SET request_digest=? WHERE invocation_id=?",
        (request["request_digest"], ctx.invocation_id),
    )
    runtime.database.execute(
        "UPDATE agent_runtime_request_snapshot SET request_json=?,request_digest=? WHERE invocation_id=?",
        (canonical_json(request), request["request_digest"], ctx.invocation_id),
    )
    return AgentRepository(runtime.database).get_job(ctx.job_id)


def observe(workspace, job, saved, *, kind="read", requested=100, status="SUCCEEDED"):
    runtime, _, source, _ = workspace
    audit = McpAuditCoordinator(runtime.database, max_payload_bytes=16384)
    handle = audit.begin(
        McpAuditContext(
            correlation_id=job.id,
            job_id=job.id,
            session_id=job.session_id,
            invocation_id=job.id + ".attempt-0",
            actor_user_id=job.requester_id,
            server_code="knowledge-mcp",
            tool_identifier="knowledge_get_code_answer" if kind == "read" else "knowledge_search",
        ),
        business_request={},
    )
    ref = dict(
        knowledge_base_id="code-kb",
        environment_id="code-env-a",
        source_id=source,
        document_id=saved["document_id"],
        revision_id=saved["revision_id"],
        requested_revision=requested,
        matched_revision=saved["svn_revision"],
        match_kind="exact" if saved["svn_revision"] == requested else "higher_revision_hint",
        requires_verification=saved["svn_revision"] != requested,
    )
    audit.complete(
        handle,
        status=status,
        business_response={"code_answer_read" if kind == "read" else "code_search": ref},
        duration_ms=1,
    )


def answer(saved):
    return (
        "环境 env-a，SVN r100：未填写工单名称时不能发布。\n\n"
        f"<!-- code-answer:{saved['document_id']}@{saved['revision_id']} -->"
    )


def fixture_answer(workspace, revision=100):
    ctx, analysis, result = prepared(workspace, revision=revision)
    return save(workspace[1], ctx, analysis, result)


def test_standard_result_records_each_cache_hit_once_without_indexing(workspace):
    saved = fixture_answer(workspace)
    job = frozen_job(workspace)
    observe(workspace, job, saved)
    runtime, store, _, _ = workspace
    recorder = CodeResultRecorder(runtime.database)
    service = AgentResultService(
        AgentRepository(runtime.database),
        SessionRepository(runtime.database),
        code_result_recorder=recorder.record,
    )
    with runtime.database.unit_of_work():
        service.save_result(job, answer(saved))
    recorder.record(job, answer(saved))
    rows = recorder.qa.for_job(job.id, job.requester_id)
    assert len(rows) == 1 and rows[0]["answer_origin"] == "cache"
    assert rows[0]["support_status"] == "supported"
    assert rows[0]["requested_revisions"] == [100]
    assert rows[0]["answer_text"] == "环境 env-a，SVN r100：未填写工单名称时不能发布。"
    assert rows[0]["references_json"][0]["document_id"] == saved["document_id"]
    assert rows[0]["references_json"][0]["revision_id"] == saved["revision_id"]
    assert (
        runtime.database.execute_one(
            "SELECT content FROM agent_artifact WHERE job_id=? AND artifact_type='report'",
            (job.id,),
        )["content"]
        == rows[0]["answer_text"]
    )
    assert store.db.execute_one(
        f"SELECT relative_path,line_start,line_end FROM {store.t('code_evidence')} LIMIT 1"
    ) == {"relative_path": "set_server/Order.cpp", "line_start": 10, "line_end": 20}
    assert len(runtime.database.execute(f"SELECT id FROM {store.t('code_index_task')}")) == 1
    assert (
        runtime.database.execute_one(
            f"SELECT count(*) AS n FROM {store.t('code_analysis')} WHERE job_id=?", (job.id,)
        )["n"]
        == 0
    )


@pytest.mark.parametrize(
    "kind,status,cited",
    [
        ("search", "SUCCEEDED", True),
        ("read", "FAILED", True),
        ("read", "SUCCEEDED", False),
    ],
)
def test_candidates_failures_and_uncited_answers_are_not_actual_references(
    workspace, kind, status, cited
):
    saved, job = fixture_answer(workspace), frozen_job(workspace)
    observe(workspace, job, saved, kind=kind, status=status)
    recorder = CodeResultRecorder(workspace[0].database)
    recorder.record(job, answer(saved) if cited else "SVN r100：还需核实。")
    row = recorder.qa.for_job(job.id, job.requester_id)[0]
    assert row["references_json"] == [] and row["support_status"] == "unverified"


def test_internal_reference_does_not_authorize_an_unread_answer(workspace):
    saved, job = fixture_answer(workspace), frozen_job(workspace)
    recorder = CodeResultRecorder(workspace[0].database)
    recorder.record(job, answer(saved))
    row = recorder.qa.for_job(job.id, job.requester_id)[0]
    assert row["references_json"] == [] and row["support_status"] == "unverified"
    assert "code-answer:" not in row["answer_text"]


def test_long_answer_keeps_references_when_private_history_is_truncated(workspace):
    saved, job = fixture_answer(workspace), frozen_job(workspace)
    observe(workspace, job, saved)
    recorder = CodeResultRecorder(workspace[0].database)
    recorder.record(job, "业务条件。" * 13000 + "\n" + answer(saved))
    row = recorder.qa.for_job(job.id, job.requester_id)[0]
    assert row["support_status"] == "supported"
    assert row["references_json"][0]["document_id"] == saved["document_id"]
    assert len(row["answer_text"]) <= 64000
    assert row["answer_text"].endswith("[内容已截断]")
    assert "code-answer:" not in row["answer_text"]


def test_higher_version_stays_a_hint_and_comparison_needs_both_versions(workspace):
    saved, job = fixture_answer(workspace, 101), frozen_job(workspace)
    observe(workspace, job, saved, requested=100)
    recorder = CodeResultRecorder(workspace[0].database)
    recorder.record(job, answer(saved))
    row = recorder.qa.for_job(job.id, job.requester_id)[0]
    assert row["support_status"] == "partial"
    assert row["references_json"][0]["svn_revision"] == 101
    assert row["references_json"][0]["version_mode"] == "next_higher_hint"
    other = frozen_job(workspace, key="compare")
    other = replace(other, input_message="环境：env-a 比较 SVN r100 与 r101")
    observe(workspace, other, saved, requested=101)
    recorder.record(other, answer(saved))
    assert recorder.qa.for_job(other.id, other.requester_id)[0]["support_status"] == "partial"


def test_no_version_no_record_and_write_failure_rolls_back_standard_result(workspace, monkeypatch):
    job = frozen_job(workspace)
    runtime = workspace[0]
    recorder = CodeResultRecorder(runtime.database)
    recorder.record(replace(job, input_message="为什么无法发布工单？"), "请提供 SVN 版本。")
    assert recorder.qa.for_job(job.id, job.requester_id) == []

    def fail(**kwargs):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(recorder.qa, "record", fail)
    service = AgentResultService(
        AgentRepository(runtime.database),
        SessionRepository(runtime.database),
        code_result_recorder=recorder.record,
    )
    with pytest.raises(RuntimeError, match="synthetic persistence"):
        with runtime.database.unit_of_work():
            service.save_result(job, "SVN r100：证据不足。")
    assert runtime.database.execute("SELECT id FROM agent_artifact WHERE job_id=?", (job.id,)) == []


def test_business_normalization_omits_source_blocks_quotes_and_credentials():
    text = (
        "  为什么发布失败？\n```cpp\nRAW_CODE\n```\n> ORIGINAL_INPUT\npassword=synthetic-only\n结论"
    )
    result = business_text(text, 2000)
    assert "RAW_CODE" not in result and "ORIGINAL_INPUT" not in result
    assert "synthetic-only" not in result and "[REDACTED]" in result
    assert len(business_text("长" * 65000, 64000)) <= 64000


def test_qa_refuses_another_environments_answer_and_history_keeps_environment(workspace):
    from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

    saved = fixture_answer(workspace)
    job = frozen_job(workspace)
    observe(workspace, job, saved)
    recorder = CodeResultRecorder(workspace[0].database)
    recorder.record(job, answer(saved))
    row = recorder.qa.for_job(job.id, job.requester_id)[0]
    assert row["environment_id"] == "code-env-a"
    with pytest.raises(CodeKnowledgeError, match="CODE_QA_REFERENCE_INVALID"):
        recorder.qa.record(
            job_id=job.id,
            result_revision=2,
            base_id="code-kb",
            actor_id=job.requester_id,
            source_id=row["source_id"],
            environment_id="code-env-b",
            requested_revisions=[100],
            question="Synthetic code question",
            answer="synthetic",
            support_status="supported",
            answer_origin="cache",
            references=row["references_json"],
        )
    other = frozen_job(workspace, key="other-environment")
    other = replace(other, input_message="环境：env-b SVN r100 Synthetic code question")
    observe(workspace, other, saved)  # A read receipt from A cannot support a B answer.
    recorder.record(other, answer(saved))
    isolated = recorder.qa.for_job(other.id, other.requester_id)[0]
    assert isolated["environment_id"] == "code-env-b"
    assert isolated["references_json"] == [] and isolated["support_status"] == "unverified"


@pytest.mark.parametrize("question", ["SVN r100", "环境：env-a，env-b环境 SVN r100"])
def test_no_environment_specific_qa_for_missing_or_ambiguous_environment(workspace, question):
    job = replace(frozen_job(workspace), input_message=question)
    recorder = CodeResultRecorder(workspace[0].database)
    recorder.record(job, "请指定一个环境")
    assert recorder.qa.for_job(job.id, job.requester_id) == []
