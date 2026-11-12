"""Control-plane admission/response boundaries using synthetic DB jobs, no SVN/model calls."""

from dataclasses import replace
from contextlib import nullcontext
from types import SimpleNamespace
from datetime import timedelta
import json

import pytest
from jsonschema import Draft202012Validator

from app.modules.knowledge.domain.code_answers import code_authorization_hash, utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_user_revision import user_svn_revisions
from app.modules.knowledge.domain.models import KnowledgeJobAccess, PinnedKnowledgeResource
from app.modules.knowledge.infrastructure.code_history_bridge import CodeHistoryBridge
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.shared.code_answer_tool_contracts import CODE_TOOL_SCHEMAS
from backend.tests.support.code_answers import (
    analysis_context,
    code_configuration,
    confirm,
    CODE_INDEX_ID,
)
from backend.tests.support.runtime import container


@pytest.fixture
def bridge(tmp_path):
    runtime = container()
    try:
        _, source, checkout, _ = code_configuration(runtime, tmp_path)
        ctx = analysis_context(runtime, source, checkout)
        access = KnowledgeJobAccess(
            ctx.job_id, ctx.actor_id, "app", "pub", "a" * 64, "b" * 64, ("code-kb",), "c" * 64
        )
        ctx = replace(ctx, authorization_hash=code_authorization_hash(access))
        pin = PinnedKnowledgeResource(
            "code-kb", "code-resource", "code-config", source, CODE_INDEX_ID, "code-index", "d" * 64
        )
        handler = CodeHistoryBridge(runtime.database, None, None, None, None)
        handler.operations.authorize_context = handler.answers.authorize_context = lambda context: (
            None
        )
        receipt = dict(
            search_id=ctx.exact_search_id,
            requested_revision=100,
            version_mode="exact",
            question_hash=ctx.question_hash,
            invocation_id=ctx.invocation_id,
            deadline_ms=int(utc_time(ctx.deadline_at).timestamp() * 1000),
        )
        handler.receipts = SimpleNamespace(read=lambda identifier, **kw: receipt)
        config = dict(source_id=source, checkout_id=checkout["id"], allowed_paths_json=[""])
        args = dict(
            knowledge_base_id="code-kb",
            source_id=source,
            checkout_id=checkout["id"],
            revision=100,
            search_id=ctx.exact_search_id,
            request_key="start",
            reason="缺少证据",
        )
        yield handler, ctx, access, pin, config, args
    finally:
        runtime.database.close()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("SVN=100，发布失败", (100,)),
        ("svn版本号：101", (101,)),
        ("比较 r100 与 r101", (100, 101)),
        ("工单 987654，SVN r100", (100,)),
    ],
)
def test_only_explicit_svn_versions(text, expected):
    assert user_svn_revisions(text) == expected


@pytest.mark.parametrize(
    "text", ["工单 100 发布失败", "SVN HEAD", "r1.5", "r1 r2 r3", "r9223372036854775808"]
)
def test_ambiguous_or_invalid_user_version_rejected(text):
    with pytest.raises(CodeKnowledgeError, match="SVN_REVISION_REQUIRED"):
        user_svn_revisions(text)


def begin_reading(f):
    handler, ctx, access, pin, config, args = f
    first = handler._begin(access, pin, config, args, "code-env-a")
    analysis = handler.operations.row("code_analysis", first["analysis_id"])
    ctx = handler._context(access, pin, config, analysis, "code-env-a")
    confirm(handler.operations, ctx, analysis)
    return handler, ctx, handler.operations.row("code_analysis", analysis["id"]), first


def test_begin_pins_original_invocation_and_rejects_unstated_version(bridge):
    handler, ctx, access, pin, config, args = bridge
    first = handler._begin(access, pin, config, args, "code-env-a")
    assert Draft202012Validator(CODE_TOOL_SCHEMAS["knowledge_svn_update"][1]).is_valid(first)
    assert handler._begin(access, pin, config, args, "code-env-a") == first
    analysis = handler.operations.row("code_analysis", first["analysis_id"])
    assert analysis["job_id"] == ctx.job_id and analysis["invocation_id"] == ctx.invocation_id
    with pytest.raises(CodeKnowledgeError, match="CODE_SEARCH_CONTEXT_CHANGED"):
        handler._begin(access, pin, config, {**args, "revision": 101}, "code-env-a")

    # A model-selected revision is not authorization, even with a forged success receipt.
    handler.receipts = SimpleNamespace(
        read=lambda *a, **kw: dict(
            search_id="fake",
            requested_revision=101,
            version_mode="exact",
            question_hash=ctx.question_hash,
            invocation_id=ctx.invocation_id,
            deadline_ms=int(utc_time(ctx.deadline_at).timestamp() * 1000),
        )
    )
    with pytest.raises(CodeKnowledgeError, match="SVN_REVISION_REQUIRED"):
        handler._begin(access, pin, config, {**args, "revision": 101}, "code-env-a")


def test_analysis_uses_job_deadline_not_completed_search_request_deadline(bridge):
    handler, ctx, access, pin, config, args = bridge
    receipt = dict(handler.receipts.read("receipt"))
    receipt["deadline_ms"] -= 240_000
    handler.receipts = SimpleNamespace(read=lambda *a, **kw: receipt)
    first = handler._begin(access, pin, config, args, "code-env-a")
    analysis = handler.operations.row("code_analysis", first["analysis_id"])
    assert utc_time(analysis["deadline_at"]) == utc_time(ctx.deadline_at)
    assert utc_time(analysis["deadline_at"]).timestamp() * 1000 > receipt["deadline_ms"]
    # The same admission still rejects an invocation whose original budget ended.
    handler.db.execute(
        "UPDATE agent_runtime_invocation SET execution_deadline_at=? WHERE invocation_id=?",
        ((utc_time(ctx.deadline_at) - timedelta(days=1)).isoformat(), ctx.invocation_id),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_EXECUTION_ENDED"):
        handler._begin(access, pin, config, args, "code-env-a")


@pytest.mark.parametrize(
    "error_code", ["CODE_CHECKOUT_IDENTITY_CHANGED", "CODE_CHECKOUT_PERMISSION_DENIED"]
)
def test_failed_identity_is_not_retried_under_a_new_request_key(bridge, error_code):
    handler, _, access, pin, config, args = bridge
    first = handler._begin(access, pin, config, args, "code-env-a")
    handler.db.execute(
        f"UPDATE {handler.operations.t('code_svn_operation')} SET state='failed',"
        "error_code=? WHERE id=?",
        (error_code, first["operation_id"]),
    )
    with pytest.raises(CodeKnowledgeError, match=error_code):
        handler._begin(access, pin, config, {**args, "request_key": "retry"}, "code-env-a")
    rows = handler.db.execute(f"SELECT id FROM {handler.operations.t('code_svn_operation')}")
    assert len(rows) == 1


def test_operation_poll_uses_published_schema_and_checks_job_ownership(bridge):
    handler, ctx, analysis, first = begin_reading(bridge)
    access, pin, config = bridge[2:5]
    handler.gateway = SimpleNamespace(
        authenticate=lambda *args: access,
        budget=lambda *args, **kw: SimpleNamespace(activate=nullcontext, check=lambda: None),
    )
    handler.access = SimpleNamespace(authenticate=lambda *args: access)
    handler.resources = SimpleNamespace(
        resolve=lambda base: pin,
        recheck=lambda value: None,
        store=SimpleNamespace(code_configuration=lambda revision: config),
    )
    args = {
        "environment": "env-a",
        "knowledge_base_id": "code-kb",
        "operation_id": first["operation_id"],
    }
    Draft202012Validator(CODE_TOOL_SCHEMAS["knowledge_get_source_operation"][0]).validate(args)
    request = dict(
        action="tool",
        tool="knowledge_get_source_operation",
        resource_revision_id=pin.revision_id,
        arguments=args,
    )
    result = handler.check(service_token="synthetic", knowledge_token="synthetic", request=request)
    assert result["state"] == "succeeded"
    assert result["source_access"]["analysis_id"] == analysis["id"]
    other_access = replace(access, job_id="another-job")
    handler.gateway.authenticate = lambda *args: other_access
    handler.access.authenticate = lambda *args: other_access
    with pytest.raises(CodeKnowledgeError, match="CODE_ENVIRONMENT_REQUIRED"):
        handler.check(service_token="synthetic", knowledge_token="synthetic", request=request)


def test_current_authorization_cannot_be_replaced_by_old_analysis(bridge):
    handler, _, analysis, _ = begin_reading(bridge)
    _, _, access, pin, config, _ = bridge
    with pytest.raises(CodeKnowledgeError, match="CODE_ANALYSIS_MISMATCH"):
        handler._context(
            replace(access, current_authorization_hash="e" * 64),
            pin,
            config,
            analysis,
            "code-env-a",
        )


def history(f, handler, ctx, analysis):
    args = dict(
        knowledge_base_id="code-kb",
        analysis_id=analysis["id"],
        request_key="history",
        path="",
        selector={"kind": "latest"},
    )
    operation = handler._history(ctx, analysis, f[4], "knowledge_svn_log", args)
    op = handler.operations.claim(operation["id"], owner="worker")
    handler.operations.complete_history(
        ctx,
        op["id"],
        owner="worker",
        claim=op["claim_version"],
        result_hash="f" * 64,
        metadata={"count": 1},
    )
    return args, handler.operations.row("code_svn_operation", op["id"])


def test_expired_payload_requeues_read_only_with_original_deadline_and_digest(bridge):
    handler, ctx, analysis, _ = begin_reading(bridge)
    _, op = history(bridge, handler, ctx, analysis)

    def expired(*a, **kw):
        raise CodeKnowledgeError("CODE_RESULT_EXPIRED")

    handler.results = SimpleNamespace(read=expired)
    result = handler._view(ctx, analysis, bridge[4], op)
    assert result["state"] == "queued" and "result" not in result
    repeated = handler.operations.row("code_svn_operation", op["id"])
    assert repeated["result_hash"] == op["result_hash"]
    assert repeated["deadline_at"] == op["deadline_at"]
    assert json_value(repeated["result_json"]) == {"count": 1}


def test_cursor_cannot_change_path_version_context_or_original_deadline(bridge):
    handler, ctx, analysis, _ = begin_reading(bridge)
    args, op = history(bridge, handler, ctx, analysis)
    handler.results = SimpleNamespace(
        read=lambda *a, **kw: dict(
            has_more=True,
            next_revision=98,
            entries=[{"message": "synthetic private text"}],
        )
    )
    view = handler._view(ctx, analysis, bridge[4], op)
    cursor = view["next_cursor"]
    assert "synthetic private text" not in cursor
    following = handler._history(
        ctx,
        analysis,
        bridge[4],
        "knowledge_svn_log",
        {**args, "request_key": "page2", "cursor": cursor},
    )
    assert utc_time(following["deadline_at"]) <= utc_time(op["deadline_at"])
    assert json_value(following["request_json"])["before"] == 98
    with pytest.raises(CodeKnowledgeError, match="CODE_HISTORY_CURSOR_INVALID"):
        handler._history(
            ctx,
            analysis,
            bridge[4],
            "knowledge_svn_log",
            {**args, "request_key": "wrong", "cursor": cursor, "path": "private"},
        )
    assert "synthetic private text" not in json.dumps(
        handler.operations.row("code_svn_operation", op["id"])
    )


def test_stopped_job_cannot_receive_already_finished_history(bridge):
    handler, ctx, analysis, _ = begin_reading(bridge)
    _, op = history(bridge, handler, ctx, analysis)
    handler.operations.db.execute(
        "UPDATE agent_job SET status='SUCCEEDED' WHERE id=?", (ctx.job_id,)
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_EXECUTION_ENDED"):
        handler._view(ctx, analysis, bridge[4], op)


def test_deadline_expiry_never_replays_update(bridge):
    handler, ctx, analysis, first = begin_reading(bridge)
    op = handler.operations.row("code_svn_operation", first["operation_id"])
    with pytest.raises(CodeKnowledgeError, match="CODE_OPERATION_REPLAY_DENIED"):
        handler.operations.replay_history(ctx, op["id"])


def configure_bridge(f):
    handler, _, access, pin, config, _ = f
    handler.gateway = SimpleNamespace(
        authenticate=lambda *a: access,
        budget=lambda *a, **kw: SimpleNamespace(activate=nullcontext, check=lambda: None),
    )
    handler.access = SimpleNamespace(authenticate=lambda *a: access)
    handler.resources = SimpleNamespace(
        resolve=lambda base: pin,
        recheck=lambda value: None,
        store=SimpleNamespace(code_configuration=lambda revision: config),
    )
    return handler


def test_directory_and_search_require_the_users_environment(bridge):
    handler = configure_bridge(bridge)

    def call(request):
        return handler.check(
            service_token="synthetic", knowledge_token="synthetic", request=request
        )

    directory = dict(action="directory_context", environment="env-a")
    assert call(directory)["environment_id"] == "code-env-a"
    with pytest.raises(CodeKnowledgeError, match="CODE_ENVIRONMENT_MISMATCH"):
        call({**directory, "environment": "env-b"})
    request = dict(
        action="search_context",
        environment="env-a",
        knowledge_base_id="code-kb",
        resource_revision_id="code-config",
        requested_revision=100,
    )
    assert call(request)["environment_id"] == "code-env-a"
    handler.db.execute(
        'DELETE FROM "knowledge.code_resource_environment" WHERE environment_id=?', ("code-env-a",)
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_ENVIRONMENT_UNAVAILABLE"):
        call(request)


@pytest.mark.parametrize(
    "message",
    [
        "SVN r100",
        "环境：env-a 和 env-b环境 SVN r100",
        "环境：不存在 SVN r100",
        "环境：env-a，环境：不存在 SVN r100",
        "环境：env-a/env-b SVN r100",
        "环境：env-a、env-b SVN r100",
        "环境：env-a / env-b SVN r100",
        "env-a和env-b环境 SVN r100",
        "环境：env-a，env-b SVN r100",
    ],
)
def test_missing_unknown_or_multiple_environments_are_not_inferred(bridge, message):
    handler = configure_bridge(bridge)
    handler.db.execute(
        "UPDATE agent_message SET content=? WHERE job_id=? AND role='user'",
        (message, bridge[1].job_id),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_ENVIRONMENT_REQUIRED"):
        handler.check(
            service_token="synthetic",
            knowledge_token="synthetic",
            request=dict(action="directory_context", environment="env-a"),
        )


def test_analysis_environment_cannot_be_switched_and_disable_revokes_reads(bridge):
    handler, ctx, analysis, _ = begin_reading(bridge)
    with pytest.raises(CodeKnowledgeError, match="CODE_ANALYSIS_MISMATCH"):
        handler._context(bridge[2], bridge[3], bridge[4], analysis, "code-env-b")
    handler.db.execute(
        "UPDATE platform_environment SET status='disabled' WHERE id=?", (ctx.environment_id,)
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_ENVIRONMENT_UNAVAILABLE"):
        handler.operations.require_reader(ctx, analysis["id"])


@pytest.mark.parametrize(
    "text",
    [
        "环境：env-a SVN r100",
        "env-a环境 SVN r100",
        "代码环境a环境 SVN r100",
        "环境：代码环境a，SVN r100",
    ],
)
def test_explicit_environment_code_and_unique_name(bridge, text):
    from app.modules.knowledge.infrastructure.code_environment import declared_environment

    assert declared_environment(bridge[0].db, text)["id"] == "code-env-a"


def test_empty_or_ambiguous_environment_names_do_not_select_a_default(bridge):
    from app.modules.knowledge.infrastructure.code_environment import declared_environment

    db = bridge[0].db
    db.execute("UPDATE platform_environment SET display_name='' WHERE id='code-env-b'")
    assert declared_environment(db, "环境：env-a SVN r100")["id"] == "code-env-a"
    db.execute(
        "UPDATE platform_environment SET display_name='同名环境' WHERE id IN ('code-env-a','code-env-b')"
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_ENVIRONMENT_REQUIRED"):
        declared_environment(db, "环境：同名环境 SVN r100")
    assert declared_environment(db, "环境：env-a SVN r100")["id"] == "code-env-a"


def test_environment_name_already_ending_in_environment_is_explicit(bridge):
    from app.modules.knowledge.infrastructure.code_environment import declared_environment

    db = bridge[0].db
    db.execute("UPDATE platform_environment SET display_name='生产环境' WHERE id='code-env-a'")
    assert declared_environment(db, "在生产环境下查询 SVN r100")["id"] == "code-env-a"
