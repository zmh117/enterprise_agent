from __future__ import annotations

import json

import pytest

from app.modules.api_capability.infrastructure import (
    GovernedApiExecutionRepository,
)
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.shared.exceptions import (
    NonRetryableExecutionError,
    NotFound,
)
from backend.tests.test_api_capability_publication_composition import (
    _container,
    _publish_agent,
    _release,
)
from backend.tests.test_business_application_control_plane import (
    draft_payload,
)
from backend.tests.test_governed_api_capability_repositories import (
    ACTOR_ID,
)


def _publish_application(
    container,
    *,
    agent_publication: dict[str, object],
    release_ids: list[str],
    code: str,
) -> tuple[dict[str, object], dict[str, object]]:
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code=code,
        name=code,
        description="DingTalk governed API test",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["agent_publication_id"] = agent_publication["id"]
    payload["api_capability_release_ids"] = release_ids
    revision = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    return application, publication


def _command(
    *,
    application: dict[str, object],
    application_publication: dict[str, object],
    agent_publication: dict[str, object],
    suffix: str,
    conversation_type: str = "direct",
) -> CreateAgentJobCommand:
    return CreateAgentJobCommand(
        idempotency_key=f"governed-dingtalk-{suffix}",
        requester_id=ACTOR_ID,
        requester_display_name="Composition Admin",
        external_conversation_id=f"conversation-{suffix}",
        user_message="查询 ONES 工作项",
        source_channel="dingding_stream",
        source_connector_id="connector-dingtalk-stream-default",
        external_event_id=f"event-{suffix}",
        routing_context={"project_code": "default"},
        reply_route={"type": "none"},
        conversation_type=conversation_type,
        agent_code="default-diagnostic-agent",
        fixed_agent_publication_id=str(agent_publication["id"]),
        fixed_agent_revision=int(agent_publication["revision"]),
        fixed_agent_config_hash=str(agent_publication["config_hash"]),
        business_application_id=str(application["id"]),
        business_application_code=str(application["code"]),
        business_application_publication_id=str(application_publication["id"]),
        business_application_config_hash=str(application_publication["config_hash"]),
        business_application_runtime_status="wired",
        conversation_mode="channel",
        session_policy={
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
        },
    )


@pytest.mark.parametrize("conversation_type", ["direct", "group"])
def test_dingtalk_active_route_needs_no_application_role_and_freezes_subject(
    conversation_type: str,
) -> None:
    container = _container()
    try:
        _repository, release = _release(container)
        agent_publication = _publish_agent(
            container,
            str(release["id"]),
        )
        application, publication = _publish_application(
            container,
            agent_publication=agent_publication,
            release_ids=[str(release["id"])],
            code="dingtalk-ones-app",
        )
        assert (
            container.create_agent_job_service.business_authorization_service.repository.business_access_for_user(
                user_id=ACTOR_ID,
                application_id=str(application["id"]),
            )
            == []
        )

        job = container.create_agent_job_service.execute(
            _command(
                application=application,
                application_publication=publication,
                agent_publication=agent_publication,
                suffix=f"subject-{conversation_type}",
                conversation_type=conversation_type,
            )
        )
        subject = GovernedApiExecutionRepository(container.database).get_external_subject(job.id)
        assert subject["external_user_id"] == "ones-user-admin"
        assert subject["default_team_id"] == "team-b"
        assert "token" not in json.dumps(subject).lower()

        published = container.job_dispatcher.publish_pending()
        assert published.published == 1
        queued = container.message_bus.jobs[-1]
        assert set(vars(queued)) == {
            "event_id",
            "job_id",
            "correlation_id",
        }
    finally:
        container.database.close()


def test_ones_unavailability_does_not_block_dingtalk_application_access() -> None:
    container = _container()
    try:
        _repository, release = _release(container)
        agent_publication = _publish_agent(
            container,
            str(release["id"]),
        )
        application, publication = _publish_application(
            container,
            agent_publication=agent_publication,
            release_ids=[str(release["id"])],
            code="dingtalk-no-ones-app",
        )
        container.database.execute(
            """
            update external_api_credential
               set status = 'DISABLED'
             where user_id = ?
            """,
            (ACTOR_ID,),
        )
        job = container.create_agent_job_service.execute(
            _command(
                application=application,
                application_publication=publication,
                agent_publication=agent_publication,
                suffix="no-credential",
            )
        )
        assert job.id
        with pytest.raises(NotFound) as raised:
            GovernedApiExecutionRepository(container.database).get_external_subject(job.id)
        assert raised.value.error_code == "job_external_subject_snapshot_missing"
        context = container.agent_executor.context_builder.build(job)
        assert context.governed_capabilities == ()
        assert len(context.governed_capability_notices) == 1
        notice = context.governed_capability_notices[0]
        assert notice.identifier == "cap__ones__work_item__search"
        assert notice.status == "unavailable"
        assert notice.reason_code == "current_sender_ones_setup_required"
        assert "我的外部身份" in notice.message
        assert "重新发送请求" in notice.message
        serialized_notice = json.dumps(
            notice.to_prompt_payload(),
            ensure_ascii=False,
        )
        assert ACTOR_ID not in serialized_notice
        assert "ones-user-admin" not in serialized_notice
        assert "team-b" not in serialized_notice
        assert str(release["id"]) not in serialized_notice
        assert str(release["connection_revision_id"]) not in serialized_notice
    finally:
        container.database.close()


def test_job_subject_does_not_drift_when_default_team_changes() -> None:
    container = _container()
    try:
        _repository, release = _release(container)
        agent_publication = _publish_agent(
            container,
            str(release["id"]),
        )
        application, publication = _publish_application(
            container,
            agent_publication=agent_publication,
            release_ids=[str(release["id"])],
            code="dingtalk-team-snapshot-app",
        )
        job = container.create_agent_job_service.execute(
            _command(
                application=application,
                application_publication=publication,
                agent_publication=agent_publication,
                suffix="team-change",
            )
        )
        execution_repository = GovernedApiExecutionRepository(container.database)
        before = execution_repository.get_external_subject(job.id)
        identity = container.identity_repository.get_external_identity(
            str(before["external_identity_id"])
        )
        container.database.execute(
            """
            update user_external_identity
               set metadata_json = ?, revision = revision + 1
             where id = ?
            """,
            (
                json.dumps(
                    {
                        "team_uuids": ["team-a", "team-b"],
                        "default_team_id": "team-a",
                    }
                ),
                identity["id"],
            ),
        )
        after = execution_repository.get_external_subject(job.id)
        assert after["snapshot_hash"] == before["snapshot_hash"]
        assert after["default_team_id"] == "team-b"
        with pytest.raises(
            NonRetryableExecutionError,
            match="differs from Job snapshot",
        ):
            container.governed_api_runtime_executor._current_subject_and_token(
                job_id=job.id,
                user_id=ACTOR_ID,
                connection_revision_id=str(release["connection_revision_id"]),
            )
    finally:
        container.database.close()


def test_agent_context_catalog_is_exact_and_provider_scoped() -> None:
    container = _container()
    try:
        repository, release = _release(container)
        agent_publication = _publish_agent(
            container,
            str(release["id"]),
        )
        application, publication = _publish_application(
            container,
            agent_publication=agent_publication,
            release_ids=[str(release["id"])],
            code="dingtalk-context-catalog-app",
        )
        job = container.create_agent_job_service.execute(
            _command(
                application=application,
                application_publication=publication,
                agent_publication=agent_publication,
                suffix="context-catalog",
            )
        )
        context = container.agent_executor.context_builder.build(job)
        assert len(context.governed_capabilities) == 1
        tool = context.governed_capabilities[0]
        assert tool["identifier"] == "cap__ones__work_item__search"
        assert tool["release_id"] == release["id"]
        assert tool["description"] == ("Search ONES work items for the current user.")
        assert "release_note" not in tool
        assert "token" not in json.dumps(tool).lower()
        assert context.governed_capability_notices == ()

        unselected_application, unselected_publication = _publish_application(
            container,
            agent_publication=agent_publication,
            release_ids=[],
            code="dingtalk-context-no-capability-app",
        )
        unselected_job = container.create_agent_job_service.execute(
            _command(
                application=unselected_application,
                application_publication=unselected_publication,
                agent_publication=agent_publication,
                suffix="context-no-capability",
            )
        )
        unselected_context = container.agent_executor.context_builder.build(unselected_job)
        assert unselected_context.governed_capabilities == ()
        assert unselected_context.governed_capability_notices == ()

        repository.set_release_status(
            str(release["id"]),
            status="DISABLED",
            actor_id=ACTOR_ID,
            reason="Emergency stop",
        )
        disabled_context = container.agent_executor.context_builder.build(job)
        assert disabled_context.governed_capabilities == ()
        assert disabled_context.governed_capability_notices == ()
    finally:
        container.database.close()
