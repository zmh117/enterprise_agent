from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.bootstrap import build_test_container
from app.modules.managed_channel.api.controller import (
    DingTalkEnterpriseRenameRequest,
)
from app.modules.managed_channel.domain import (
    ChannelIngressSubmission,
    DingTalkApplicationInput,
)
from app.shared.config import Settings
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import grant_test_application_access
from backend.tests.test_business_application_control_plane import control_plane_settings


NOW = "2026-08-03T00:00:00+00:00"


def _container():
    value = build_test_container(
        Settings(
            database_dsn="sqlite:///:memory:",
            app_config_master_key="dingtalk-enterprise-test-key",
        ),
        migrate=True,
    )
    value.database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('enterprise-admin', 'enterprise-admin', 'Enterprise Admin',
                'enabled', ?, ?)
        """,
        (NOW, NOW),
    )
    return value


def _pending_connection(container, *, name: str, client_id: str):
    enterprise = container.managed_channel_service.create_dingtalk_enterprise(
        name=name,
        actor_id="enterprise-admin",
    )
    channel = container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name=f"{name}应用",
            client_id=client_id,
            client_secret=f"secret-{client_id}",
            dingtalk_enterprise_id=enterprise["id"],
        ),
        actor_id="enterprise-admin",
        enabled=True,
    )
    return enterprise, channel


def _submission(
    connector_id: str,
    event_id: str,
    *,
    sender_corp_id: str = "corp-a",
    chatbot_corp_id: str = "corp-a",
    sender_id: str = "staff-a",
    sender_name: str = "测试用户",
    robot_code: str = "robot-enterprise",
) -> ChannelIngressSubmission:
    return ChannelIngressSubmission(
        connector_id=connector_id,
        external_event_id=event_id,
        correlation_id=f"correlation-{event_id}",
        normalized_event={
            "msgId": event_id,
            "senderStaffId": sender_id,
            "senderNick": sender_name,
            "senderCorpId": sender_corp_id,
            "chatbotCorpId": chatbot_corp_id,
            "conversationType": "1",
            "conversationId": "conversation-a",
            "robotCode": robot_code,
            "msgtype": "text",
            "sessionWebhook": (
                "https://oapi.dingtalk.com/robot/sendBySession/fixture-enterprise-e2e"
            ),
            "sessionWebhookExpiredTime": "1893456000000",
            "text": {"content": "verification content must not persist"},
        },
        safe_summary={"msgtype": "text"},
        payload_hash=f"hash-{event_id}",
        request_bytes=256,
    )


def _dispatch(container, *, connector_id: str, submission: ChannelIngressSubmission):
    lease = container.runtime_control_service.acquire("runtime-enterprise-e2e")
    if lease is None:
        lease = container.database.execute_one(
            """
            select lease_token
              from channel_runtime_lease
             where lease_name = 'dingtalk-stream-runtime-singleton'
            """
        )
    assert lease is not None
    event, _created = container.runtime_control_service.receive(
        "runtime-enterprise-e2e",
        str(lease["lease_token"]),
        submission,
    )
    container.channel_outbox_publisher.publish_pending(limit=10)
    assert container.message_bus is not None
    container.message_bus.consume_channel_events(container.channel_dispatch_service.handle)
    return container.managed_channel_repository.get_event(str(event["id"]))


def _activate_application(
    container,
    *,
    code: str,
    connector_id: str,
    robot_code: str,
    user_id: str,
):
    for direction in ("ingress", "delivery"):
        container.database.execute(
            """
            insert into agent_channel_binding
              (id, publication_id, direction, connector_id, config_json, created_at)
            values (?, 'agent_publication_default_v1', ?, ?, '{}', ?)
            """,
            (
                f"binding-enterprise-e2e-{direction}-{connector_id}",
                direction,
                connector_id,
                NOW,
            ),
        )
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code=code,
        name=f"{code} 应用",
        description="钉钉企业与身份端到端测试",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    grant_test_application_access(
        container,
        application_id=str(application["id"]),
        role_code=f"{code}-access",
        user_id=user_id,
    )
    revision = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": "agent_publication_default_v1",
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 30,
                "continuous_conversation_enabled": False,
                "attachments_enabled": False,
            },
            "execution_policy": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "triggers": [
                {
                    "trigger_type": "dingtalk_private",
                    "connector_id": connector_id,
                    "routing_key": f"bot:{robot_code}",
                    "actor_policy": "CURRENT_SENDER",
                    "service_account_user_id": "",
                    "enabled": True,
                    "config": {
                        "conversation_type": "private",
                        "require_mention": False,
                        "webhook_definition_id": "",
                    },
                }
            ],
            "deliveries": [
                {
                    "delivery_type": "reply_original",
                    "connector_id": connector_id,
                    "enabled": True,
                    "config": {
                        "target_reference": "",
                        "reply_mode": "original",
                    },
                }
            ],
            "capabilities": [],
        },
    )
    publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    container.business_application_service.activate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    return application


def test_pending_enterprise_message_verifies_once_without_business_records() -> None:
    container = _container()
    enterprise, channel = _pending_connection(
        container,
        name="待验证企业",
        client_id="ding-pending",
    )
    lease = container.runtime_control_service.acquire("runtime-enterprise")
    assert lease is not None

    event, created = container.runtime_control_service.receive(
        "runtime-enterprise",
        lease["lease_token"],
        _submission(channel["id"], "verification-event"),
    )
    repeated, repeated_created = container.runtime_control_service.receive(
        "runtime-enterprise",
        lease["lease_token"],
        _submission(channel["id"], "verification-event"),
    )

    current = container.managed_channel_service.get_dingtalk_enterprise(enterprise["id"])
    assert event["status"] == "ENTERPRISE_VERIFIED"
    assert created is True
    assert repeated == event
    assert repeated_created is False
    assert current["status"] == "ACTIVE"
    assert current["corp_id"] == "corp-a"
    assert current["verified_at"]
    assert container.database.execute_one(
        "select count(*) as count from channel_ingress_event"
    ) == {"count": 0}
    assert container.database.execute_one(
        "select count(*) as count from channel_ingress_outbox"
    ) == {"count": 0}
    assert container.database.execute_one(
        "select count(*) as count from dingtalk_identity_candidate"
    ) == {"count": 0}
    assert "verification content must not persist" not in str(
        container.database.execute("select * from audit_event")
    )


@pytest.mark.parametrize(
    ("sender", "chatbot", "error_code"),
    [
        ("", "corp-a", "dingtalk_corp_id_invalid"),
        ("corp-a", "", "dingtalk_corp_id_invalid"),
        ("corp-a", "corp-b", "dingtalk_corp_id_mismatch"),
    ],
)
def test_pending_enterprise_rejects_missing_or_mismatched_corp_ids(
    sender: str,
    chatbot: str,
    error_code: str,
) -> None:
    container = _container()
    enterprise, channel = _pending_connection(
        container,
        name="不匹配企业",
        client_id="ding-mismatch",
    )
    lease = container.runtime_control_service.acquire("runtime-enterprise")
    assert lease is not None

    with pytest.raises(NonRetryableExecutionError) as error:
        container.runtime_control_service.receive(
            "runtime-enterprise",
            lease["lease_token"],
            _submission(
                channel["id"],
                "mismatch-event",
                sender_corp_id=sender,
                chatbot_corp_id=chatbot,
            ),
        )

    assert error.value.error_code == error_code
    assert (
        container.managed_channel_service.get_dingtalk_enterprise(enterprise["id"])["status"]
        == "PENDING_VERIFICATION"
    )
    assert container.database.execute_one(
        "select count(*) as count from channel_ingress_event"
    ) == {"count": 0}


def test_enterprise_lifecycle_requires_disabled_apps_and_restore_reverification() -> None:
    container = _container()
    enterprise, channel = _pending_connection(
        container,
        name="生命周期企业",
        client_id="ding-lifecycle",
    )
    lease = container.runtime_control_service.acquire("runtime-enterprise")
    assert lease is not None
    container.runtime_control_service.receive(
        "runtime-enterprise",
        lease["lease_token"],
        _submission(channel["id"], "lifecycle-verification"),
    )
    active = container.managed_channel_service.get_dingtalk_enterprise(enterprise["id"])
    renamed = container.managed_channel_service.rename_dingtalk_enterprise(
        enterprise["id"],
        name="生命周期企业（已改名）",
        expected_revision=active["revision"],
        actor_id="enterprise-admin",
    )
    disabled = container.managed_channel_service.disable_dingtalk_enterprise(
        enterprise["id"],
        expected_revision=renamed["revision"],
        actor_id="enterprise-admin",
    )
    with pytest.raises(NonRetryableExecutionError) as enabled_apps:
        container.managed_channel_service.archive_dingtalk_enterprise(
            enterprise["id"],
            expected_revision=disabled["revision"],
            actor_id="enterprise-admin",
        )
    assert enabled_apps.value.error_code == "dingtalk_enterprise_connectors_enabled"

    disabled_channel = container.managed_channel_service.set_enabled(
        channel["id"],
        enabled=False,
        expected_revision=channel["revision"],
        actor_id="enterprise-admin",
    )
    assert disabled_channel["enabled"] is False
    archived = container.managed_channel_service.archive_dingtalk_enterprise(
        enterprise["id"],
        expected_revision=disabled["revision"],
        actor_id="enterprise-admin",
    )
    restored = container.managed_channel_service.restore_dingtalk_enterprise(
        enterprise["id"],
        expected_revision=archived["revision"],
        actor_id="enterprise-admin",
    )
    assert restored["status"] == "PENDING_VERIFICATION"
    assert restored["corp_id"] == "corp-a"
    assert restored["verified_at"] is None


def test_enterprise_and_connection_contracts_hide_corp_mutation_and_secrets() -> None:
    container = _container()
    enterprise, channel = _pending_connection(
        container,
        name="响应边界企业",
        client_id="ding-contract",
    )

    with pytest.raises(ValidationError):
        DingTalkEnterpriseRenameRequest.model_validate(
            {
                "name": "伪造企业",
                "expected_revision": 1,
                "corp_id": "forged-corp-id",
            }
        )

    response_text = str(
        {
            "enterprise": container.managed_channel_service.get_dingtalk_enterprise(
                enterprise["id"]
            ),
            "channel": channel,
        }
    )
    assert "secret-ding-contract" not in response_text
    assert "secret_ref" not in response_text
    assert "client_secret" not in response_text
    assert "verification_event_id" not in response_text


def test_enterprise_verification_binding_and_two_application_jobs_end_to_end() -> None:
    base = control_plane_settings()
    settings = replace(
        base,
        database_dsn="sqlite:///:memory:",
        app_config_master_key="dingtalk-enterprise-e2e-test-key",
        identity=replace(
            base.identity,
            published_agent_runtime_enabled=True,
        ),
    )
    container = build_test_container(settings, migrate=True, seed=True)
    enterprise = container.managed_channel_service.create_dingtalk_enterprise(
        name="端到端企业",
        actor_id="user_local_admin",
    )
    first = container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="端到端应用一",
            client_id="dingtalk-enterprise-e2e-first",
            client_secret="fixture-e2e-first-secret",
            dingtalk_enterprise_id=str(enterprise["id"]),
        ),
        actor_id="user_local_admin",
        enabled=True,
    )
    lease = container.runtime_control_service.acquire("runtime-enterprise-e2e")
    assert lease is not None

    verification, created = container.runtime_control_service.receive(
        "runtime-enterprise-e2e",
        str(lease["lease_token"]),
        _submission(
            str(first["id"]),
            "enterprise-e2e-verification",
            sender_corp_id="corp-enterprise-e2e",
            chatbot_corp_id="corp-enterprise-e2e",
        ),
    )

    assert created is True
    assert verification["status"] == "ENTERPRISE_VERIFIED"
    assert (
        container.managed_channel_service.get_dingtalk_enterprise(str(enterprise["id"]))["corp_id"]
        == "corp-enterprise-e2e"
    )
    assert container.agent_repository.count_rows("agent_job") == 0

    target = container.identity_repository.create_user(
        username="enterprise-e2e-user",
        display_name="端到端人员",
    )
    first_application = _activate_application(
        container,
        code="enterprise-e2e-first",
        connector_id=str(first["id"]),
        robot_code="robot-enterprise-e2e-first",
        user_id=str(target["id"]),
    )
    rejected = _dispatch(
        container,
        connector_id=str(first["id"]),
        submission=_submission(
            str(first["id"]),
            "enterprise-e2e-candidate",
            sender_corp_id="corp-enterprise-e2e",
            chatbot_corp_id="corp-enterprise-e2e",
            sender_id="staff-enterprise-e2e",
            sender_name="首次观察昵称",
            robot_code="robot-enterprise-e2e-first",
        ),
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["error_code"] == "identity_not_bound"
    assert container.agent_repository.count_rows("agent_job") == 0
    candidate = container.database.execute_one(
        """
        select id, revision
          from dingtalk_identity_candidate
         where dingtalk_enterprise_id = ? and external_subject_id = ?
        """,
        (enterprise["id"], "staff-enterprise-e2e"),
    )
    assert candidate is not None

    bound = container.identity_discovery_service.bind_candidate(
        actor_id="user_local_admin",
        candidate_id=str(candidate["id"]),
        target_user_id=str(target["id"]),
        expected_candidate_revision=int(candidate["revision"]),
        expected_user_revision=int(target["revision"]),
        bind_without_access_confirmed=True,
    )
    identity = bound["identity"]
    assert identity["connector_id"] == ""
    assert identity["dingtalk_enterprise_id"] == enterprise["id"]

    first_accepted = _dispatch(
        container,
        connector_id=str(first["id"]),
        submission=_submission(
            str(first["id"]),
            "enterprise-e2e-first-job",
            sender_corp_id="corp-enterprise-e2e",
            chatbot_corp_id="corp-enterprise-e2e",
            sender_id="staff-enterprise-e2e",
            sender_name="应用一昵称",
            robot_code="robot-enterprise-e2e-first",
        ),
    )
    assert first_accepted["job_id"], (
        first_accepted["status"],
        first_accepted["error_code"],
        first_accepted["error_summary"],
    )
    first_job = container.agent_repository.get_job(str(first_accepted["job_id"]))
    assert first_job.business_application_id == first_application["id"]
    assert first_job.source_connector_id == first["id"]

    second = container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="端到端应用二",
            client_id="dingtalk-enterprise-e2e-second",
            client_secret="fixture-e2e-second-secret",
            dingtalk_enterprise_id=str(enterprise["id"]),
        ),
        actor_id="user_local_admin",
        enabled=True,
    )
    second_application = _activate_application(
        container,
        code="enterprise-e2e-second",
        connector_id=str(second["id"]),
        robot_code="robot-enterprise-e2e-second",
        user_id=str(target["id"]),
    )
    second_accepted = _dispatch(
        container,
        connector_id=str(second["id"]),
        submission=_submission(
            str(second["id"]),
            "enterprise-e2e-second-job",
            sender_corp_id="corp-enterprise-e2e",
            chatbot_corp_id="corp-enterprise-e2e",
            sender_id="staff-enterprise-e2e",
            sender_name="应用二昵称",
            robot_code="robot-enterprise-e2e-second",
        ),
    )
    assert second_accepted["job_id"]
    second_job = container.agent_repository.get_job(str(second_accepted["job_id"]))
    assert second_job.internal_user_id == target["id"]
    assert second_job.external_identity_id == identity["id"]
    assert second_job.business_application_id == second_application["id"]
    assert second_job.source_connector_id == second["id"]

    observations = container.identity_repository.list_dingtalk_application_observations(
        str(identity["id"])
    )
    assert {item["application_name"] for item in observations} == {
        "端到端应用一",
        "端到端应用二",
    }
    observation_rows = container.database.execute(
        """
        select connector_id
          from dingtalk_identity_application_observation
         where external_identity_id = ?
        """,
        (identity["id"],),
    )
    assert {item["connector_id"] for item in observation_rows} == {
        first["id"],
        second["id"],
    }
    assert (
        container.identity_repository.get_external_identity(str(identity["id"]))["display_name"]
        == "应用二昵称"
    )


def test_verified_corp_id_conflict_is_rejected_for_second_enterprise() -> None:
    container = _container()
    _, first = _pending_connection(
        container,
        name="企业一",
        client_id="ding-first-enterprise",
    )
    second_enterprise, second = _pending_connection(
        container,
        name="企业二",
        client_id="ding-second-enterprise",
    )
    lease = container.runtime_control_service.acquire("runtime-enterprise")
    assert lease is not None
    container.runtime_control_service.receive(
        "runtime-enterprise",
        lease["lease_token"],
        _submission(first["id"], "verify-first"),
    )

    with pytest.raises(NonRetryableExecutionError) as conflict:
        container.runtime_control_service.receive(
            "runtime-enterprise",
            lease["lease_token"],
            _submission(second["id"], "verify-second"),
        )
    assert conflict.value.error_code == "dingtalk_corp_id_conflict"
    assert (
        container.managed_channel_service.get_dingtalk_enterprise(second_enterprise["id"])["status"]
        == "PENDING_VERIFICATION"
    )
