from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.bootstrap import build_test_container
from app.modules.managed_channel.domain import (
    ChannelIngressSubmission,
    DingTalkApplicationInput,
)
from app.modules.identity_discovery.domain import DingTalkIdentityObservation
from app.shared.config import IdentitySettings, Settings


@pytest.fixture
def discovery_container():
    settings = Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="identity-discovery-test-key",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=False,
            cookie_secure=False,
            dingtalk_tenant_code="tenant-discovery",
        ),
    )
    container = build_test_container(settings, migrate=True)
    timestamp = "2026-08-03T00:00:00+00:00"
    container.database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('fixture-admin', 'fixture-admin', 'Fixture Admin',
                'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    enterprise = container.managed_channel_service.create_dingtalk_enterprise(
        name="身份发现测试企业",
        actor_id="fixture-admin",
    )
    container.database.execute(
        """
        update dingtalk_enterprise
           set corp_id = 'corp-discovery', status = 'ACTIVE', verified_at = ?,
               verification_event_id = 'fixture-verification'
         where id = ?
        """,
        (timestamp, enterprise["id"]),
    )
    container._test_dingtalk_enterprise_id = enterprise["id"]
    return container


@pytest.fixture
def dingtalk_connector(discovery_container):
    return discovery_container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="身份发现测试机器人",
            client_id="identity-discovery-client",
            client_secret="fixture-only-secret",
            dingtalk_enterprise_id=discovery_container._test_dingtalk_enterprise_id,
        ),
        actor_id="fixture-admin",
        enabled=True,
    )


def _submission(
    connector_id: str,
    event_id: str,
    *,
    sender_id: str = "staff-unbound",
    sender_name: str = "待绑定用户",
    conversation_type: str = "1",
    conversation_id: str = "private-conversation",
    robot_code: str = "robot-discovery",
    create_at: object = 1_785_024_000_000,
    text: str = "请帮我查看系统状态",
    corp_id: str = "corp-discovery",
    extra: dict[str, Any] | None = None,
) -> ChannelIngressSubmission:
    normalized_event: dict[str, Any] = {
        "conversationId": conversation_id,
        "conversationType": conversation_type,
        "senderStaffId": sender_id,
        "senderNick": sender_name,
        "senderCorpId": corp_id,
        "chatbotCorpId": corp_id,
        "msgId": event_id,
        "robotCode": robot_code,
        "createAt": create_at,
        "msgtype": "text",
        "text": {"content": text},
    }
    normalized_event.update(extra or {})
    return ChannelIngressSubmission(
        connector_id=connector_id,
        external_event_id=event_id,
        correlation_id=f"correlation-{event_id}",
        normalized_event=normalized_event,
        safe_summary={"msgtype": str(normalized_event.get("msgtype") or "")},
        payload_hash=f"fixture-hash-{event_id}",
        request_bytes=512,
    )


def _dispatch(discovery_container, connector_id: str, submission: ChannelIngressSubmission):
    lease = discovery_container.runtime_control_service.acquire("runtime-discovery")
    if lease is None:
        current = discovery_container.database.execute_one(
            "select lease_token from channel_runtime_lease where lease_name = ?",
            ("dingtalk-stream-runtime-singleton",),
        )
        assert current is not None
        lease_token = str(current["lease_token"])
    else:
        lease_token = str(lease["lease_token"])
    event, _created = discovery_container.runtime_control_service.receive(
        "runtime-discovery",
        lease_token,
        submission,
    )
    discovery_container.channel_outbox_publisher.publish_pending(limit=10)
    assert discovery_container.message_bus is not None
    discovery_container.message_bus.consume_channel_events(
        discovery_container.channel_dispatch_service.handle
    )
    return discovery_container.managed_channel_repository.get_event(str(event["id"]))


def _bind_dingtalk_fixture(
    container,
    *,
    user_id: str,
    external_subject_id: str,
    display_name: str,
):
    identity = container.identity_repository.bind_external_identity(
        user_id=user_id,
        provider="dingtalk",
        tenant_code=str(container._test_dingtalk_enterprise_id),
        external_subject_id=external_subject_id,
        connector_id="",
        display_name=display_name,
    )
    container.database.execute(
        """
        update user_external_identity
           set dingtalk_enterprise_id = ?, connector_id = ''
         where id = ?
        """,
        (container._test_dingtalk_enterprise_id, identity["id"]),
    )
    return container.identity_repository.get_external_identity(str(identity["id"]))


@pytest.mark.parametrize("historical_state", ["never_bound", "disabled", "unbound"])
def test_identity_rejection_creates_candidate_without_agent_job(
    discovery_container,
    dingtalk_connector,
    historical_state: str,
):
    sender_id = f"staff-{historical_state}"
    if historical_state != "never_bound":
        user = discovery_container.identity_repository.create_user(
            username=f"user-{historical_state}",
            display_name=f"历史人员 {historical_state}",
        )
        identity = _bind_dingtalk_fixture(
            discovery_container,
            user_id=str(user["id"]),
            external_subject_id=sender_id,
            display_name="历史钉钉用户",
        )
        if historical_state == "disabled":
            discovery_container.identity_repository.set_external_identity_status(
                str(identity["id"]),
                status="disabled",
                expected_revision=int(identity["revision"]),
            )
        else:
            discovery_container.identity_repository.unbind_external_identity(
                str(identity["id"]),
                expected_revision=int(identity["revision"]),
            )

    event = _dispatch(
        discovery_container,
        str(dingtalk_connector["id"]),
        _submission(
            str(dingtalk_connector["id"]),
            f"event-{historical_state}",
            sender_id=sender_id,
        ),
    )

    assert event["status"] == "REJECTED"
    assert event["error_code"] in {
        "identity_not_bound",
        "identity_inactive",
    }
    candidate = discovery_container.database.execute_one(
        """
        select dingtalk_enterprise_id, external_subject_id
        from dingtalk_identity_candidate
        where dingtalk_enterprise_id = ? and external_subject_id = ?
        """,
        (discovery_container._test_dingtalk_enterprise_id, sender_id),
    )
    assert candidate is not None
    assert (
        discovery_container.database.execute_one(
            "select count(*) as count from agent_job"
        )
        or {}
    ).get("count") == 0
    assert discovery_container.message_bus is not None
    assert not discovery_container.message_bus.jobs


def test_disabled_user_creates_restore_candidate(discovery_container, dingtalk_connector):
    user = discovery_container.identity_repository.create_user(
        username="disabled-owner",
        display_name="已停用原人员",
    )
    _bind_dingtalk_fixture(
        discovery_container,
        user_id=str(user["id"]),
        external_subject_id="staff-disabled-owner",
        display_name="已停用原人员",
    )
    discovery_container.identity_repository.update_user(
        str(user["id"]),
        expected_revision=int(user["revision"]),
        display_name=str(user["display_name"]),
        email="",
        status="disabled",
    )

    event = _dispatch(
        discovery_container,
        str(dingtalk_connector["id"]),
        _submission(
            str(dingtalk_connector["id"]),
            "event-disabled-owner",
            sender_id="staff-disabled-owner",
        ),
    )

    assert event["error_code"] == "identity_user_inactive"
    candidate = discovery_container.database.execute_one(
        """
        select id from dingtalk_identity_candidate
        where external_subject_id = ?
        """,
        ("staff-disabled-owner",),
    )
    assert candidate is not None
    assert (
        discovery_container.database.execute_one(
            "select count(*) as count from agent_job"
        )
        or {}
    ).get("count") == 0


def test_enabled_bound_identity_is_not_discovered(discovery_container, dingtalk_connector):
    user = discovery_container.identity_repository.create_user(
        username="enabled-owner",
        display_name="已绑定人员",
    )
    _bind_dingtalk_fixture(
        discovery_container,
        user_id=str(user["id"]),
        external_subject_id="staff-enabled-owner",
        display_name="已绑定人员",
    )

    event = _dispatch(
        discovery_container,
        str(dingtalk_connector["id"]),
        _submission(
            str(dingtalk_connector["id"]),
            "event-enabled-owner",
            sender_id="staff-enabled-owner",
        ),
    )

    assert event["status"] == "REJECTED"
    assert event["error_code"] not in {
        "identity_not_bound",
        "identity_inactive",
        "identity_user_inactive",
    }
    assert (
        discovery_container.database.execute_one(
            """
            select count(*) as count
            from dingtalk_identity_candidate
            where external_subject_id = ?
            """,
            ("staff-enabled-owner",),
        )
        or {}
    ).get("count") == 0


def test_discovery_fixture_covers_private_group_duplicate_truncation_and_attachment(
    discovery_container,
    dingtalk_connector,
):
    connector_id = str(dingtalk_connector["id"])
    second_connector = discovery_container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="同企业第二个机器人",
            client_id="identity-discovery-client-second",
            client_secret="fixture-only-secret-second",
            dingtalk_enterprise_id=discovery_container._test_dingtalk_enterprise_id,
        ),
        actor_id="fixture-admin",
        enabled=True,
    )
    private = _submission(
        connector_id,
        "event-private",
        sender_id="staff-aggregate",
        conversation_type="1",
        conversation_id="private-aggregate",
        text="私聊消息",
    )
    group = _submission(
        connector_id,
        "event-group",
        sender_id="staff-aggregate",
        conversation_type="2",
        conversation_id="group-aggregate",
        robot_code="robot-group",
        create_at="not-a-time",
        text="群聊消息",
    )
    truncated = _submission(
        connector_id,
        "event-long",
        sender_id="staff-aggregate",
        text="测" * 1_200,
    )
    attachment = _submission(
        connector_id,
        "event-file",
        sender_id="staff-aggregate",
        text="",
        extra={
            "msgtype": "file",
            "text": {},
            "content": {
                "downloadCode": "fixture-download-code",
                "fileName": "排查资料.txt",
                "fileSize": 128,
            },
        },
    )
    second_robot = _submission(
        str(second_connector["id"]),
        "event-second-robot",
        sender_id="staff-aggregate",
        conversation_type="2",
        conversation_id="group-second-robot",
        robot_code="robot-second",
        text="第二个机器人收到的消息",
    )

    for submission in (private, group, truncated, attachment):
        _dispatch(discovery_container, connector_id, submission)
    _dispatch(
        discovery_container,
        str(second_connector["id"]),
        second_robot,
    )
    duplicate = replace(group, correlation_id="correlation-duplicate")
    duplicate_event = _dispatch(discovery_container, connector_id, duplicate)

    candidate = discovery_container.database.execute_one(
        """
        select id, observation_count
        from dingtalk_identity_candidate
        where dingtalk_enterprise_id = ? and external_subject_id = ?
        """,
        (discovery_container._test_dingtalk_enterprise_id, "staff-aggregate"),
    )
    assert candidate is not None
    assert int(candidate["observation_count"]) == 5
    messages = discovery_container.database.execute(
        """
        select conversation_type, conversation_id, safe_text, text_truncated,
               attachment_type, attachment_name, attachment_size, occurred_at
        from dingtalk_identity_candidate_message
        where candidate_id = ?
        order by received_at, id
        """,
        (candidate["id"],),
    )
    assert len(messages) == 5
    assert {row["conversation_type"] for row in messages} == {"direct", "group"}
    assert any(row["conversation_id"] == "group-aggregate" for row in messages)
    long_message = next(row for row in messages if row["text_truncated"])
    assert len(str(long_message["safe_text"])) == 1_000
    file_message = next(row for row in messages if row["attachment_type"])
    assert file_message["attachment_name"] == "排查资料.txt"
    assert int(file_message["attachment_size"]) == 128
    serialized_messages = str(messages)
    assert "fixture-download-code" not in serialized_messages
    assert duplicate_event["status"] == "REJECTED"


def test_projection_failure_keeps_channel_event_retryable_without_job(
    discovery_container,
    dingtalk_connector,
    monkeypatch: pytest.MonkeyPatch,
):
    connector_id = str(dingtalk_connector["id"])
    lease = discovery_container.runtime_control_service.acquire("runtime-discovery")
    assert lease is not None
    event, _ = discovery_container.runtime_control_service.receive(
        "runtime-discovery",
        str(lease["lease_token"]),
        _submission(
            connector_id,
            "event-projection-failure",
            sender_id="staff-projection-failure",
        ),
    )
    discovery_container.channel_outbox_publisher.publish_pending(limit=10)

    def fail_observation(_observation):
        raise RuntimeError("fixture projection failure")

    monkeypatch.setattr(
        discovery_container.identity_discovery_repository,
        "observe",
        fail_observation,
    )
    assert discovery_container.message_bus is not None
    with pytest.raises(RuntimeError, match="fixture projection failure"):
        discovery_container.message_bus.consume_channel_events(
            discovery_container.channel_dispatch_service.handle
        )

    stored = discovery_container.managed_channel_repository.get_event(str(event["id"]))
    assert stored["status"] == "DISPATCH_PENDING"
    assert stored["job_id"] is None
    assert (
        discovery_container.database.execute_one(
            "select count(*) as count from agent_job"
        )
        or {}
    ).get("count") == 0


def test_candidates_are_isolated_by_enterprise_and_keep_only_twenty_messages(
    discovery_container,
    dingtalk_connector,
):
    timestamp = "2026-08-03T00:00:00+00:00"
    other_enterprise = discovery_container.managed_channel_service.create_dingtalk_enterprise(
        name="另一个测试企业",
        actor_id="fixture-admin",
    )
    discovery_container.database.execute(
        """
        update dingtalk_enterprise
           set corp_id = 'corp-discovery-other', status = 'ACTIVE', verified_at = ?,
               verification_event_id = 'fixture-other-verification'
         where id = ?
        """,
        (timestamp, other_enterprise["id"]),
    )
    other = discovery_container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="另一个企业机器人",
            client_id="identity-discovery-client-other",
            client_secret="fixture-only-secret-other",
            dingtalk_enterprise_id=str(other_enterprise["id"]),
        ),
        actor_id="fixture-admin",
        enabled=True,
    )
    first_connector_id = str(dingtalk_connector["id"])
    other_connector_id = str(other["id"])
    for index in range(21):
        _dispatch(
            discovery_container,
            first_connector_id,
            _submission(
                first_connector_id,
                f"event-retention-{index:02d}",
                sender_id="staff-same-id",
                text=f"第 {index + 1} 条消息",
            ),
        )
    _dispatch(
        discovery_container,
        other_connector_id,
        _submission(
            other_connector_id,
            "event-other-tenant",
            sender_id="staff-same-id",
            text="其它企业消息",
            corp_id="corp-discovery-other",
        ),
    )

    candidates = discovery_container.database.execute(
        """
        select id, dingtalk_enterprise_id, observation_count
        from dingtalk_identity_candidate
        where external_subject_id = ?
        order by dingtalk_enterprise_id
        """,
        ("staff-same-id",),
    )
    assert {row["dingtalk_enterprise_id"] for row in candidates} == {
        discovery_container._test_dingtalk_enterprise_id,
        other_enterprise["id"],
    }
    primary = next(
        row
        for row in candidates
        if row["dingtalk_enterprise_id"]
        == discovery_container._test_dingtalk_enterprise_id
    )
    assert int(primary["observation_count"]) == 21
    message_count = discovery_container.database.execute_one(
        """
        select count(*) as count
        from dingtalk_identity_candidate_message
        where candidate_id = ?
        """,
        (primary["id"],),
    )
    assert message_count and int(message_count["count"]) == 20


def test_projection_failure_rolls_back_candidate_aggregate(
    discovery_container,
    dingtalk_connector,
):
    connector_id = str(dingtalk_connector["id"])
    lease = discovery_container.runtime_control_service.acquire("runtime-discovery")
    assert lease is not None
    event, _ = discovery_container.runtime_control_service.receive(
        "runtime-discovery",
        str(lease["lease_token"]),
        _submission(
            connector_id,
            "event-rollback",
            sender_id="staff-rollback",
        ),
    )
    observation = DingTalkIdentityObservation(
        source_ingress_event_id=str(event["id"]),
        received_at=str(event["received_at"]),
        occurred_at=str(event["received_at"]),
        dingtalk_enterprise_id=discovery_container._test_dingtalk_enterprise_id,
        external_subject_id="staff-rollback",
        display_name="事务回滚用户",
        connector_id="connector-does-not-exist",
        robot_code="robot-discovery",
        conversation_type="direct",
        conversation_id="private-rollback",
        message_kind="text",
        safe_text="不会提交",
        text_truncated=False,
        attachment_type="",
        attachment_name="",
        attachment_size=None,
    )

    with pytest.raises(Exception):
        discovery_container.identity_discovery_repository.observe(observation)

    assert (
        discovery_container.database.execute_one(
            """
            select count(*) as count
            from dingtalk_identity_candidate
            where external_subject_id = ?
            """,
            ("staff-rollback",),
        )
        or {}
    ).get("count") == 0
