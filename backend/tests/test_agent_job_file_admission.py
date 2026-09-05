from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

import pytest

import app.modules.job.application.create_agent_job_service as job_service_module
from app.modules.channel.domain.channel_event import ChannelAttachment, ChannelFileReference
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    SystemNoticeIntake,
)
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from backend.tests.support.file_workspace import (
    FakeDownloader,
    file_workspace_command_kwargs,
    multimodal_container,
)


FILE_FEATURES = {"workspace_enabled": True, "file_mcp_enabled": True}


def _capture_admission_plans(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    observed: list[Any] = []
    real_plan = job_service_module.plan_file_admission

    def capture(**kwargs: object) -> Any:
        plan = real_plan(**kwargs)  # type: ignore[arg-type]
        observed.append(plan)
        return plan

    monkeypatch.setattr(job_service_module, "plan_file_admission", capture)
    return observed


def _command(
    runtime: Any,
    *,
    key: str,
    conversation_id: str,
    message: str,
    **overrides: object,
) -> CreateAgentJobCommand:
    file_kwargs = file_workspace_command_kwargs(runtime)
    file_kwargs["task_file_features"] = dict(FILE_FEATURES)
    values: dict[str, object] = {
        "idempotency_key": key,
        "requester_id": "user_local_admin",
        "external_conversation_id": conversation_id,
        "external_event_id": f"{key}-event",
        "external_message_id": f"{key}-message",
        "user_message": message,
        "source_channel": "dingding_stream",
        "source_connector_id": "connector-dingtalk-stream-default",
        "conversation_type": "direct",
        "bot_identity": "robot-redacted",
        **file_kwargs,
    }
    values.update(overrides)
    return CreateAgentJobCommand(**values)  # type: ignore[arg-type]


def _stage_ready_files(
    runtime: Any,
    *,
    conversation_id: str,
    names: tuple[str, ...],
    stage_key: str | None = None,
) -> dict[str, tuple[str, str]]:
    attachments = tuple(
        ChannelAttachment(
            media_type="document",
            file_name=name,
            source_credential=f"download-{ordinal}",
        )
        for ordinal, name in enumerate(names, start=1)
    )
    source_job = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key=stage_key or f"{conversation_id}-stage",
            conversation_id=conversation_id,
            message="保存这些文件",
            external_message_id=(
                f"{stage_key}-source-message"
                if stage_key
                else f"{conversation_id}-source-message"
            ),
            attachments=attachments,
        )
    )
    assert isinstance(source_job, AgentJob)
    runtime.attachment_service.downloader = FakeDownloader(  # type: ignore[union-attr]
        {
            f"download-{ordinal}": f"content-{ordinal}".encode()
            for ordinal in range(1, len(names) + 1)
        }
    )
    source_attachments = runtime.agent_repository.list_attachments(source_job.id)
    for ordinal, attachment in enumerate(source_attachments, start=1):
        assert runtime.attachment_service.process(  # type: ignore[union-attr]
            attachment.id,
            f"{conversation_id}-process-{ordinal}",
        ) in {"waiting", "released"}
    rows = runtime.database.execute(
        """
        select a.file_name, b.file_id, b.version_id
          from message_attachment a
          join message_attachment_file_binding b on b.attachment_id = a.id
         where a.job_id = ?
        """,
        (source_job.id,),
    )
    for row in rows:
        runtime.database.execute(
            "update managed_file set source_received_at = ? where id = ?",
            (datetime.now(UTC).isoformat(), row["file_id"]),
        )
    return {
        str(row["file_name"]): (str(row["file_id"]), str(row["version_id"]))
        for row in rows
    }


def test_execute_output_request_with_conversation_time_word_has_no_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    plans = _capture_admission_plans(monkeypatch)

    result = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-output-conversation-time",
            conversation_id="admission-output-conversation",
            message="生成 md 文件记录我今天的对话",
        )
    )

    assert isinstance(result, AgentJob)
    assert (plans[-1].gate.action, plans[-1].gate.reason_code) == (
        "enqueue_job",
        "no_file_dependency",
    )
    assert result.status == JobStatus.PENDING
    assert result.task_workspace_id
    assert result.business_application_route_decision["file_turn_dependencies"] == []
    manifest_service = runtime.create_agent_job_service.file_manifest_service
    assert manifest_service is not None
    manifest = manifest_service.runtime_manifest(result.id)
    assert manifest["schema_version"] == 5
    assert manifest["items"] == []


def test_execute_explicit_time_window_source_is_metadata_without_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    conversation_id = "admission-time-window"
    identities = _stage_ready_files(
        runtime,
        conversation_id=conversation_id,
        names=("今日材料.txt",),
    )
    plans = _capture_admission_plans(monkeypatch)

    result = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-time-window-output",
            conversation_id=conversation_id,
            message="根据今天上传的文件生成汇总.md",
        )
    )

    assert isinstance(result, AgentJob)
    assert plans[-1].gate.action == "enqueue_job"
    dependencies = result.business_application_route_decision["file_turn_dependencies"]
    assert [
        (item["file_id"], item["version_id"], item["required_capability"], item["reason"])
        for item in dependencies
    ] == [(*identities["今日材料.txt"], "METADATA", "TIME_WINDOW")]
    manifest_service = runtime.create_agent_job_service.file_manifest_service
    assert manifest_service is not None
    manifest = manifest_service.runtime_manifest(result.id)
    assert [(item["file_id"], item["auto_materialize"]) for item in manifest["items"]] == [
        (identities["今日材料.txt"][0], False)
    ]


@pytest.mark.parametrize(
    ("message", "reason_code"),
    (
        ("2月30日的文件", "invalid_time_window"),
        ("读取今天上传的文件", "time_window_empty"),
    ),
)
def test_execute_file_notice_does_not_create_job_or_workspace(
    message: str,
    reason_code: str,
) -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    before_jobs = runtime.agent_repository.count_rows("agent_job")

    result = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key=f"admission-notice-{reason_code}",
            conversation_id=f"admission-notice-{reason_code}",
            message=message,
        )
    )

    assert isinstance(result, SystemNoticeIntake)
    assert result.reason_code == reason_code
    assert result.task_workspace_id == ""
    assert runtime.agent_repository.count_rows("agent_job") == before_jobs


def test_execute_binding_priority_matrix_uses_frozen_candidate_set() -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    conversation_id = "admission-priority"
    identities = _stage_ready_files(
        runtime,
        conversation_id=conversation_id,
        names=("计划.txt", "说明.md"),
    )

    exact = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-priority-filename",
            conversation_id=conversation_id,
            message="读取计划.txt",
        )
    )
    assert isinstance(exact, AgentJob)
    assert [
        item["file_id"]
        for item in exact.business_application_route_decision["file_turn_dependencies"]
    ] == [identities["计划.txt"][0]]

    explicit = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-priority-explicit",
            conversation_id=conversation_id,
            message="读取指定文件",
            file_references=(
                ChannelFileReference(
                    file_id=identities["说明.md"][0],
                    version_id=identities["说明.md"][1],
                ),
            ),
        )
    )
    assert isinstance(explicit, AgentJob)
    assert [
        item["file_id"]
        for item in explicit.business_application_route_decision["file_turn_dependencies"]
    ] == [identities["说明.md"][0]]

    quoted = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-priority-quote",
            conversation_id=conversation_id,
            message="分析引用消息里的附件",
            quoted_external_message_id=f"{conversation_id}-source-message",
        )
    )
    assert isinstance(quoted, AgentJob)
    assert {
        item["file_id"]
        for item in quoted.business_application_route_decision["file_turn_dependencies"]
    } == {identities["计划.txt"][0], identities["说明.md"][0]}

    ambiguous = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-priority-ambiguous",
            conversation_id=conversation_id,
            message="分析这些文件",
        )
    )
    assert isinstance(ambiguous, SystemNoticeIntake)
    assert ambiguous.reason_code == "file_binding_ambiguous"

    current = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-priority-current",
            conversation_id=conversation_id,
            message="结合引用消息分析这个文件",
            quoted_external_message_id=f"{conversation_id}-source-message",
            attachments=(
                ChannelAttachment(
                    media_type="document",
                    file_name="当前.txt",
                    source_credential="download-current",
                ),
            ),
        )
    )
    assert isinstance(current, AgentJob)
    assert current.status == JobStatus.WAITING_INPUT
    assert [
        item["reason"]
        for item in current.business_application_route_decision["file_turn_dependencies"]
    ] == ["CURRENT_MESSAGE"]


def test_execute_unique_deixis_binds_the_only_workspace_file() -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    conversation_id = "admission-deixis"
    identities = _stage_ready_files(
        runtime,
        conversation_id=conversation_id,
        names=("唯一材料.txt",),
    )

    result = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-deixis-read",
            conversation_id=conversation_id,
            message="分析这个文件",
        )
    )

    assert isinstance(result, AgentJob)
    assert [
        (item["file_id"], item["reason"])
        for item in result.business_application_route_decision["file_turn_dependencies"]
    ] == [(identities["唯一材料.txt"][0], "DEIXIS")]


def test_execute_time_window_over_limit_preserves_existing_workspace() -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    conversation_id = "admission-time-window-limit"
    for batch, start in enumerate((1, 11, 21), start=1):
        _stage_ready_files(
            runtime,
            conversation_id=conversation_id,
            names=tuple(
                f"材料-{ordinal:02d}.txt"
                for ordinal in range(start, min(start + 10, 22))
            ),
            stage_key=f"{conversation_id}-stage-{batch}",
        )
    active = runtime.database.execute_one(
        "select id from task_workspace where status = 'ACTIVE'"
    )
    assert active is not None

    result = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-time-window-limit-read",
            conversation_id=conversation_id,
            message="读取今天上传的文件",
        )
    )

    assert isinstance(result, SystemNoticeIntake)
    assert result.reason_code == "time_window_too_many"
    assert result.task_workspace_id == str(active["id"])


def test_waiting_job_restores_legacy_dependency_payload_on_attachment_completion() -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    result = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            key="admission-legacy-recovery",
            conversation_id="admission-legacy-recovery",
            message="读取这个文件",
            attachments=(
                ChannelAttachment(
                    media_type="document",
                    file_name="历史任务.txt",
                    source_credential="download-legacy",
                ),
            ),
        )
    )
    assert isinstance(result, AgentJob)
    assert result.status == JobStatus.WAITING_INPUT
    route_decision = dict(result.business_application_route_decision)
    legacy_payloads = []
    for item in route_decision["file_turn_dependencies"]:
        legacy_item = dict(item)
        legacy_item.pop("source_received_at", None)
        legacy_item.pop("content_available", None)
        legacy_payloads.append(legacy_item)
    route_decision["file_turn_dependencies"] = legacy_payloads
    runtime.database.execute(
        "update agent_job set business_application_route_decision_json = ? where id = ?",
        (json.dumps(route_decision, ensure_ascii=False), result.id),
    )
    attachment = runtime.agent_repository.list_attachments(result.id)[0]
    runtime.attachment_service.downloader = FakeDownloader(  # type: ignore[union-attr]
        {"download-legacy": b"legacy-content"}
    )

    assert runtime.attachment_service.process(  # type: ignore[union-attr]
        attachment.id, "admission-legacy-recovery-process"
    ) == "released"
    assert runtime.agent_repository.get_job(result.id).status == JobStatus.PENDING


@pytest.mark.parametrize("workspace_enabled", (False, True))
def test_output_request_workspace_lifecycle_matches_frozen_feature(
    workspace_enabled: bool,
) -> None:
    runtime = multimodal_container(
        task_file_features={"workspace_enabled": workspace_enabled}
    )
    kwargs = file_workspace_command_kwargs(runtime)
    kwargs["task_file_features"] = {"workspace_enabled": workspace_enabled}

    result = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=f"admission-workspace-{workspace_enabled}",
            requester_id="user_local_admin",
            external_conversation_id=f"admission-workspace-{workspace_enabled}",
            external_event_id=f"admission-workspace-{workspace_enabled}-event",
            user_message="创建 report.md",
            source_channel="dingding_stream",
            source_connector_id="connector-dingtalk-stream-default",
            conversation_type="direct",
            bot_identity="robot-redacted",
            **kwargs,
        )
    )

    assert isinstance(result, AgentJob)
    assert bool(result.task_workspace_id) is workspace_enabled
