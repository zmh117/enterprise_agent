from __future__ import annotations

from datetime import datetime

from app.modules.job.application.file_context import (
    SHANGHAI,
    CurrentMessageAttachment,
    WorkspaceFileCandidate,
    evaluate_file_gate,
    file_dependency_payload,
    infer_capability,
    parse_time_window,
    resolve_file_context,
    system_notice_markdown,
)


def test_current_message_attachments_bind_before_other_evidence() -> None:
    decision = resolve_file_context(
        text="这个表有多少延期？",
        current_attachments=(CurrentMessageAttachment(file_name="计划.xlsx", ordinal=1),),
        quoted_external_message_id="quoted-1",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="其他.docx",
                message_external_id="quoted-1",
                source_status="READY",
                readability_status="AVAILABLE",
            ),
        ),
    )
    assert len(decision.dependencies) == 1
    assert decision.dependencies[0].reason == "CURRENT_MESSAGE"
    assert decision.dependencies[0].required_capability == "READABLE_CONTENT"


def test_quote_binds_attachments_on_referenced_message() -> None:
    decision = resolve_file_context(
        text="总结一下",
        quoted_external_message_id="msg-file",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="计划.xlsx",
                attachment_id="a1",
                message_external_id="msg-file",
                source_status="READY",
                readability_status="PENDING",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="无关.txt",
                attachment_id="a2",
                message_external_id="other",
                source_status="READY",
                readability_status="NOT_REQUIRED",
            ),
        ),
    )
    assert [item.version_id for item in decision.dependencies] == ["v1"]
    assert decision.dependencies[0].reason == "QUOTE"


def test_unresolved_quote_does_not_fall_back_to_deixis() -> None:
    decision = resolve_file_context(
        text="这个文件讲了什么？",
        quoted_external_message_id="missing",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="计划.xlsx",
                source_status="READY",
                readability_status="PENDING",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
        ),
    )
    assert decision.dependencies == ()
    assert decision.quote_unresolved is True


def test_exact_filename_binds_unique_workspace_file() -> None:
    decision = resolve_file_context(
        text="请看 项目计划.xlsx 里有多少任务",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="AVAILABLE",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="会议纪要.md",
                source_status="READY",
                readability_status="NOT_REQUIRED",
            ),
        ),
    )
    assert [item.display_name for item in decision.dependencies] == ["项目计划.xlsx"]
    assert decision.dependencies[0].reason == "FILENAME"


def test_duplicate_display_name_is_ambiguous() -> None:
    decision = resolve_file_context(
        text="打开 计划.xlsx",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="计划.xlsx",
                source_status="READY",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="计划.xlsx",
                source_status="READY",
            ),
        ),
    )
    assert decision.ambiguous is True
    assert decision.dependencies == ()


def test_substring_without_full_filename_does_not_bind() -> None:
    decision = resolve_file_context(
        text="这个计划里延期多少？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="PENDING",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
        ),
    )
    assert decision.dependencies == ()


def test_image_time_window_question_returns_metadata_candidate() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(
        text="今天发的图片什么内容",
        now=now,
        candidates=(
            WorkspaceFileCandidate(
                file_id="f-old",
                version_id="v-old",
                display_name="notes.txt",
                source_status="READY",
                readability_status="NOT_REQUIRED",
                source_ready_at="2026-08-19T02:00:00+00:00",
                source_received_at="2026-08-19T02:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f-image",
                version_id="v-image",
                display_name="image-1-980757d6.png",
                source_status="READY",
                readability_status="AVAILABLE",
                source_ready_at="2026-08-19T01:40:47+00:00",
                source_received_at="2026-08-19T01:40:47+00:00",
            ),
        ),
    )
    assert [item.version_id for item in decision.dependencies] == ["v-image"]
    assert decision.dependencies[0].reason == "TIME_WINDOW"
    assert decision.dependencies[0].required_capability == "METADATA"


def test_image_deixis_does_not_bind_later_non_image() -> None:
    decision = resolve_file_context(
        text="这张图片讲了什么？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f-image",
                version_id="v-image",
                display_name="scan.png",
                source_status="READY",
                readability_status="AVAILABLE",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f-txt",
                version_id="v-txt",
                display_name="later.txt",
                source_status="READY",
                readability_status="NOT_REQUIRED",
                source_ready_at="2026-08-19T00:00:00+00:00",
            ),
        ),
    )
    assert [item.display_name for item in decision.dependencies] == ["scan.png"]


def test_image_deixis_without_images_does_not_bind() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(
        text="今天发的图片什么内容",
        now=now,
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="notes.txt",
                source_status="READY",
                source_ready_at="2026-08-19T00:00:00+00:00",
                source_received_at="2026-08-19T00:00:00+00:00",
            ),
        ),
    )
    assert decision.dependencies == ()
    assert decision.notice_kind == "time_window_empty"
    assert evaluate_file_gate(decision).action == "system_notice"


def test_deixis_binds_unique_latest_ready_file() -> None:
    decision = resolve_file_context(
        text="这个表有多少负责人？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="旧.txt",
                source_status="READY",
                readability_status="NOT_REQUIRED",
                source_ready_at="2026-08-17T00:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="PENDING",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
        ),
    )
    assert [item.version_id for item in decision.dependencies] == ["v2"]
    assert decision.dependencies[0].reason == "DEIXIS"


def test_deixis_with_multiple_latest_files_is_ambiguous() -> None:
    decision = resolve_file_context(
        text="刚才那个文件呢？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="a.xlsx",
                source_status="READY",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="b.xlsx",
                source_status="READY",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
        ),
    )
    assert decision.ambiguous is True
    gate = evaluate_file_gate(decision)
    assert gate.action == "system_notice"
    assert gate.reason_code == "file_binding_ambiguous"


def test_plural_deixis_with_multiple_files_is_ambiguous() -> None:
    decision = resolve_file_context(
        text="比较这些文件，只回复一次",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="input-1.txt",
                source_status="READY",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="input-2.txt",
                source_status="READY",
                source_ready_at="2026-08-18T00:01:00+00:00",
            ),
        ),
    )
    assert decision.ambiguous is True
    assert decision.dependencies == ()
    title, body = system_notice_markdown(
        notice_kind="ambiguous",
        display_names=decision.clarification_names,
    )
    assert "请指明" in title
    assert "{" not in body


def test_no_hard_evidence_returns_empty_dependencies() -> None:
    decision = resolve_file_context(
        text="ONES MCP 的权限应该放在哪里？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="PENDING",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
        ),
    )
    assert decision.dependencies == ()
    assert evaluate_file_gate(decision).action == "enqueue_job"


def test_metadata_question_does_not_wait_for_readable_content() -> None:
    assert infer_capability("这个文件叫什么名字？") == "METADATA"
    decision = resolve_file_context(
        text="这个文件叫什么名字？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="PENDING",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
        ),
    )
    gate = evaluate_file_gate(decision)
    assert gate.action == "enqueue_job"


def test_readable_content_pending_is_system_notice() -> None:
    decision = resolve_file_context(
        text="总结一下 项目计划.xlsx",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="PENDING",
            ),
        ),
    )
    gate = evaluate_file_gate(decision)
    assert gate.action == "system_notice"
    assert gate.reason_code == "file_readable_content_not_ready"
    title, body = system_notice_markdown(
        notice_kind="pending",
        display_names=("项目计划.xlsx",),
    )
    assert "可读内容" in body
    assert title.startswith("文件")
    assert "{" not in body


def test_rejected_source_notice_explains_format_mismatch() -> None:
    title, body = system_notice_markdown(
        notice_kind="rejected",
        display_names=("图片-20260901-195406.png",),
        failure_reasons=("文件实际格式与文件扩展名不匹配",),
    )

    assert title == "文件未进入工作区"
    assert "文件实际格式与文件扩展名不匹配" in body
    assert "转换为匹配的受支持格式后重新发送" in body


def test_current_message_waits_for_source_import() -> None:
    decision = resolve_file_context(
        text="总结这份文件",
        current_attachments=(CurrentMessageAttachment(file_name="计划.xlsx", ordinal=1),),
    )
    gate = evaluate_file_gate(decision)
    assert gate.action == "wait_source"
    assert gate.reason_code == "file_source_pending"


def test_original_request_does_not_wait_for_readable_content() -> None:
    assert infer_capability("把原文件发给我") == "ORIGINAL"
    decision = resolve_file_context(
        text="把原文件发给我",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="PENDING",
                source_ready_at="2026-08-18T00:00:00+00:00",
            ),
        ),
    )
    assert evaluate_file_gate(decision).action == "enqueue_job"


def test_processing_failed_is_system_notice() -> None:
    decision = resolve_file_context(
        text="总结 项目计划.xlsx",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="UNAVAILABLE",
            ),
        ),
    )
    gate = evaluate_file_gate(decision)
    assert gate.action == "system_notice"
    assert gate.reason_code == "file_processing_failed"


def test_failed_file_status_question_reaches_agent_as_metadata() -> None:
    decision = resolve_file_context(
        text="《项目计划.xlsx》为什么可读内容生成失败？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="UNAVAILABLE",
            ),
        ),
    )

    gate = evaluate_file_gate(decision)

    assert decision.dependencies[0].required_capability == "METADATA"
    assert gate.action == "enqueue_job"
    assert gate.reason_code == "file_capability_ready"


def test_failed_file_dependency_preserves_safe_machine_error_code() -> None:
    decision = resolve_file_context(
        text="《项目计划.xlsx》的失败原因是什么？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="项目计划.xlsx",
                source_status="READY",
                readability_status="UNAVAILABLE",
                error_code="docling_conversion_failed",
            ),
        ),
    )

    payload = file_dependency_payload(decision.dependencies[0])

    assert payload["error_code"] == "docling_conversion_failed"


def test_rejected_file_failure_question_reaches_agent_with_safe_metadata() -> None:
    decision = resolve_file_context(
        text="《M102200001(1).txt》的失败原因是什么？",
        candidates=(
            WorkspaceFileCandidate(
                file_id="",
                version_id="",
                display_name="M102200001(1).txt",
                source_status="REJECTED",
                readability_status="UNAVAILABLE",
                error_code="file_encoding_invalid",
            ),
        ),
    )

    gate = evaluate_file_gate(decision)

    assert gate.action == "enqueue_job"
    assert gate.dependencies[0].error_code == "file_encoding_invalid"


def test_mixed_ready_and_failed_files_reach_agent_with_both_dependencies() -> None:
    decision = resolve_file_context(
        text="对比 正常.xlsx 和 失败.xlsx 的内容，并说明无法覆盖的部分",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f-ready",
                version_id="v-ready",
                display_name="正常.xlsx",
                source_status="READY",
                readability_status="AVAILABLE",
            ),
            WorkspaceFileCandidate(
                file_id="f-failed",
                version_id="v-failed",
                display_name="失败.xlsx",
                source_status="READY",
                readability_status="UNAVAILABLE",
            ),
        ),
    )

    gate = evaluate_file_gate(decision)

    assert gate.action == "enqueue_job"
    assert {item.version_id for item in gate.dependencies} == {"v-ready", "v-failed"}


def test_explicit_output_request_does_not_bind_generic_deixis_to_failed_input() -> None:
    decision = resolve_file_context(
        text="生成 test.md，输出这个文件的完整目录",
        requests_file_output=True,
        candidates=(
            WorkspaceFileCandidate(
                file_id="f-failed",
                version_id="v-failed",
                display_name="历史失败日志.log",
                source_status="READY",
                readability_status="UNAVAILABLE",
                source_ready_at="2026-08-24T15:00:00+00:00",
            ),
        ),
    )

    assert decision.dependencies == ()
    assert evaluate_file_gate(decision).action == "enqueue_job"


def test_parse_time_window_natural_week_and_calendar_dates() -> None:
    monday = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
    last_week = parse_time_window("上周的图", now=monday)
    assert last_week is not None
    assert last_week.start.isoformat() == "2026-08-10T00:00:00+08:00"
    assert last_week.end.isoformat() == "2026-08-17T00:00:00+08:00"

    this_week = parse_time_window("这周的文件", now=monday)
    assert this_week is not None
    assert this_week.start.isoformat() == "2026-08-17T00:00:00+08:00"
    assert this_week.end.isoformat() == "2026-08-24T00:00:00+08:00"

    day = parse_time_window("8月12日的文件", now=monday)
    assert day is not None
    assert day.start.isoformat() == "2026-08-12T00:00:00+08:00"
    assert day.end.isoformat() == "2026-08-13T00:00:00+08:00"

    spanned = parse_time_window("8月10日到15日的附件", now=monday)
    assert spanned is not None
    assert spanned.start.isoformat() == "2026-08-10T00:00:00+08:00"
    assert spanned.end.isoformat() == "2026-08-16T00:00:00+08:00"

    january = datetime(2026, 1, 5, 9, 0, tzinfo=SHANGHAI)
    rolled = parse_time_window("12月20日的文件", now=january)
    assert rolled is not None
    assert rolled.start.isoformat() == "2025-12-20T00:00:00+08:00"


def test_invalid_calendar_date_and_reversed_range_do_not_resolve() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=SHANGHAI)
    assert parse_time_window("2月30日的文件", now=now) is None
    assert parse_time_window("8月15日到10日的文件", now=now) is None


def test_invalid_file_date_returns_safe_notice_without_job() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(text="2月30日的文件", now=now)
    gate = evaluate_file_gate(decision)
    assert decision.dependencies == ()
    assert gate.action == "system_notice"
    assert gate.reason_code == "invalid_time_window"
    title, body = system_notice_markdown(
        notice_kind="invalid_time_window", display_names=()
    )
    assert "有效日期" in title
    assert "今天" not in body


def test_invalid_date_without_file_semantics_stays_on_normal_job_path() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(text="2月30日这个说法成立吗", now=now)
    assert decision.notice_kind == ""
    assert decision.dependencies == ()
    assert evaluate_file_gate(decision).action == "enqueue_job"


def test_date_chat_without_file_token_does_not_bind() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(
        text="8月12日附近有什么安排",
        now=now,
        retained_candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="plan.xlsx",
                source_status="READY",
                source_received_at="2026-08-12T04:00:00+00:00",
            ),
        ),
    )
    assert decision.dependencies == ()
    assert decision.notice_kind == ""
    assert evaluate_file_gate(decision).reason_code == "no_file_dependency"


def test_time_window_beats_current_workspace_deixis() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(
        text="上周这张图",
        now=now,
        candidates=(
            WorkspaceFileCandidate(
                file_id="f-this-week",
                version_id="v-this-week",
                display_name="today.png",
                source_status="READY",
                readability_status="AVAILABLE",
                source_ready_at="2026-08-17T01:00:00+00:00",
                source_received_at="2026-08-17T01:00:00+00:00",
            ),
        ),
        retained_candidates=(
            WorkspaceFileCandidate(
                file_id="f-last-week",
                version_id="v-last-week",
                display_name="last-week.png",
                source_status="READY",
                readability_status="AVAILABLE",
                source_received_at="2026-08-12T04:00:00+00:00",
            ),
        ),
    )
    assert [item.version_id for item in decision.dependencies] == ["v-last-week"]
    assert decision.dependencies[0].reason == "TIME_WINDOW"


def test_empty_time_window_is_system_notice_not_job() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(text="上周的附件", now=now)
    gate = evaluate_file_gate(decision)
    assert gate.action == "system_notice"
    assert gate.reason_code == "time_window_empty"
    _title, body = system_notice_markdown(notice_kind="time_window_empty", display_names=())
    assert "仍可访问" in body
    assert "没发过" not in body
    assert "从来没有" not in body


def test_multiple_time_window_content_questions_return_metadata_candidates() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(
        text="上周的文件什么内容",
        now=now,
        retained_candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="a.txt",
                source_status="READY",
                source_received_at="2026-08-12T04:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="b.txt",
                source_status="READY",
                source_received_at="2026-08-13T04:00:00+00:00",
            ),
        ),
    )
    assert decision.ambiguous is False
    assert {item.version_id for item in decision.dependencies} == {"v1", "v2"}
    assert all(item.required_capability == "METADATA" for item in decision.dependencies)
    gate = evaluate_file_gate(decision)
    assert gate.action == "enqueue_job"


def test_multiple_time_window_metadata_binds_all_without_preload() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
    assert infer_capability("上周发了哪些文件") == "METADATA"
    decision = resolve_file_context(
        text="上周发了哪些文件",
        now=now,
        retained_candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="a.txt",
                source_status="READY",
                source_received_at="2026-08-12T04:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f2",
                version_id="v2",
                display_name="b.txt",
                source_status="READY",
                source_received_at="2026-08-13T04:00:00+00:00",
            ),
        ),
    )
    assert {item.version_id for item in decision.dependencies} == {"v1", "v2"}
    assert all(item.reason == "TIME_WINDOW" for item in decision.dependencies)
    assert evaluate_file_gate(decision).action == "enqueue_job"


def test_unique_time_window_content_unavailable_remains_metadata_only() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(
        text="上周的文件什么内容",
        now=now,
        retained_candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="old.txt",
                source_status="READY",
                source_received_at="2026-08-12T04:00:00+00:00",
                content_available=False,
            ),
        ),
    )
    gate = evaluate_file_gate(decision)
    assert gate.action == "enqueue_job"
    assert decision.dependencies[0].required_capability == "METADATA"


def test_time_window_over_candidate_limit_is_system_notice() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI)
    decision = resolve_file_context(
        text="上周的文件什么内容",
        now=now,
        retained_candidates=tuple(
            WorkspaceFileCandidate(
                file_id=f"f{index}",
                version_id=f"v{index}",
                display_name=f"file-{index}.txt",
                source_status="READY",
                source_received_at="2026-08-12T04:00:00+00:00",
            )
            for index in range(21)
        ),
    )
    gate = evaluate_file_gate(decision)
    assert decision.dependencies == ()
    assert gate.action == "system_notice"
    assert gate.reason_code == "time_window_too_many"
