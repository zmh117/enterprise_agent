from __future__ import annotations

from app.modules.job.application.file_context import (
    CurrentMessageAttachment,
    WorkspaceFileCandidate,
    evaluate_file_gate,
    infer_capability,
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


def test_image_content_question_binds_unique_latest_image() -> None:
    decision = resolve_file_context(
        text="今天发的图片什么内容",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f-old",
                version_id="v-old",
                display_name="notes.txt",
                source_status="READY",
                readability_status="NOT_REQUIRED",
                source_ready_at="2026-08-19T02:00:00+00:00",
            ),
            WorkspaceFileCandidate(
                file_id="f-image",
                version_id="v-image",
                display_name="image-1-980757d6.png",
                source_status="READY",
                readability_status="AVAILABLE",
                source_ready_at="2026-08-19T01:40:47+00:00",
            ),
        ),
    )
    assert [item.version_id for item in decision.dependencies] == ["v-image"]
    assert decision.dependencies[0].reason == "DEIXIS"
    assert decision.dependencies[0].required_capability == "READABLE_CONTENT"


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
    decision = resolve_file_context(
        text="今天发的图片什么内容",
        candidates=(
            WorkspaceFileCandidate(
                file_id="f1",
                version_id="v1",
                display_name="notes.txt",
                source_status="READY",
                source_ready_at="2026-08-19T00:00:00+00:00",
            ),
        ),
    )
    assert decision.dependencies == ()
    assert decision.ambiguous is False


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
