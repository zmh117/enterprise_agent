from __future__ import annotations

from collections.abc import Callable
import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.channel.domain.channel_event import ChannelAttachment
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    StagedAttachmentIntake,
)
from app.modules.job.domain.agent_job import AgentJob
from app.shared.config import AttachmentSettings
from app.shared.exceptions import AppError, NonRetryableExecutionError, PermissionDenied
from backend.tests.support.file_workspace import file_workspace_command_kwargs, multimodal_container
from backend.tests.support.runtime import audit_trail, container


FILE_FEATURES = {"workspace_enabled": True, "file_mcp_enabled": True}
PERSISTED_TABLES = ("agent_session", "agent_message", "agent_job", "message_attachment")

INGRESS_AUDITS = ("permission.connector_ingress",)
CONNECTOR_AUDITS = (*INGRESS_AUDITS, "permission.connector_delivery")
PERMISSION_AUDITS = (*CONNECTOR_AUDITS, "permission.job_create.start")
APPLICATION_AUDITS = (
    *CONNECTOR_AUDITS,
    "authorization.business.job_create",
    "permission.job_create.start",
)


def _document(
    name: str = "资料.txt",
    *,
    credential: str = "download-1",
    size: int | None = None,
) -> ChannelAttachment:
    return ChannelAttachment(
        media_type="document",
        file_name=name,
        source_credential=credential,
        declared_size=size,
    )


def _command(**overrides: object) -> CreateAgentJobCommand:
    values: dict[str, object] = {
        "idempotency_key": "creation-contract",
        "external_conversation_id": "creation-contract-conversation",
        "requester_id": "local-user",
        "user_message": "check order",
    }
    values.update(overrides)
    return CreateAgentJobCommand(**values)  # type: ignore[arg-type]


def _application_command(runtime: Any, **overrides: object) -> CreateAgentJobCommand:
    application = runtime.business_application_repository.get_by_code("multimodal-test-application")
    file_kwargs = file_workspace_command_kwargs(runtime)
    publication = runtime.database.execute_one(
        "select config_hash from business_application_publication where id = ?",
        (file_kwargs["business_application_publication_id"],),
    )
    values: dict[str, object] = {
        **file_kwargs,
        "business_application_config_hash": str(publication["config_hash"]),
        "idempotency_key": "creation-contract-stage",
        "requester_id": "user_local_admin",
        "external_conversation_id": "creation-contract-stage-conversation",
        "external_event_id": "creation-contract-stage-event",
        "external_message_id": "creation-contract-stage-message",
        "user_message": "",
        "attachments": (_document(),),
        "source_channel": "dingding_stream",
        "source_connector_id": "connector-dingtalk-stream-default",
        "conversation_type": "direct",
        "bot_identity": "robot-redacted",
        "business_application_id": str(application["id"]),
        "business_application_code": "multimodal-test-application",
        "conversation_mode": "channel",
        "continuous_conversation_enabled": True,
        "attachments_enabled": True,
        "task_file_features": dict(FILE_FEATURES),
    }
    values.update(overrides)
    return CreateAgentJobCommand(**values)  # type: ignore[arg-type]


def _persisted_counts(runtime: Any) -> dict[str, int]:
    return {table: runtime.agent_repository.count_rows(table) for table in PERSISTED_TABLES}


def _assert_rejected_without_persisting(
    runtime: Any,
    action: Callable[[], object],
    *,
    error_type: type[AppError],
    message: str,
    error_code: str,
    audit_events: tuple[str, ...],
) -> AppError:
    before = _persisted_counts(runtime)

    def rejected() -> AppError:
        with pytest.raises(AppError) as raised:
            action()
        return raised.value

    error, events = audit_trail(runtime, rejected)

    assert type(error) is error_type
    assert str(error) == message
    assert error.error_code == error_code
    assert tuple(events) == audit_events
    assert _persisted_counts(runtime) == before
    return error


@pytest.mark.parametrize(
    ("service_overrides", "command_overrides", "message", "error_code", "audit_events"),
    (
        pytest.param(
            {},
            {"conversation_mode": "application"},
            "Legacy shared session mode cannot create new Jobs",
            "session_mode_unsupported",
            (),
            id="legacy-application-session",
        ),
        pytest.param(
            {},
            {"conversation_mode": "actor"},
            "Legacy shared session mode cannot create new Jobs",
            "session_mode_unsupported",
            (),
            id="legacy-actor-session",
        ),
        pytest.param(
            {},
            {
                "conversation_mode": "actor",
                "attachments": (_document("tool.exe"),),
                "attachments_enabled": True,
            },
            "Legacy shared session mode cannot create new Jobs",
            "session_mode_unsupported",
            (),
            id="session-mode-checked-before-attachments",
        ),
        pytest.param(
            {"business_authorization_service": None},
            {
                "business_application_id": "application-without-authorizer",
                "source_channel": "debug_api",
            },
            "Business authorization service is unavailable",
            "business_authorization_unavailable",
            INGRESS_AUDITS,
            id="business-authorizer-missing",
        ),
        pytest.param(
            {"business_authorization_service": None},
            {
                "business_application_id": "application-without-authorizer",
                "source_channel": "debug_api",
                "attachments": (_document(),),
                "attachments_enabled": False,
            },
            "message_attachments_disabled",
            "",
            (),
            id="attachments-checked-before-connectors-and-authorization",
        ),
        pytest.param(
            {"agent_config_service": None},
            {},
            "Published Agent runtime service is unavailable",
            "",
            PERMISSION_AUDITS,
            id="agent-config-missing",
        ),
        pytest.param(
            {"credential_cipher": None},
            {"attachments": (_document(),), "attachments_enabled": True},
            "Attachment credential encryption is unavailable",
            "",
            PERMISSION_AUDITS,
            id="attachment-cipher-missing",
        ),
        pytest.param(
            {"credential_cipher": None, "agent_config_service": None},
            {"attachments": (_document(),), "attachments_enabled": True},
            "Published Agent runtime service is unavailable",
            "",
            PERMISSION_AUDITS,
            id="agent-binding-checked-before-attachment-cipher",
        ),
        pytest.param(
            {"published_agent_runtime_enabled": False},
            {
                "business_application_id": "application-without-publication",
                "continuous_conversation_enabled": False,
            },
            "Business Application session isolation facts are incomplete",
            "session_isolation_incomplete",
            APPLICATION_AUDITS,
            id="application-publication-missing",
        ),
        pytest.param(
            {"published_agent_runtime_enabled": False},
            {
                "business_application_id": "application-shared-session",
                "business_application_publication_id": "publication-shared-session",
                "continuous_conversation_enabled": True,
            },
            "Business Application session isolation facts are incomplete",
            "session_isolation_incomplete",
            APPLICATION_AUDITS,
            id="continuous-session-outside-channel-mode",
        ),
    ),
)
def test_execute_rejects_before_persisting_the_turn(
    service_overrides: dict[str, object],
    command_overrides: dict[str, object],
    message: str,
    error_code: str,
    audit_events: tuple[str, ...],
) -> None:
    runtime = container()
    service = runtime.create_agent_job_service
    for name, value in service_overrides.items():
        setattr(service, name, value)

    _assert_rejected_without_persisting(
        runtime,
        lambda: service.execute(_command(**command_overrides)),
        error_type=NonRetryableExecutionError,
        message=message,
        error_code=error_code,
        audit_events=audit_events,
    )


def test_continuing_an_unknown_session_is_denied_without_creating_a_job() -> None:
    runtime = container()

    error = _assert_rejected_without_persisting(
        runtime,
        lambda: runtime.create_agent_job_service.execute(
            _command(continue_session_id="session-missing")
        ),
        error_type=PermissionDenied,
        message="Debug session cannot be continued",
        error_code="session_continue_denied",
        audit_events=PERMISSION_AUDITS,
    )

    assert error.safe_message == "无法继续该调试会话，请使用当前应用和数据范围创建新会话"


@pytest.mark.parametrize(
    ("source_channel", "continuous_conversation_enabled", "continues_conversation"),
    (
        pytest.param("dingding", True, True, id="continuous-channel"),
        pytest.param("dingding", False, False, id="non-continuous-channel"),
        pytest.param("debug_api", True, False, id="isolated-channel-never-continues"),
    ),
)
def test_execute_reuses_the_conversation_session_only_when_it_continues(
    source_channel: str,
    continuous_conversation_enabled: bool,
    continues_conversation: bool,
) -> None:
    runtime = container()
    first, second = (
        runtime.create_agent_job_service.execute(
            _command(
                idempotency_key=f"creation-contract-turn-{turn}",
                source_channel=source_channel,
                continuous_conversation_enabled=continuous_conversation_enabled,
            )
        )
        for turn in (1, 2)
    )

    assert isinstance(first, AgentJob)
    assert isinstance(second, AgentJob)
    session = runtime.session_repository.get_session(first.session_id)
    assert (session.session_key != f"legacy:{session.id}") is continues_conversation
    assert (first.session_id == second.session_id) is continues_conversation


def test_isolated_channel_without_a_conversation_gets_a_per_request_conversation() -> None:
    runtime = container()

    job = runtime.create_agent_job_service.execute(
        _command(
            idempotency_key="creation-contract-isolated",
            source_channel="debug_api",
            external_conversation_id="",
        )
    )

    assert isinstance(job, AgentJob)
    digest = hashlib.sha256(b"debug_api:creation-contract-isolated").hexdigest()
    session = runtime.session_repository.get_session(job.session_id)
    assert session.external_conversation_id == f"isolated:debug_api:{digest}"


def test_execute_without_attachments_does_not_require_the_attachment_cipher() -> None:
    runtime = container()
    runtime.create_agent_job_service.credential_cipher = None

    job = runtime.create_agent_job_service.execute(_command())

    assert isinstance(job, AgentJob)


class _PinnedAgentConfig:
    def __init__(
        self,
        *,
        publication: dict[str, Any],
        denied_directions: frozenset[str],
    ) -> None:
        self.repository = SimpleNamespace(
            get_definition=lambda agent_code: {"id": "agent-pinned", "code": agent_code}
        )
        self._publication = publication
        self._denied_directions = denied_directions

    def publication(self, publication_id: str) -> dict[str, Any]:
        assert publication_id == self._publication["id"]
        return self._publication

    def current_publication(self, agent_code: str) -> dict[str, Any]:
        raise AssertionError(
            f"pinned jobs must not resolve the current publication of {agent_code}"
        )

    def connector_allowed(self, *, publication_id: str, direction: str, connector_id: str) -> bool:
        assert publication_id == self._publication["id"]
        assert connector_id
        return direction not in self._denied_directions


def _pinned_publication(**overrides: object) -> dict[str, Any]:
    publication: dict[str, Any] = {
        "id": "agent-publication-pinned",
        "agent_id": "agent-pinned",
        "revision": 3,
        "config_hash": "pinned-hash",
        "runtime_kind": "python-v1",
        "snapshot": {"supported_runtime_protocol_versions": ["1.5"]},
    }
    publication.update(overrides)
    return publication


@pytest.mark.parametrize(
    ("publication_overrides", "command_overrides", "denied_directions", "message", "error_code"),
    (
        pytest.param(
            {"agent_id": "agent-other"},
            {},
            frozenset(),
            "Pinned Agent publication belongs to another Agent",
            "",
            id="publication-of-another-agent",
        ),
        pytest.param(
            {},
            {"fixed_agent_revision": 4},
            frozenset(),
            "Pinned Agent revision mismatch",
            "",
            id="revision-mismatch",
        ),
        pytest.param(
            {},
            {"fixed_agent_config_hash": "expected-hash"},
            frozenset(),
            "Pinned Agent hash mismatch",
            "",
            id="hash-mismatch",
        ),
        pytest.param(
            {},
            {"fixed_agent_revision": 4, "fixed_agent_config_hash": "expected-hash"},
            frozenset(),
            "Pinned Agent revision mismatch",
            "",
            id="revision-checked-before-hash",
        ),
        pytest.param(
            {"runtime_kind": "node-v1"},
            {},
            frozenset(),
            "Pinned Agent publication runtime is unsupported",
            "agent_runtime_kind_unsupported",
            id="runtime-kind-unsupported",
        ),
        pytest.param(
            {"runtime_kind": None},
            {},
            frozenset(),
            "Pinned Agent publication runtime is unsupported",
            "agent_runtime_kind_unsupported",
            id="runtime-kind-missing",
        ),
        pytest.param(
            {"snapshot": {"supported_runtime_protocol_versions": ["1.4"]}},
            {},
            frozenset(),
            "Pinned Agent publication does not support the required Runtime protocol",
            "agent_runtime_protocol_unsupported",
            id="runtime-protocol-unsupported",
        ),
        pytest.param(
            {"runtime_kind": "node-v1", "snapshot": {}},
            {},
            frozenset(),
            "Pinned Agent publication runtime is unsupported",
            "agent_runtime_kind_unsupported",
            id="runtime-kind-checked-before-protocol",
        ),
        pytest.param(
            {},
            {},
            frozenset({"ingress"}),
            "Source connector is not assigned to the Agent publication",
            "",
            id="source-connector-not-assigned",
        ),
        pytest.param(
            {},
            {},
            frozenset({"delivery"}),
            "Delivery connector is not assigned to the Agent publication",
            "",
            id="delivery-connector-not-assigned",
        ),
        pytest.param(
            {},
            {},
            frozenset({"ingress", "delivery"}),
            "Source connector is not assigned to the Agent publication",
            "",
            id="source-connector-checked-before-delivery",
        ),
    ),
)
def test_pinned_agent_publication_is_verified_before_the_turn_is_persisted(
    publication_overrides: dict[str, object],
    command_overrides: dict[str, object],
    denied_directions: frozenset[str],
    message: str,
    error_code: str,
) -> None:
    runtime = container()
    service = runtime.create_agent_job_service
    service.agent_config_service = _PinnedAgentConfig(  # type: ignore[assignment]
        publication=_pinned_publication(**publication_overrides),
        denied_directions=denied_directions,
    )

    _assert_rejected_without_persisting(
        runtime,
        lambda: service.execute(
            _command(fixed_agent_publication_id="agent-publication-pinned", **command_overrides)
        ),
        error_type=NonRetryableExecutionError,
        message=message,
        error_code=error_code,
        audit_events=PERMISSION_AUDITS,
    )


class _RecordingReadinessGuard:
    def __init__(self, error: AppError | None = None) -> None:
        self.error = error
        self.runtime_kinds: list[str] = []

    def require_ready(self, runtime_kind: str) -> None:
        self.runtime_kinds.append(runtime_kind)
        if self.error is not None:
            raise self.error


def test_runtime_readiness_guard_receives_the_publication_runtime_kind() -> None:
    runtime = container()
    guard = _RecordingReadinessGuard()
    runtime.create_agent_job_service.runtime_readiness_guard = guard  # type: ignore[assignment]

    job = runtime.create_agent_job_service.execute(_command())

    assert isinstance(job, AgentJob)
    assert job.agent_runtime_kind == "python-v1"
    assert guard.runtime_kinds == ["python-v1"]


def test_unready_runtime_blocks_the_turn_before_it_is_persisted() -> None:
    runtime = container()
    guard = _RecordingReadinessGuard(
        NonRetryableExecutionError(
            "Agent runtime is not ready",
            safe_message="Agent Runtime 尚未就绪",
            error_code="agent_runtime_not_ready",
        )
    )
    runtime.create_agent_job_service.runtime_readiness_guard = guard  # type: ignore[assignment]

    error = _assert_rejected_without_persisting(
        runtime,
        lambda: runtime.create_agent_job_service.execute(_command()),
        error_type=NonRetryableExecutionError,
        message="Agent runtime is not ready",
        error_code="agent_runtime_not_ready",
        audit_events=PERMISSION_AUDITS,
    )

    assert error is guard.error
    assert guard.runtime_kinds == ["python-v1"]


LIMITED_ATTACHMENTS = AttachmentSettings(
    enabled=True,
    max_count=2,
    max_file_bytes=100,
    max_message_bytes=150,
)


@pytest.mark.parametrize(
    ("command_overrides", "message", "safe_message"),
    (
        pytest.param(
            {"attachments": (_document(),), "attachments_enabled": False},
            "message_attachments_disabled",
            "此业务应用未启用附件",
            id="disabled-by-application",
        ),
        pytest.param(
            {"attachments": (_document(),)},
            "message_attachments_disabled",
            "此业务应用未启用附件",
            id="disabled-by-settings",
        ),
        pytest.param(
            {
                "attachments_enabled": True,
                "attachments": tuple(_document(f"资料-{index}.txt") for index in range(3)),
            },
            "attachment_count_exceeded",
            "附件数量过多",
            id="too-many-attachments",
        ),
        pytest.param(
            {
                "attachments_enabled": True,
                "attachments": (_document("a.exe"), _document("b.exe"), _document("c.exe")),
            },
            "attachment_count_exceeded",
            "附件数量过多",
            id="count-checked-before-type",
        ),
        pytest.param(
            {"attachments_enabled": True, "attachments": (_document("tool.exe"),)},
            "unsupported_attachment_type",
            "不支持此附件类型",
            id="unsupported-type",
        ),
        pytest.param(
            {"attachments_enabled": True, "attachments": (_document(credential=""),)},
            "attachment_source_missing",
            "缺少附件来源",
            id="source-missing",
        ),
        pytest.param(
            {"attachments_enabled": True, "attachments": (_document("图.png", size=101),)},
            "attachment_size_exceeded",
            "附件过大",
            id="binary-file-over-setting",
        ),
        pytest.param(
            {
                "attachments_enabled": True,
                "attachments": (_document("笔记.txt", size=15 * 1024 * 1024 + 1),),
            },
            "attachment_size_exceeded",
            "附件过大",
            id="text-file-over-fixed-limit",
        ),
        pytest.param(
            {
                "attachments_enabled": True,
                "attachments": (_document("笔记.txt", size=1024),),
            },
            "attachment_message_size_exceeded",
            "附件消息过大",
            id="text-file-counts-toward-message-limit",
        ),
        pytest.param(
            {
                "attachments_enabled": True,
                "attachments": (
                    _document("图-1.png", credential="download-1", size=80),
                    _document("图-2.png", credential="download-2", size=80),
                ),
            },
            "attachment_message_size_exceeded",
            "附件消息过大",
            id="message-total-over-setting",
        ),
    ),
)
def test_execute_validates_attachments_before_any_side_effect(
    command_overrides: dict[str, object],
    message: str,
    safe_message: str,
) -> None:
    runtime = container()
    runtime.create_agent_job_service.attachment_settings = (
        LIMITED_ATTACHMENTS
        if command_overrides.get("attachments_enabled")
        else AttachmentSettings(enabled=False)
    )

    error = _assert_rejected_without_persisting(
        runtime,
        lambda: runtime.create_agent_job_service.execute(_command(**command_overrides)),
        error_type=NonRetryableExecutionError,
        message=message,
        error_code="",
        audit_events=(),
    )

    assert error.safe_message == safe_message


@pytest.mark.parametrize(
    ("service_overrides", "command_overrides", "message", "error_code", "audit_events"),
    (
        pytest.param(
            {},
            {"user_message": "请分析"},
            "Attachment staging requires a file-only message",
            "attachment_stage_invalid",
            (),
            id="message-has-text",
        ),
        pytest.param(
            {},
            {"attachments": ()},
            "Attachment staging requires a file-only message",
            "attachment_stage_invalid",
            (),
            id="message-has-no-attachment",
        ),
        pytest.param(
            {},
            {"user_message": "请分析", "conversation_mode": "legacy"},
            "Attachment staging requires a file-only message",
            "attachment_stage_invalid",
            (),
            id="file-only-checked-before-session-mode",
        ),
        pytest.param(
            {},
            {"conversation_mode": "legacy"},
            "Attachment staging requires channel-isolated sessions",
            "attachment_stage_session_mode_invalid",
            (),
            id="session-not-channel-isolated",
        ),
        pytest.param(
            {},
            {"business_application_id": ""},
            "Attachment staging requires a frozen Business Application publication",
            "attachment_stage_publication_missing",
            (),
            id="application-missing",
        ),
        pytest.param(
            {},
            {"business_application_publication_id": ""},
            "Attachment staging requires a frozen Business Application publication",
            "attachment_stage_publication_missing",
            (),
            id="publication-missing",
        ),
        pytest.param(
            {},
            {"task_file_features": {"workspace_enabled": True}},
            "Attachment staging requires the governed workspace and File MCP",
            "attachment_stage_workspace_disabled",
            (),
            id="file-mcp-disabled",
        ),
        pytest.param(
            {},
            {"attachments": (_document("图.png"),)},
            "Attachment format is outside the frozen task-workspace policy",
            "file_workspace_type_unsupported",
            (),
            id="format-outside-workspace-policy",
        ),
        pytest.param(
            {},
            {"attachments_enabled": False},
            "message_attachments_disabled",
            "",
            (),
            id="attachments-disabled-by-application",
        ),
        pytest.param(
            {"attachment_settings": AttachmentSettings(enabled=False)},
            {"attachments_enabled": None},
            "message_attachments_disabled",
            "",
            (),
            id="attachments-disabled-by-settings",
        ),
        pytest.param(
            {"credential_cipher": None},
            {},
            "Attachment credential encryption is unavailable",
            "",
            (),
            id="attachment-cipher-missing",
        ),
        pytest.param(
            {"credential_cipher": None},
            {"continuous_conversation_enabled": False},
            "Attachment credential encryption is unavailable",
            "",
            (),
            id="attachment-cipher-checked-before-continuous-session",
        ),
        pytest.param(
            {},
            {"continuous_conversation_enabled": False},
            "Attachment staging requires continuous channel conversation",
            "attachment_stage_continuous_session_required",
            (),
            id="continuous-session-disabled-by-application",
        ),
        pytest.param(
            {"continuous_enabled": False},
            {"continuous_conversation_enabled": None},
            "Attachment staging requires continuous channel conversation",
            "attachment_stage_continuous_session_required",
            (),
            id="continuous-session-disabled-by-settings",
        ),
        pytest.param(
            {},
            {"external_conversation_id": ""},
            "Attachment staging session isolation facts are incomplete",
            "session_isolation_incomplete",
            CONNECTOR_AUDITS,
            id="conversation-missing",
        ),
        pytest.param(
            {"file_manifest_service": None},
            {},
            "Task file workspace service is unavailable",
            "file_workspace_unavailable",
            CONNECTOR_AUDITS,
            id="workspace-service-missing",
        ),
    ),
)
def test_stage_attachments_rejects_without_persisting_the_intake(
    service_overrides: dict[str, object],
    command_overrides: dict[str, object],
    message: str,
    error_code: str,
    audit_events: tuple[str, ...],
) -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    service = runtime.create_agent_job_service
    for name, value in service_overrides.items():
        setattr(service, name, value)

    _assert_rejected_without_persisting(
        runtime,
        lambda: service.stage_attachments(_application_command(runtime, **command_overrides)),
        error_type=NonRetryableExecutionError,
        message=message,
        error_code=error_code,
        audit_events=audit_events,
    )


def test_stage_attachments_rolls_back_the_session_when_no_workspace_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)
    manifest_service = runtime.create_agent_job_service.file_manifest_service
    assert manifest_service is not None
    monkeypatch.setattr(manifest_service, "resolve_workspace", lambda **_: None)

    error = _assert_rejected_without_persisting(
        runtime,
        lambda: runtime.create_agent_job_service.stage_attachments(_application_command(runtime)),
        error_type=NonRetryableExecutionError,
        message="Task file workspace could not be resolved for attachment intake",
        error_code="file_workspace_unavailable",
        audit_events=CONNECTOR_AUDITS,
    )

    assert error.safe_message == "无法创建任务文件工作区"


def test_stage_attachments_uses_the_command_project_when_the_routed_project_is_blank() -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)

    intake = runtime.create_agent_job_service.stage_attachments(
        _application_command(
            runtime,
            project_code="staging-project",
            routing_context={"project_code": ""},
        )
    )

    session = runtime.session_repository.get_session(intake.session_id)
    assert session.project_code == "staging-project"


def test_job_creation_audit_trail_order() -> None:
    runtime = multimodal_container(task_file_features={})

    job, events = audit_trail(
        runtime,
        lambda: runtime.create_agent_job_service.execute(
            _application_command(
                runtime,
                idempotency_key="creation-contract-audit",
                user_message="检查订单状态",
                attachments=(),
                task_file_features={},
            )
        ),
    )

    assert isinstance(job, AgentJob)
    assert tuple(events) == (*APPLICATION_AUDITS, "job.created", "job.dispatch.enqueued")


def test_attachment_staging_audit_trail_order() -> None:
    runtime = multimodal_container(task_file_features=FILE_FEATURES)

    intake, events = audit_trail(
        runtime,
        lambda: runtime.create_agent_job_service.stage_attachments(_application_command(runtime)),
    )

    assert isinstance(intake, StagedAttachmentIntake)
    assert len(intake.attachment_ids) == 1
    assert tuple(events) == (*CONNECTOR_AUDITS, "attachment.intake.staged")
