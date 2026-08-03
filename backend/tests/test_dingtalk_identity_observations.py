from __future__ import annotations

import json

import pytest

from app.bootstrap import build_test_container
from app.modules.managed_channel.domain import DingTalkApplicationInput
from app.shared.config import Settings
from app.shared.exceptions import NonRetryableExecutionError


NOW = "2026-08-03T00:00:00+00:00"


def _container():
    container = build_test_container(
        Settings(
            database_dsn="sqlite:///:memory:",
            app_config_master_key="dingtalk-observation-test-key",
        ),
        migrate=True,
    )
    for user_id in ("observation-admin", "observation-user"):
        container.database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values (?, ?, ?, 'enabled', ?, ?)
            """,
            (user_id, user_id, user_id, NOW, NOW),
        )
    return container


def _active_enterprise(container, *, name: str, corp_id: str):
    enterprise = container.managed_channel_service.create_dingtalk_enterprise(
        name=name,
        actor_id="observation-admin",
    )
    container.database.execute(
        """
        update dingtalk_enterprise
           set corp_id = ?, status = 'ACTIVE', verified_at = ?,
               verification_event_id = ?
         where id = ?
        """,
        (corp_id, NOW, f"verify-{corp_id}", enterprise["id"]),
    )
    return container.managed_channel_service.get_dingtalk_enterprise(enterprise["id"])


def _connector(container, *, enterprise_id: str, client_id: str):
    return container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name=f"应用 {client_id}",
            client_id=client_id,
            client_secret=f"secret-{client_id}",
            dingtalk_enterprise_id=enterprise_id,
        ),
        actor_id="observation-admin",
        enabled=True,
    )


def _ingress(
    container,
    *,
    connector_id: str,
    event_id: str,
    received_at: str,
) -> str:
    ingress_id = f"ingress-{event_id}"
    container.database.execute(
        """
        insert into channel_ingress_event
          (id, source_type, connector_id, external_event_id, correlation_id,
           payload_hash, safe_summary_json, normalized_event_json,
           status, request_bytes, received_at)
        values (?, 'dingding_stream', ?, ?, ?, ?, '{}', ?,
                'ACCEPTED', 1, ?)
        """,
        (
            ingress_id,
            connector_id,
            event_id,
            f"correlation-{event_id}",
            f"hash-{event_id}",
            json.dumps({"msgId": event_id}),
            received_at,
        ),
    )
    return ingress_id


def test_identity_is_enterprise_scoped_and_observed_by_multiple_apps() -> None:
    container = _container()
    enterprise = _active_enterprise(
        container,
        name="观察企业",
        corp_id="corp-observation",
    )
    first = _connector(
        container,
        enterprise_id=enterprise["id"],
        client_id="ding-observation-first",
    )
    second = _connector(
        container,
        enterprise_id=enterprise["id"],
        client_id="ding-observation-second",
    )
    first_event = _ingress(
        container,
        connector_id=first["id"],
        event_id="first",
        received_at="2026-08-03T01:00:00+00:00",
    )
    identity = container.identity_repository.bind_dingtalk_identity(
        user_id="observation-user",
        dingtalk_enterprise_id=enterprise["id"],
        external_subject_id="staff-shared",
        display_name="初始昵称",
        source_connector_id=first["id"],
        source_ingress_event_id=first_event,
        observed_at="2026-08-03T01:00:00+00:00",
        replace_current=False,
    )
    second_event = _ingress(
        container,
        connector_id=second["id"],
        event_id="second",
        received_at="2026-08-03T02:00:00+00:00",
    )
    container.identity_repository.record_dingtalk_message_facts(
        identity_id=identity["id"],
        connector_id=second["id"],
        source_ingress_event_id=second_event,
        nickname="跨应用昵称",
        occurred_at="2026-08-03T02:00:00+00:00",
        received_at="2026-08-03T02:00:00+00:00",
    )

    current = container.identity_repository.get_external_identity(identity["id"])
    observations = container.identity_repository.list_dingtalk_application_observations(
        identity["id"]
    )
    assert current["connector_id"] == ""
    assert current["dingtalk_enterprise_id"] == enterprise["id"]
    assert current["display_name"] == "跨应用昵称"
    assert {item["application_name"] for item in observations} == {
        first["name"],
        second["name"],
    }


def test_nickname_cursor_is_monotonic_idempotent_and_falls_back_from_bad_clock() -> None:
    container = _container()
    enterprise = _active_enterprise(
        container,
        name="昵称企业",
        corp_id="corp-nickname",
    )
    connector = _connector(
        container,
        enterprise_id=enterprise["id"],
        client_id="ding-nickname",
    )
    initial_event = _ingress(
        container,
        connector_id=connector["id"],
        event_id="nickname-initial",
        received_at="2026-08-03T01:00:00+00:00",
    )
    identity = container.identity_repository.bind_dingtalk_identity(
        user_id="observation-user",
        dingtalk_enterprise_id=enterprise["id"],
        external_subject_id="staff-nickname",
        display_name="初始昵称",
        source_connector_id=connector["id"],
        source_ingress_event_id=initial_event,
        observed_at="2026-08-03T01:00:00+00:00",
        replace_current=False,
    )

    def observe(
        event: str,
        nickname: str,
        occurred_at: str,
        received_at: str,
    ) -> None:
        ingress = _ingress(
            container,
            connector_id=connector["id"],
            event_id=event,
            received_at=received_at,
        )
        container.identity_repository.record_dingtalk_message_facts(
            identity_id=identity["id"],
            connector_id=connector["id"],
            source_ingress_event_id=ingress,
            nickname=nickname,
            occurred_at=occurred_at,
            received_at=received_at,
        )

    observe(
        "nickname-new",
        "最新昵称",
        "2026-08-03T03:00:00+00:00",
        "2026-08-03T03:00:00+00:00",
    )
    observe(
        "nickname-old",
        "旧昵称",
        "2026-08-03T02:00:00+00:00",
        "2026-08-03T04:00:00+00:00",
    )
    observe(
        "nickname-empty",
        "",
        "2026-08-03T04:00:00+00:00",
        "2026-08-03T04:00:00+00:00",
    )
    observe(
        "nickname-bad-clock",
        "时钟回退昵称",
        "2099-01-01T00:00:00+00:00",
        "2026-08-03T05:00:00+00:00",
    )
    bad_clock_ingress = "ingress-nickname-bad-clock"
    container.identity_repository.record_dingtalk_message_facts(
        identity_id=identity["id"],
        connector_id=connector["id"],
        source_ingress_event_id=bad_clock_ingress,
        nickname="时钟回退昵称",
        occurred_at="2099-01-01T00:00:00+00:00",
        received_at="2026-08-03T05:00:00+00:00",
    )

    current = container.database.execute_one(
        "select * from user_external_identity where id = ?",
        (identity["id"],),
    )
    audits = container.database.execute(
        """
        select * from dingtalk_identity_nickname_audit
         where external_identity_id = ? order by observed_at, source_ingress_event_id
        """,
        (identity["id"],),
    )
    assert current is not None
    assert current["display_name"] == "时钟回退昵称"
    assert current["display_name_observed_at"] == "2026-08-03T05:00:00+00:00"
    assert [row["current_nickname"] for row in audits] == [
        "最新昵称",
        "时钟回退昵称",
    ]


def test_same_enterprise_rebind_requires_confirmation_but_other_enterprise_is_independent() -> None:
    container = _container()
    first_enterprise = _active_enterprise(
        container,
        name="企业一",
        corp_id="corp-one",
    )
    second_enterprise = _active_enterprise(
        container,
        name="企业二",
        corp_id="corp-two",
    )
    first_connector = _connector(
        container,
        enterprise_id=first_enterprise["id"],
        client_id="ding-rebind-one",
    )
    second_connector = _connector(
        container,
        enterprise_id=second_enterprise["id"],
        client_id="ding-rebind-two",
    )

    def bind(
        enterprise_id: str,
        connector_id: str,
        staff_id: str,
        event_id: str,
        *,
        replace: bool,
    ):
        ingress = _ingress(
            container,
            connector_id=connector_id,
            event_id=event_id,
            received_at="2026-08-03T01:00:00+00:00",
        )
        return container.identity_repository.bind_dingtalk_identity(
            user_id="observation-user",
            dingtalk_enterprise_id=enterprise_id,
            external_subject_id=staff_id,
            display_name=staff_id,
            source_connector_id=connector_id,
            source_ingress_event_id=ingress,
            observed_at="2026-08-03T01:00:00+00:00",
            replace_current=replace,
        )

    original = bind(
        first_enterprise["id"],
        first_connector["id"],
        "staff-old",
        "rebind-old",
        replace=False,
    )
    with pytest.raises(NonRetryableExecutionError) as confirmation:
        bind(
            first_enterprise["id"],
            first_connector["id"],
            "staff-new",
            "rebind-new-unconfirmed",
            replace=False,
        )
    assert confirmation.value.error_code == "dingtalk_rebind_confirmation_required"
    replacement = bind(
        first_enterprise["id"],
        first_connector["id"],
        "staff-new",
        "rebind-new-confirmed",
        replace=True,
    )
    other = bind(
        second_enterprise["id"],
        second_connector["id"],
        "staff-new",
        "other-enterprise",
        replace=False,
    )

    assert container.identity_repository.get_external_identity(original["id"])[
        "status"
    ] == "unbound"
    assert replacement["status"] == "enabled"
    assert other["status"] == "enabled"
    current = container.database.execute_one(
        """
        select count(*) as count from user_external_identity
         where user_id = 'observation-user' and provider = 'dingtalk'
           and status in ('enabled', 'disabled')
        """
    )
    assert current == {"count": 2}
